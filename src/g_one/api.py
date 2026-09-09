from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, text

from .auth import CurrentPrincipal, Principal, encode_token
from .db import DatabaseSession
from .models import AuditEvent, Device, SupportRequest
from .schemas import (
    AuditEventRead,
    DevelopmentSessionCreate,
    DeviceCreate,
    DeviceRead,
    PrincipalRead,
    SessionToken,
    SupportDecision,
    SupportRequestCreate,
    SupportRequestRead,
)

router = APIRouter()


@router.post("/api/v1/session/development", response_model=SessionToken)
def create_development_session(body: DevelopmentSessionCreate, request: Request) -> SessionToken:
    settings = request.app.state.settings
    if settings.environment != "development":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    allowed_roles = {"user", "tenant_admin", "support", "auditor"}
    if not body.roles or not body.roles.issubset(allowed_roles):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid role")
    principal = Principal(body.subject, body.tenant_id, frozenset(body.roles))
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
