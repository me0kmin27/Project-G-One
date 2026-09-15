from datetime import datetime, timedelta, timezone
import hmac
import hashlib
import ipaddress
import io
import json
from pathlib import Path
import secrets
import subprocess
import zipfile

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from .auth import CurrentPrincipal, Principal, encode_token
from .db import DatabaseSession
from .models import ApiToken, AuditEvent, ClientDeploymentProfile, ClientEnrollmentCode, Device, FileServer, InstallationState, SupportRequest, VpnNetwork, VpnPeer, WorkspaceUser
from .passwords import hash_password, verify_password
from .schemas import (
    AdministratorSetup,
    AuditEventRead,
    ApiTokenCreate,
    ApiTokenIssued,
    ApiTokenRead,
    ClientBootstrap,
    ClientBootstrapRequest,
    ClientVpnEnrollment,
    DeploymentProfileCreate,
    DeploymentProfileRead,
    ConsoleSessionCreate,
    DeviceCreate,
    DeviceRead,
    FileServerCreate,
    FileServerRead,
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
    "tenant_admin": ("조직 관리자", ["tokens.manage", "users.manage", "roles.manage", "devices.manage", "vpn.manage", "support.manage", "audit.read"]),
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
    if user is None or not verify_password(body.password, user.password_hash):
        session.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid account credentials")
    principal = Principal(user.subject, user.tenant_id, frozenset(user.roles))
    audit(session, principal, "session.login", "user", user.id)
    session.commit()
    return SessionToken(access_token=encode_token(principal, request.app.state.settings))


ProvisionedPrincipal = CurrentPrincipal


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


def normalized_values(values: list[str], label: str) -> list[str]:
    normalized = sorted({value.strip() for value in values if value.strip()})
    if not normalized:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{label} cannot be empty")
    return normalized


def validate_deployment_profile(
    body: DeploymentProfileCreate, tenant_id: str, session
) -> tuple[VpnNetwork, list[str], list[str], str]:
    """Validate and normalize all references used by a deployment profile."""
    network = session.scalar(
        select(VpnNetwork).where(
            VpnNetwork.id == body.vpn_network_id,
            VpnNetwork.tenant_id == tenant_id,
            VpnNetwork.enabled.is_(True),
        )
    )
    if network is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "VPN network not found")
    file_server_ids = normalized_values(body.file_server_ids, "file servers")
    servers = session.scalars(
        select(FileServer).where(
            FileServer.tenant_id == tenant_id,
            FileServer.id.in_(file_server_ids),
            FileServer.enabled.is_(True),
        )
    ).all()
    if len(servers) != len(file_server_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "file server not found")
    subjects = normalized_values(body.target_subjects, "target subjects")
    users = session.scalars(
        select(WorkspaceUser).where(
            WorkspaceUser.tenant_id == tenant_id,
            WorkspaceUser.subject.in_(subjects),
            WorkspaceUser.status == "active",
        )
    ).all()
    if len(users) != len(subjects):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "active target user not found")
    try:
        allowed_ips = normalize_allowed_ips(body.allowed_ips)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return network, file_server_ids, subjects, allowed_ips


@router.get("/api/v1/file-servers", response_model=list[FileServerRead])
def list_file_servers(principal: ProvisionedPrincipal, session: DatabaseSession):
    principal.require_role("tenant_admin")
    return session.scalars(
        select(FileServer)
        .where(FileServer.tenant_id == principal.tenant_id, FileServer.enabled.is_(True))
        .order_by(FileServer.name)
    ).all()


@router.post("/api/v1/file-servers", response_model=FileServerRead, status_code=status.HTTP_201_CREATED)
def create_file_server(
    body: FileServerCreate, principal: ProvisionedPrincipal, session: DatabaseSession
):
    principal.require_role("tenant_admin")
    host = body.host.strip().lower()
    if any(character in host for character in ("/", "\\", ":")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "host must be a DNS name or IP address")
    server = FileServer(
        tenant_id=principal.tenant_id,
        name=body.name.strip(),
        host=host,
        shares=normalized_values(body.shares, "shares"),
    )
    session.add(server)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "file server name already exists") from exc
    audit(session, principal, "file_server.created", "file_server", server.id)
    session.commit()
    return server


