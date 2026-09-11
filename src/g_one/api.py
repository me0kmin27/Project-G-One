from datetime import datetime, timedelta, timezone
import hmac
import hashlib
import ipaddress
import secrets
import subprocess
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from .auth import CurrentPrincipal, Principal, encode_token
from .db import DatabaseSession
from .models import ApiToken, AuditEvent, Device, InstallationState, SupportRequest, VpnNetwork, VpnPeer, Workspace, WorkspaceUser
from .passwords import hash_password, verify_password
from .schemas import (
    AdministratorSetup,
    AuditEventRead,
    ApiTokenCreate,
    ApiTokenIssued,
    ApiTokenRead,
    ClientBootstrap,
    ClientBootstrapRequest,
    ConsoleSessionCreate,
    DeviceCreate,
    DeviceRead,
    PrincipalRead,
    SessionToken,
    SetupStatus,
    RoleRead,
    SupportDecision,
    SupportRequestCreate,
    SupportRequestRead,
    VpnNetworkCreate,
    VpnNetworkRead,
    VpnPeerCreate,
    VpnPeerEnrollment,
    VpnPeerRead,
    VpnPeerRoutesUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
    UserSessionCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from .wireguard import (
    address_belongs,
    apply_config,
    generate_keypair,
    normalize_allowed_ips,
    public_key,
    render_client_config,
    render_server_config,
    validate_key,
)

router = APIRouter()

ROLES = {
    "tenant_admin": ("워크스페이스 관리자", ["workspace.manage", "tokens.manage", "users.manage", "roles.manage", "devices.manage", "vpn.manage", "support.manage", "audit.read"]),
    "support": ("지원 담당자", ["devices.read", "vpn.read", "support.manage"]),
    "auditor": ("감사 담당자", ["audit.read"]),
    "member": ("일반 사용자", ["devices.self", "support.consent"]),
}
TOKEN_SCOPES = {"devices:read", "devices:write", "vpn:read", "support:read", "audit:read"}


@router.post("/api/v1/session/console", response_model=SessionToken)
def create_console_session(
    body: ConsoleSessionCreate, request: Request, session: DatabaseSession
) -> SessionToken:
    settings = request.app.state.settings
    if not hmac.compare_digest(body.password, settings.console_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid console credentials")
    user = session.scalar(
        select(WorkspaceUser).where(
            WorkspaceUser.tenant_id == body.tenant_id,
            WorkspaceUser.subject == body.subject,
            WorkspaceUser.status == "active",
        )
    )
    if user is None or "tenant_admin" not in user.roles:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "provisioned administrator required")
    principal = Principal(user.subject, user.tenant_id, frozenset(user.roles))
    return SessionToken(access_token=encode_token(principal, settings))


@router.get("/api/v1/setup/status", response_model=SetupStatus)
def read_setup_status(session: DatabaseSession) -> SetupStatus:
    state = session.get(InstallationState, 1)
    return SetupStatus(administrator_required=state is None or not state.initialized)


@router.post("/api/v1/setup/administrator", response_model=SessionToken, status_code=status.HTTP_201_CREATED)
def create_initial_administrator(
    body: AdministratorSetup, request: Request, session: DatabaseSession
) -> SessionToken:
    claimed = session.execute(
        update(InstallationState)
        .where(InstallationState.id == 1, InstallationState.initialized.is_(False))
        .values(initialized=True)
    )
    if claimed.rowcount != 1:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "administrator has already been configured")

    user = WorkspaceUser(
        tenant_id=body.tenant_id,
        subject=body.subject,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        roles=["tenant_admin"],
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "administrator account already exists") from exc
    principal = Principal(user.subject, user.tenant_id, frozenset(user.roles))
    audit(session, principal, "installation.admin_created", "user", user.id)
    session.commit()
    return SessionToken(access_token=encode_token(principal, request.app.state.settings))


@router.post("/api/v1/session/login", response_model=SessionToken)
def create_user_session(
    body: UserSessionCreate, request: Request, session: DatabaseSession
) -> SessionToken:
    subject = body.subject.strip()
    tenant_id = body.tenant_id.strip()
    user = session.scalar(
        select(WorkspaceUser).where(
            WorkspaceUser.tenant_id == tenant_id,
            WorkspaceUser.subject == subject,
            WorkspaceUser.status == "active",
        )
    )
    if user is None:
        claimed = session.execute(
            update(InstallationState)
            .where(InstallationState.id == 1, InstallationState.initialized.is_(False))
            .values(initialized=True)
        )
        if claimed.rowcount == 1:
            user = WorkspaceUser(
                tenant_id=tenant_id,
                subject=subject,
                display_name=subject,
                password_hash=hash_password(body.password),
                roles=["tenant_admin"],
            )
            session.add(user)
            session.flush()
            principal = Principal(user.subject, user.tenant_id, frozenset(user.roles))
            audit(session, principal, "installation.admin_created", "user", user.id)
            session.commit()
    if user is None or not verify_password(body.password, user.password_hash):
        session.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid account credentials")
    principal = Principal(user.subject, user.tenant_id, frozenset(user.roles))
    workspace = session.get(Workspace, user.tenant_id)
    if workspace is None and "tenant_admin" not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace has not been created")
    audit(session, principal, "session.login", "user", user.id)
    session.commit()
    return SessionToken(access_token=encode_token(principal, request.app.state.settings))


