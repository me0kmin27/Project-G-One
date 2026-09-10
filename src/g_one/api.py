from datetime import datetime, timedelta, timezone
import hmac
import ipaddress
import subprocess

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .auth import CurrentPrincipal, Principal, encode_token
from .db import DatabaseSession
from .models import AuditEvent, Device, SupportRequest, VpnNetwork, VpnPeer
from .schemas import (
    AuditEventRead,
    ConsoleSessionCreate,
    DeviceCreate,
    DeviceRead,
    PrincipalRead,
    SessionToken,
    SupportDecision,
    SupportRequestCreate,
    SupportRequestRead,
    VpnNetworkCreate,
    VpnNetworkRead,
    VpnPeerCreate,
    VpnPeerEnrollment,
    VpnPeerRead,
)
from .wireguard import (
    address_belongs,
    apply_config,
    generate_keypair,
    public_key,
    render_client_config,
    render_server_config,
    validate_key,
)

router = APIRouter()


@router.post("/api/v1/session/console", response_model=SessionToken)
def create_console_session(body: ConsoleSessionCreate, request: Request) -> SessionToken:
    settings = request.app.state.settings
    if not hmac.compare_digest(body.password, settings.console_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid console credentials")
    principal = Principal(
        body.subject,
        body.tenant_id,
        frozenset({"tenant_admin", "support", "auditor"}),
    )
    return SessionToken(access_token=encode_token(principal, settings))


@router.get("/api/v1/me", response_model=PrincipalRead)
def get_current_principal(principal: CurrentPrincipal) -> PrincipalRead:
    return PrincipalRead(
        subject=principal.subject,
        tenant_id=principal.tenant_id,
        roles=sorted(principal.roles),
    )


def now() -> datetime:
    return datetime.now(timezone.utc)


def audit(session, principal, action: str, target_type: str, target_id: str, **details) -> None:
    session.add(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome="success",
            details=details,
        )
    )


@router.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def ready(session: DatabaseSession) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.post("/api/v1/devices", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
def create_device(body: DeviceCreate, principal: CurrentPrincipal, session: DatabaseSession):
    device = Device(tenant_id=principal.tenant_id, owner_id=principal.subject, name=body.name)
    session.add(device)
    session.flush()
    audit(session, principal, "device.registered", "device", device.id)
    session.commit()
    return device


@router.get("/api/v1/devices", response_model=list[DeviceRead])
def list_devices(principal: CurrentPrincipal, session: DatabaseSession):
    statement = select(Device).where(Device.tenant_id == principal.tenant_id)
    if principal.roles.isdisjoint({"tenant_admin", "support"}):
        statement = statement.where(Device.owner_id == principal.subject)
    return session.scalars(statement.order_by(Device.created_at)).all()


@router.delete("/api/v1/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_id: str, principal: CurrentPrincipal, session: DatabaseSession) -> None:
    device = session.scalar(
        select(Device).where(Device.tenant_id == principal.tenant_id, Device.id == device_id)
    )
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    if device.owner_id != principal.subject and "tenant_admin" not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "device ownership required")
    if device.status != "revoked":
        device.status = "revoked"
        device.revoked_at = now()
        audit(session, principal, "device.revoked", "device", device.id)
        session.commit()


@router.post(
    "/api/v1/support-requests",
    response_model=SupportRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_support_request(
    body: SupportRequestCreate, principal: CurrentPrincipal, session: DatabaseSession
):
    principal.require_role("support", "tenant_admin")
    device = session.scalar(
        select(Device).where(
            Device.tenant_id == principal.tenant_id,
            Device.id == body.target_device_id,
            Device.status == "registered",
        )
    )
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "active device not found")
    request = SupportRequest(
        tenant_id=principal.tenant_id,
        requester_id=principal.subject,
        target_device_id=device.id,
        purpose=body.purpose,
        permissions=sorted(permission.value for permission in body.permissions),
        expires_at=now() + timedelta(seconds=body.lifetime_seconds),
    )
    session.add(request)
    session.flush()
    audit(
        session,
        principal,
        "support.requested",
        "support_request",
        request.id,
        permissions=request.permissions,
    )
    session.commit()
    return request


@router.get("/api/v1/support-requests", response_model=list[SupportRequestRead])
def list_support_requests(principal: CurrentPrincipal, session: DatabaseSession):
    statement = select(SupportRequest).where(SupportRequest.tenant_id == principal.tenant_id)
    if principal.roles.isdisjoint({"tenant_admin", "support"}):
        owned_device_ids = select(Device.id).where(
            Device.tenant_id == principal.tenant_id,
            Device.owner_id == principal.subject,
        )
        statement = statement.where(SupportRequest.target_device_id.in_(owned_device_ids))
    return session.scalars(statement.order_by(SupportRequest.created_at.desc()).limit(200)).all()


def get_support_request(session, tenant_id: str, request_id: str) -> SupportRequest:
    request = session.scalar(
        select(SupportRequest).where(
            SupportRequest.tenant_id == tenant_id, SupportRequest.id == request_id
        )
    )
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "support request not found")
    return request


@router.post("/api/v1/support-requests/{request_id}/decision", response_model=SupportRequestRead)
def decide_support_request(
    request_id: str,
    body: SupportDecision,
    principal: CurrentPrincipal,
    session: DatabaseSession,
):
    request = get_support_request(session, principal.tenant_id, request_id)
    device = session.scalar(
        select(Device).where(
            Device.tenant_id == principal.tenant_id, Device.id == request.target_device_id
        )
    )
    if device is None or device.owner_id != principal.subject:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "target device ownership required")
    if request.state != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "support request is no longer pending")
    if request.expires_at.replace(tzinfo=timezone.utc) <= now():
        request.state = "expired"
        audit(session, principal, "support.expired", "support_request", request.id)
        session.commit()
        raise HTTPException(status.HTTP_410_GONE, "support request expired")
    request.state = "accepted" if body.accept else "denied"
    request.decided_at = now()
    audit(session, principal, f"support.{request.state}", "support_request", request.id)
    session.commit()
    return request