@router.put("/api/v1/file-servers/{server_id}", response_model=FileServerRead)
def update_file_server(
    server_id: str, body: FileServerCreate, principal: ProvisionedPrincipal, session: DatabaseSession
):
    principal.require_role("tenant_admin")
    server = session.scalar(select(FileServer).where(
        FileServer.id == server_id,
        FileServer.tenant_id == principal.tenant_id,
        FileServer.enabled.is_(True),
    ))
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file server not found")
    host = body.host.strip().lower()
    if any(character in host for character in ("/", "\\", ":")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "host must be a DNS name or IP address")
    server.name = body.name.strip()
    server.host = host
    server.shares = normalized_values(body.shares, "shares")
    server.updated_at = now()
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "file server name already exists") from exc
    audit(session, principal, "file_server.updated", "file_server", server.id)
    session.commit()
    return server


@router.delete("/api/v1/file-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file_server(
    server_id: str, principal: ProvisionedPrincipal, session: DatabaseSession
) -> None:
    principal.require_role("tenant_admin")
    server = session.scalar(select(FileServer).where(
        FileServer.id == server_id,
        FileServer.tenant_id == principal.tenant_id,
        FileServer.enabled.is_(True),
    ))
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file server not found")
    server.enabled = False
    server.updated_at = now()
    audit(session, principal, "file_server.disabled", "file_server", server.id)
    session.commit()


@router.get("/api/v1/client-deployments", response_model=list[DeploymentProfileRead])
def list_client_deployments(principal: ProvisionedPrincipal, session: DatabaseSession):
    profiles = session.scalars(
        select(ClientDeploymentProfile)
        .where(
            ClientDeploymentProfile.tenant_id == principal.tenant_id,
            ClientDeploymentProfile.enabled.is_(True),
        )
        .order_by(ClientDeploymentProfile.name)
    ).all()
    if "tenant_admin" in principal.roles:
        return profiles
    return [profile for profile in profiles if principal.subject in profile.target_subjects]


@router.post(
    "/api/v1/client-deployments",
    response_model=DeploymentProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_client_deployment(
    body: DeploymentProfileCreate, principal: ProvisionedPrincipal, session: DatabaseSession
):
    principal.require_role("tenant_admin")
    network, file_server_ids, subjects, allowed_ips = validate_deployment_profile(
        body, principal.tenant_id, session
    )
    profile = ClientDeploymentProfile(
        tenant_id=principal.tenant_id,
        name=body.name.strip(),
        vpn_network_id=network.id,
        allowed_ips=allowed_ips,
        file_server_ids=file_server_ids,
        target_subjects=subjects,
        deliver_vpn_on_login=body.deliver_vpn_on_login,
        deliver_file_servers_on_login=body.deliver_file_servers_on_login,
    )
    session.add(profile)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "deployment profile name already exists") from exc
    audit(
        session,
        principal,
        "client_deployment.created",
        "client_deployment",
        profile.id,
        target_subjects=subjects,
    )
    session.commit()
    return profile


@router.put("/api/v1/client-deployments/{profile_id}", response_model=DeploymentProfileRead)
def update_client_deployment(
    profile_id: str,
    body: DeploymentProfileCreate,
    principal: ProvisionedPrincipal,
    session: DatabaseSession,
):
    principal.require_role("tenant_admin")
    profile = session.scalar(select(ClientDeploymentProfile).where(
        ClientDeploymentProfile.id == profile_id,
        ClientDeploymentProfile.tenant_id == principal.tenant_id,
        ClientDeploymentProfile.enabled.is_(True),
    ))
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "deployment profile not found")
    network, file_server_ids, subjects, allowed_ips = validate_deployment_profile(
        body, principal.tenant_id, session
    )
    profile.name = body.name.strip()
    profile.vpn_network_id = network.id
    profile.allowed_ips = allowed_ips
    profile.file_server_ids = file_server_ids
    profile.target_subjects = subjects
    profile.deliver_vpn_on_login = body.deliver_vpn_on_login
    profile.deliver_file_servers_on_login = body.deliver_file_servers_on_login
    profile.revision += 1
    profile.updated_at = now()
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "deployment profile name already exists") from exc
    audit(session, principal, "client_deployment.updated", "client_deployment", profile.id,
          revision=profile.revision, target_subjects=subjects)
    session.commit()
    return profile