def require_provisioned_workspace(
    principal: CurrentPrincipal, session: DatabaseSession
) -> Principal:
    workspace = session.get(Workspace, principal.tenant_id)
    if workspace is None or workspace.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "active workspace required")
    return principal


ProvisionedPrincipal = Annotated[Principal, Depends(require_provisioned_workspace)]


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


def validate_roles(roles: set[str]) -> list[str]:
    unknown = roles - ROLES.keys()
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown roles: {', '.join(sorted(unknown))}")
    return sorted(roles)


@router.get("/api/v1/workspace", response_model=WorkspaceRead)
def read_workspace(principal: CurrentPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    workspace = session.get(Workspace, principal.tenant_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace has not been created")
    return workspace


@router.put("/api/v1/workspace", response_model=WorkspaceRead)
def update_workspace(body: WorkspaceUpdate, principal: CurrentPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    workspace = session.get(Workspace, principal.tenant_id)
    if workspace is None:
        workspace = Workspace(id=principal.tenant_id, name=body.name.strip())
        session.add(workspace)
    else:
        workspace.name = body.name.strip()
        workspace.updated_at = now()
    audit(session, principal, "workspace.updated", "workspace", principal.tenant_id)
    session.commit()
    return workspace


@router.get("/api/v1/roles", response_model=list[RoleRead])
def list_roles(principal: ProvisionedPrincipal):
    principal.require_role("tenant_admin")
    return [RoleRead(id=key, name=value[0], permissions=value[1]) for key, value in ROLES.items()]


@router.get("/api/v1/users", response_model=list[UserRead])
def list_users(principal: ProvisionedPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    return session.scalars(select(WorkspaceUser).where(WorkspaceUser.tenant_id == principal.tenant_id).order_by(WorkspaceUser.created_at)).all()


@router.post("/api/v1/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, principal: ProvisionedPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    if session.get(Workspace, principal.tenant_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "create the workspace before adding users")
    network = session.scalar(select(VpnNetwork).where(VpnNetwork.tenant_id == principal.tenant_id))
    try:
        vpn_address = address_belongs(network.address_cidr, body.vpn_address) if network and body.vpn_address else None
        allowed_ips = normalize_allowed_ips(body.allowed_ips) if body.allowed_ips else ""
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    user = WorkspaceUser(tenant_id=principal.tenant_id, subject=body.subject.strip(), display_name=body.display_name.strip(), email=body.email.strip() if body.email else None, password_hash=hash_password(body.password), roles=validate_roles(body.roles), vpn_address=vpn_address, allowed_ips=allowed_ips)
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "user already exists") from exc
    audit(session, principal, "user.created", "user", user.id, roles=user.roles)
    session.commit()
    return user


@router.put("/api/v1/users/{user_id}", response_model=UserRead)
def update_user(user_id: str, body: UserUpdate, principal: ProvisionedPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    user = session.scalar(select(WorkspaceUser).where(WorkspaceUser.id == user_id, WorkspaceUser.tenant_id == principal.tenant_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    network = session.scalar(select(VpnNetwork).where(VpnNetwork.tenant_id == principal.tenant_id))
    try:
        user.vpn_address = address_belongs(network.address_cidr, body.vpn_address) if network and body.vpn_address else None
        user.allowed_ips = normalize_allowed_ips(body.allowed_ips) if body.allowed_ips else ""
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    user.display_name, user.email = body.display_name.strip(), body.email.strip() if body.email else None
    user.roles, user.status, user.updated_at = validate_roles(body.roles), body.status, now()
    user.policy_version += 1
    if body.password:
        user.password_hash = hash_password(body.password)
    audit(session, principal, "user.updated", "user", user.id, roles=user.roles, status=user.status)
    session.commit()
    return user


@router.post("/api/v1/client/bootstrap", response_model=ClientBootstrap)
def bootstrap_client(
    body: ClientBootstrapRequest,
    request: Request,
    principal: ProvisionedPrincipal,
    session: DatabaseSession,
):
    """Return all device settings only after bearer-token authentication."""
    user = session.scalar(select(WorkspaceUser).where(
        WorkspaceUser.tenant_id == principal.tenant_id,
        WorkspaceUser.subject == principal.subject,
        WorkspaceUser.status == "active",
    ))
    if user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "active provisioned account required")

    device = session.scalar(select(Device).where(
        Device.tenant_id == principal.tenant_id,
        Device.owner_id == principal.subject,
        Device.name == body.device_name,
        Device.revoked_at.is_(None),
    ))
    if device is None:
        device = Device(tenant_id=principal.tenant_id, owner_id=principal.subject, name=body.device_name)
        session.add(device)

    network = session.scalar(select(VpnNetwork).where(VpnNetwork.tenant_id == principal.tenant_id))
    settings = request.app.state.settings
    vpn_profile = None
    if network and user.vpn_address and settings.wireguard_private_key:
        address = address_belongs(network.address_cidr, user.vpn_address)
        routes = normalize_allowed_ips(
            user.allowed_ips or str(ipaddress.ip_interface(network.address_cidr).network)
        )
        private_key, peer_public_key = generate_keypair()
        peer = session.scalar(select(VpnPeer).where(
            VpnPeer.tenant_id == principal.tenant_id,
            VpnPeer.network_id == network.id,
            VpnPeer.address == address,
        ))
        if peer is None:
            peer = VpnPeer(tenant_id=principal.tenant_id, network_id=network.id, address=address)
            session.add(peer)
        peer.name = f"client:{principal.subject}:{body.device_name}"
        peer.public_key = peer_public_key
        peer.allowed_ips = routes
        peer.persistent_keepalive = 25
        peer.enabled = True
        peer.revoked_at = None
        session.flush()
        sync_vpn(session, network, request)
        vpn_profile = render_client_config(
            network, private_key, address, public_key(settings.wireguard_private_key), routes
        )

    session.flush()
    audit(session, principal, "client.bootstrapped", "device", device.id, vpn=bool(vpn_profile))
    session.commit()
    return ClientBootstrap(
        version=user.policy_version,
        user=UserRead.model_validate(user),
        vpn=network_response(network, request) if network else None,
        vpn_profile=vpn_profile,
        file_shares=[],
        device=DeviceRead.model_validate(device),
    )


@router.post("/api/v1/client/vpn/enroll", response_model=VpnPeerEnrollment)
def enroll_client_vpn(
    body: ClientVpnEnrollment,
    request: Request,
    principal: ProvisionedPrincipal,
    session: DatabaseSession,
):
    """Rotate and return the current user's device-specific WireGuard profile."""
    user = session.scalar(select(WorkspaceUser).where(
        WorkspaceUser.tenant_id == principal.tenant_id,
        WorkspaceUser.subject == principal.subject,
        WorkspaceUser.status == "active",
    ))
    if user is None or not user.vpn_address:
        raise HTTPException(status.HTTP_409_CONFLICT, "VPN address is not assigned to this user")
    network = get_vpn_network(session, principal.tenant_id)
    settings = request.app.state.settings
    if not settings.wireguard_private_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "VPN server key is not configured")

    try:
        address = address_belongs(network.address_cidr, user.vpn_address)
        routes = normalize_allowed_ips(
            user.allowed_ips or str(ipaddress.ip_interface(network.address_cidr).network)
        )
        private_key, peer_public_key = generate_keypair()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    peer_name = f"client:{principal.subject}:{body.device_name.strip()}"
    peer = session.scalar(select(VpnPeer).where(
        VpnPeer.tenant_id == principal.tenant_id,
        VpnPeer.network_id == network.id,
        VpnPeer.address == address,
    ))
    if peer is None:
        peer = VpnPeer(tenant_id=principal.tenant_id, network_id=network.id, address=address)
        session.add(peer)
    peer.name = peer_name
    peer.public_key = peer_public_key
    peer.allowed_ips = routes
    peer.persistent_keepalive = 25
    peer.enabled = True
    peer.revoked_at = None
    session.flush()
    audit(session, principal, "vpn.client.enrolled", "vpn_peer", peer.id, device=body.device_name.strip())
    sync_vpn(session, network, request)
    session.commit()
    config = render_client_config(
        network, private_key, address, public_key(settings.wireguard_private_key), routes
    )
    return VpnPeerEnrollment.model_validate(peer).model_copy(update={"client_config": config})


@router.get("/api/v1/tokens", response_model=list[ApiTokenRead])
def list_tokens(principal: ProvisionedPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    return session.scalars(select(ApiToken).where(ApiToken.tenant_id == principal.tenant_id).order_by(ApiToken.created_at.desc())).all()


@router.post("/api/v1/tokens", response_model=ApiTokenIssued, status_code=status.HTTP_201_CREATED)
def create_api_token(body: ApiTokenCreate, principal: ProvisionedPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    unknown = body.scopes - TOKEN_SCOPES
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown scopes: {', '.join(sorted(unknown))}")
    secret = "gone_" + secrets.token_urlsafe(32)
    token = ApiToken(tenant_id=principal.tenant_id, name=body.name.strip(), token_hash=hashlib.sha256(secret.encode()).hexdigest(), prefix=secret[:12], scopes=sorted(body.scopes), created_by=principal.subject, expires_at=now() + timedelta(days=body.lifetime_days))
    session.add(token)
    session.flush()
    audit(session, principal, "token.created", "api_token", token.id, scopes=token.scopes)
    session.commit()
    public = ApiTokenRead.model_validate(token)
    return ApiTokenIssued(**public.model_dump(), token=secret)


@router.delete("/api/v1/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_token(token_id: str, principal: ProvisionedPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    token = session.scalar(select(ApiToken).where(ApiToken.id == token_id, ApiToken.tenant_id == principal.tenant_id))
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
    if token.revoked_at is None:
        token.revoked_at = now()
        audit(session, principal, "token.revoked", "api_token", token.id)
        session.commit()


@router.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def ready(session: DatabaseSession) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.post("/api/v1/devices", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
def create_device(body: DeviceCreate, principal: ProvisionedPrincipal, session: DatabaseSession):
    device = Device(tenant_id=principal.tenant_id, owner_id=principal.subject, name=body.name)
    session.add(device)
    session.flush()
    audit(session, principal, "device.registered", "device", device.id)
    session.commit()
    return device


@router.get("/api/v1/devices", response_model=list[DeviceRead])
def list_devices(principal: ProvisionedPrincipal, session: DatabaseSession):
    statement = select(Device).where(Device.tenant_id == principal.tenant_id)
    if principal.roles.isdisjoint({"tenant_admin", "support"}):
        statement = statement.where(Device.owner_id == principal.subject)
    return session.scalars(statement.order_by(Device.created_at)).all()


@router.delete("/api/v1/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_id: str, principal: ProvisionedPrincipal, session: DatabaseSession) -> None:
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
    body: SupportRequestCreate, principal: ProvisionedPrincipal, session: DatabaseSession
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
def list_support_requests(principal: ProvisionedPrincipal, session: DatabaseSession):
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
    principal: ProvisionedPrincipal,
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
def end_support_request(request_id: str, principal: ProvisionedPrincipal, session: DatabaseSession):
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
def list_audit_events(principal: ProvisionedPrincipal, session: DatabaseSession):
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
            "network_route": str(ipaddress.ip_interface(network.address_cidr).network),
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
    principal: ProvisionedPrincipal,
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
def read_vpn_network(request: Request, principal: ProvisionedPrincipal, session: DatabaseSession):
    return network_response(get_vpn_network(session, principal.tenant_id), request)


@router.get("/api/v1/vpn/peers", response_model=list[VpnPeerRead])
def list_vpn_peers(principal: ProvisionedPrincipal, session: DatabaseSession):
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
    principal: ProvisionedPrincipal,
    session: DatabaseSession,
):
    principal.require_role("tenant_admin")
    network = get_vpn_network(session, principal.tenant_id)
    try:
        address = address_belongs(network.address_cidr, body.address)
        allowed_ips = normalize_allowed_ips(
            body.allowed_ips or str(ipaddress.ip_interface(network.address_cidr).network)
        )
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
        allowed_ips=allowed_ips,
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
            network, client_private, address, public_key(settings.wireguard_private_key), allowed_ips
        )
    return VpnPeerEnrollment.model_validate(peer).model_copy(update={"client_config": config})


@router.put("/api/v1/vpn/peers/{peer_id}/routes", response_model=VpnPeerRead)
def update_vpn_peer_routes(
    peer_id: str,
    body: VpnPeerRoutesUpdate,
    request: Request,
    principal: ProvisionedPrincipal,
    session: DatabaseSession,
):
    principal.require_role("tenant_admin")
    peer = session.scalar(
        select(VpnPeer).where(VpnPeer.id == peer_id, VpnPeer.tenant_id == principal.tenant_id)
    )
    if peer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VPN peer not found")
    try:
        peer.allowed_ips = normalize_allowed_ips(body.allowed_ips)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    audit(
        session,
        principal,
        "vpn.peer.routes.updated",
        "vpn_peer",
        peer.id,
        allowed_ips=peer.allowed_ips,
    )
    sync_vpn(session, get_vpn_network(session, principal.tenant_id), request)
    session.commit()
    session.refresh(peer)
    return peer


@router.delete("/api/v1/vpn/peers/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_vpn_peer(
    peer_id: str,
    request: Request,
    principal: ProvisionedPrincipal,
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