@router.post("/api/v1/support-requests/{request_id}/end", response_model=SupportRequestRead)
def end_support_request(request_id: str, principal: CurrentPrincipal, session: DatabaseSession):
    request = get_support_request(session, principal.tenant_id, request_id)
    device = session.scalar(
        select(Device).where(
            Device.tenant_id == principal.tenant_id, Device.id == request.target_device_id
        )
    )
    is_target = device is not None and device.owner_id == principal.subject
    if principal.subject != request.requester_id and not is_target:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "session participant required")
    if request.state != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "support session is not active")
    request.state = "ended"
    request.ended_at = now()
    audit(session, principal, "support.ended", "support_request", request.id)
    session.commit()
    return request


@router.get("/api/v1/audit-events", response_model=list[AuditEventRead])
def list_audit_events(principal: CurrentPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin", "auditor")
    return session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == principal.tenant_id)
        .order_by(AuditEvent.occurred_at.desc())
        .limit(200)
    ).all()


def get_vpn_network(session, tenant_id: str) -> VpnNetwork:
    network = session.scalar(select(VpnNetwork).where(VpnNetwork.tenant_id == tenant_id))
    if network is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VPN network not configured")
    return network


def network_response(network: VpnNetwork, request: Request) -> VpnNetworkRead:
    settings = request.app.state.settings
    return VpnNetworkRead.model_validate(network).model_copy(
        update={
            "server_public_key": public_key(settings.wireguard_private_key)
            if settings.wireguard_private_key else None,
            "runtime_enabled": settings.wireguard_apply,
        }
    )


def sync_vpn(session, network: VpnNetwork, request: Request) -> None:
    settings = request.app.state.settings
    if not settings.wireguard_private_key:
        return
    peers = session.scalars(
        select(VpnPeer).where(
            VpnPeer.network_id == network.id,
            VpnPeer.tenant_id == network.tenant_id,
        )
    ).all()
    try:
        apply_config(render_server_config(network, peers, settings.wireguard_private_key), settings)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"WireGuard apply failed: {exc}"
        ) from exc


@router.put("/api/v1/vpn/network", response_model=VpnNetworkRead)
def configure_vpn_network(
    body: VpnNetworkCreate,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
):
    principal.require_role("tenant_admin")
    try:
        address_cidr = str(ipaddress.ip_interface(body.address_cidr))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid VPN interface address"
        ) from exc
    network = session.scalar(select(VpnNetwork).where(VpnNetwork.tenant_id == principal.tenant_id))
    if network is None:
        network = VpnNetwork(tenant_id=principal.tenant_id)
        session.add(network)
    network.name = body.name.strip()
    network.address_cidr = address_cidr
    network.endpoint = body.endpoint.strip()
    network.listen_port = body.listen_port
    network.dns = body.dns.strip() if body.dns else None
    network.updated_at = now()
    session.flush()
    audit(session, principal, "vpn.network.configured", "vpn_network", network.id)
    sync_vpn(session, network, request)
    session.commit()
    return network_response(network, request)


@router.get("/api/v1/vpn/network", response_model=VpnNetworkRead)
def read_vpn_network(request: Request, principal: CurrentPrincipal, session: DatabaseSession):
    return network_response(get_vpn_network(session, principal.tenant_id), request)


@router.get("/api/v1/vpn/peers", response_model=list[VpnPeerRead])
def list_vpn_peers(principal: CurrentPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin", "support")
    return session.scalars(
        select(VpnPeer)
        .where(VpnPeer.tenant_id == principal.tenant_id)
        .order_by(VpnPeer.created_at)
    ).all()


@router.post(
    "/api/v1/vpn/peers",
    response_model=VpnPeerEnrollment,
    status_code=status.HTTP_201_CREATED,
)
def create_vpn_peer(
    body: VpnPeerCreate,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
):
    principal.require_role("tenant_admin")
    network = get_vpn_network(session, principal.tenant_id)
    try:
        address = address_belongs(network.address_cidr, body.address)
        client_private, generated_public = generate_keypair()
        peer_public = validate_key(body.public_key) if body.public_key else generated_public
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    peer = VpnPeer(
        tenant_id=principal.tenant_id,
        network_id=network.id,
        name=body.name.strip(),
        public_key=peer_public,
        address=address,
        persistent_keepalive=body.persistent_keepalive,
    )
    session.add(peer)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "peer key or address already exists") from exc
    audit(session, principal, "vpn.peer.created", "vpn_peer", peer.id, address=address)
    sync_vpn(session, network, request)
    session.commit()
    config = None
    settings = request.app.state.settings
    if body.public_key is None and settings.wireguard_private_key:
        config = render_client_config(
            network, client_private, address, public_key(settings.wireguard_private_key)
        )
    return VpnPeerEnrollment.model_validate(peer).model_copy(update={"client_config": config})


@router.delete("/api/v1/vpn/peers/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_vpn_peer(
    peer_id: str,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
):
    principal.require_role("tenant_admin")
    peer = session.scalar(
        select(VpnPeer).where(
            VpnPeer.id == peer_id, VpnPeer.tenant_id == principal.tenant_id
        )
    )
    if peer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VPN peer not found")
    peer.enabled = False
    peer.revoked_at = now()
    audit(session, principal, "vpn.peer.revoked", "vpn_peer", peer.id)
    sync_vpn(session, get_vpn_network(session, principal.tenant_id), request)
    session.commit()