@router.delete("/api/v1/client-deployments/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client_deployment(
    profile_id: str, principal: ProvisionedPrincipal, session: DatabaseSession
):
    principal.require_role("tenant_admin")
    profile = session.scalar(select(ClientDeploymentProfile).where(
        ClientDeploymentProfile.id == profile_id,
        ClientDeploymentProfile.tenant_id == principal.tenant_id,
        ClientDeploymentProfile.enabled.is_(True),
    ))
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "deployment profile not found")
    profile.enabled = False
    profile.revision += 1
    profile.updated_at = now()
    audit(session, principal, "client_deployment.disabled", "client_deployment", profile.id)
    session.commit()


@router.get("/api/v1/client-deployments/{profile_id}/download")
def download_client_deployment(
    profile_id: str,
    request: Request,
    principal: ProvisionedPrincipal,
    session: DatabaseSession,
    subject: str | None = Query(default=None, max_length=128),
):
    profile = session.scalar(
        select(ClientDeploymentProfile).where(
            ClientDeploymentProfile.id == profile_id,
            ClientDeploymentProfile.tenant_id == principal.tenant_id,
            ClientDeploymentProfile.enabled.is_(True),
        )
    )
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "deployment profile not found")
    target = subject.strip() if subject else principal.subject
    if target not in profile.target_subjects:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "deployment is not assigned to this user")
    if target != principal.subject and "tenant_admin" not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot download for another user")

    artifact = Path(request.app.state.settings.windows_client_artifact)
    if not artifact.is_file():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Windows client artifact is not published")
    servers = session.scalars(
        select(FileServer).where(
            FileServer.tenant_id == principal.tenant_id,
            FileServer.id.in_(profile.file_server_ids),
            FileServer.enabled.is_(True),
        )
    ).all()
    raw_code = secrets.token_urlsafe(32)
    enrollment = ClientEnrollmentCode(
        tenant_id=principal.tenant_id,
        profile_id=profile.id,
        subject=target,
        token_hash=hashlib.sha256(raw_code.encode()).hexdigest(),
        expires_at=now() + timedelta(minutes=10),
        created_by=principal.subject,
    )
    session.add(enrollment)
    session.flush()
    manifest = {
        "schema_version": 1,
        "server_url": str(request.base_url).rstrip("/"),
        "tenant_id": principal.tenant_id,
        "profile": {"id": profile.id, "name": profile.name, "revision": profile.revision},
        "target_subject": target,
        "enrollment_code": raw_code,
        "expires_at": enrollment.expires_at.isoformat(),
        "vpn": {"network_id": profile.vpn_network_id, "allowed_ips": profile.allowed_ips},
        "file_servers": [
            {"name": server.name, "host": server.host, "shares": server.shares}
            for server in servers
        ],
    }
    bundle = io.BytesIO()
    client_settings = {
        "serverUrl": manifest["server_url"],
        "workspace": principal.tenant_id,
        "enrollmentCode": raw_code,
    }
    install_script = """$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList $arguments
    exit $LASTEXITCODE
}
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$msi = Join-Path $root 'GOne.Client-x64.msi'
$settings = Join-Path $root 'clientsettings.json'
$process = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @('/i', ('\"' + $msi + '\"'))
if ($process.ExitCode -notin @(0, 1641, 3010)) { throw "G-One MSI installation failed (exit code $($process.ExitCode))." }
$target = Join-Path $env:ProgramData 'G-One'
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Force $settings (Join-Path $target 'clientsettings.json')
Write-Host 'G-One installation and deployment settings are complete.'
"""
    install_command = "@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%~dp0Install-GOne.ps1\"\r\npause\r\n"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(artifact, "GOne.Client-x64.msi")
        archive.writestr("deployment.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("clientsettings.json", json.dumps(client_settings, ensure_ascii=False, indent=2))
        archive.writestr("Install-GOne.ps1", install_script)
        archive.writestr("Install-GOne.cmd", install_command)
    bundle.seek(0)
    audit(
        session,
        principal,
        "client_deployment.downloaded",
        "client_deployment",
        profile.id,
        target_subject=target,
        enrollment_id=enrollment.id,
    )
    session.commit()
    filename = f"GOne-{profile.id[:8]}-r{profile.revision}.zip"
    return StreamingResponse(
        bundle,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


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


@router.delete("/api/v1/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, principal: ProvisionedPrincipal, session: DatabaseSession) -> None:
    principal.require_role("tenant_admin")
    user = session.scalar(select(WorkspaceUser).where(
        WorkspaceUser.id == user_id, WorkspaceUser.tenant_id == principal.tenant_id
    ))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if user.subject == principal.subject:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot delete the signed-in account")
    if "tenant_admin" in user.roles:
        other_admins = session.scalars(select(WorkspaceUser).where(
            WorkspaceUser.tenant_id == principal.tenant_id,
            WorkspaceUser.id != user.id,
            WorkspaceUser.status == "active",
        )).all()
        if not any("tenant_admin" in candidate.roles for candidate in other_admins):
            raise HTTPException(status.HTTP_409_CONFLICT, "cannot delete the last administrator")
    profiles = session.scalars(select(ClientDeploymentProfile).where(
        ClientDeploymentProfile.tenant_id == principal.tenant_id,
        ClientDeploymentProfile.enabled.is_(True),
    )).all()
    for profile in profiles:
        if user.subject in profile.target_subjects:
            profile.target_subjects = [subject for subject in profile.target_subjects if subject != user.subject]
            profile.enabled = bool(profile.target_subjects)
            profile.revision += 1
            profile.updated_at = now()
    audit(session, principal, "user.deleted", "user", user.id, subject=user.subject)
    session.delete(user)
    session.commit()


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

    profile = None
    login_delivery = not body.enrollment_code
    if body.enrollment_code:
        token_hash = hashlib.sha256(body.enrollment_code.encode()).hexdigest()
        enrollment = session.scalar(select(ClientEnrollmentCode).where(
            ClientEnrollmentCode.token_hash == token_hash,
            ClientEnrollmentCode.tenant_id == principal.tenant_id,
            ClientEnrollmentCode.subject == principal.subject,
        ))
        if enrollment is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid client enrollment code")
        # The short expiry protects a code until its first authenticated use. Once
        # activated, the same installed client may use it again after logout or a
        # reboot; the code is still tenant- and subject-bound.
        if enrollment.used_at is None:
            expires_at = enrollment.expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now():
                raise HTTPException(status.HTTP_410_GONE, "client enrollment code expired")
            enrollment.used_at = now()
        profile = session.scalar(select(ClientDeploymentProfile).where(
            ClientDeploymentProfile.id == enrollment.profile_id,
            ClientDeploymentProfile.tenant_id == principal.tenant_id,
            ClientDeploymentProfile.enabled.is_(True),
        ))
        if profile is None or principal.subject not in profile.target_subjects:
            raise HTTPException(status.HTTP_409_CONFLICT, "client deployment is no longer available")
    else:
        # A managed client does not need a download-time enrollment code forever.
        # On every authenticated login, select the most recently managed profile
        # assigned to this user and return its current VPN policy.
        assigned_profiles = session.scalars(
            select(ClientDeploymentProfile).where(
                ClientDeploymentProfile.tenant_id == principal.tenant_id,
                ClientDeploymentProfile.enabled.is_(True),
            ).order_by(
                ClientDeploymentProfile.updated_at.desc(),
                ClientDeploymentProfile.name,
            )
        ).all()
        profile = next(
            (candidate for candidate in assigned_profiles
             if principal.subject in candidate.target_subjects),
            None,
        )

    network = session.scalar(select(VpnNetwork).where(VpnNetwork.tenant_id == principal.tenant_id))
    settings = request.app.state.settings
    vpn_profile = None
    include_vpn = profile is None or not login_delivery or profile.deliver_vpn_on_login
    if network and user.vpn_address and settings.wireguard_private_key and include_vpn:
        address = address_belongs(network.address_cidr, user.vpn_address)
        routes = normalize_allowed_ips(
            profile.allowed_ips if profile else
            (user.allowed_ips or str(ipaddress.ip_interface(network.address_cidr).network))
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
    file_shares = []
    if profile and (not login_delivery or profile.deliver_file_servers_on_login):
        servers = session.scalars(select(FileServer).where(
            FileServer.tenant_id == principal.tenant_id,
            FileServer.id.in_(profile.file_server_ids),
            FileServer.enabled.is_(True),
        )).all()
        file_shares = [
            {"name": f"{server.name} - {share}", "unc_path": f"\\\\{server.host}\\{share}"}
            for server in servers for share in server.shares
        ]
    return ClientBootstrap(
        version=user.policy_version,
        user=UserRead.model_validate(user),
        vpn=network_response(network, request) if network else None,
        vpn_profile=vpn_profile,
        file_shares=file_shares,
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
