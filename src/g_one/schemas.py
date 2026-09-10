from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PrincipalRead(ApiModel):
    subject: str
    tenant_id: str
    roles: list[str]


class ConsoleSessionCreate(ApiModel):
    subject: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)

    @field_validator("subject", "tenant_id")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("identifier cannot be blank")
        return normalized


class UserSessionCreate(ApiModel):
    subject: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=512)

    @field_validator("subject", "tenant_id")
    @classmethod
    def normalize_login_identifier(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("identifier cannot be blank")
        return normalized


class AdministratorSetup(UserSessionCreate):
    display_name: str = Field(min_length=1, max_length=128)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("display name cannot be blank")
        return normalized


class SessionToken(ApiModel):
    access_token: str
    token_type: str = "bearer"


class SetupStatus(ApiModel):
    administrator_required: bool


class WorkspaceUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=128)


class WorkspaceRead(ApiModel):
    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class UserCreate(ApiModel):
    subject: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=512)
    roles: set[str] = Field(default_factory=set)
    vpn_address: str | None = Field(default=None, max_length=64)
    allowed_ips: str = Field(default="", max_length=1024)


class UserUpdate(ApiModel):
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    roles: set[str] = Field(default_factory=set)
    status: str = Field(pattern="^(active|suspended)$")
    password: str | None = Field(default=None, min_length=8, max_length=512)
    vpn_address: str | None = Field(default=None, max_length=64)
    allowed_ips: str = Field(default="", max_length=1024)


class UserRead(ApiModel):
    id: str
    subject: str
    display_name: str
    email: str | None
    roles: list[str]
    vpn_address: str | None
    allowed_ips: str
    policy_version: int
    status: str
    created_at: datetime
    updated_at: datetime


class RoleRead(ApiModel):
    id: str
    name: str
    permissions: list[str]


class ApiTokenCreate(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: set[str] = Field(min_length=1)
    lifetime_days: int = Field(default=30, ge=1, le=365)


class ApiTokenRead(ApiModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_by: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None


class ApiTokenIssued(ApiTokenRead):
    token: str


class DeviceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("name cannot be blank")
        return normalized


class DeviceRead(ApiModel):
    id: str
    owner_id: str
    name: str
    platform: str
    status: str
    created_at: datetime
    revoked_at: datetime | None


class SupportPermission(str, Enum):
    screen_view = "screen_view"
    input_control = "input_control"
    clipboard = "clipboard"
    file_transfer = "file_transfer"


class SupportRequestCreate(ApiModel):
    target_device_id: str
    purpose: str = Field(min_length=3, max_length=500)
    permissions: set[SupportPermission] = Field(min_length=1)
    lifetime_seconds: int = Field(default=300, ge=60, le=900)

    @field_validator("purpose")
    @classmethod
    def normalize_purpose(cls, value: str) -> str:
        if len(normalized := value.strip()) < 3:
            raise ValueError("purpose is too short")
        return normalized


class SupportDecision(ApiModel):
    accept: bool


class SupportRequestRead(ApiModel):
    id: str
    requester_id: str
    target_device_id: str
    purpose: str
    permissions: list[str]
    state: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    ended_at: datetime | None


class AuditEventRead(ApiModel):
    id: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    outcome: str
    details: dict
    occurred_at: datetime


class VpnNetworkCreate(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    address_cidr: str = Field(default="10.44.0.1/24", max_length=64)
    endpoint: str = Field(min_length=1, max_length=255)
    listen_port: int = Field(default=51820, ge=1, le=65535)
    dns: str | None = Field(default=None, max_length=255)


class VpnNetworkRead(ApiModel):
    id: str
    name: str
    address_cidr: str
    endpoint: str
    listen_port: int
    dns: str | None
    enabled: bool
    server_public_key: str | None = None
    runtime_enabled: bool = False
    network_route: str = ""
    created_at: datetime
    updated_at: datetime


class VpnPeerCreate(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    address: str = Field(max_length=64)
    public_key: str | None = Field(default=None, max_length=44)
    allowed_ips: str | None = Field(default=None, max_length=1024)
    persistent_keepalive: int = Field(default=25, ge=0, le=65535)


class VpnPeerRoutesUpdate(ApiModel):
    allowed_ips: str = Field(min_length=1, max_length=1024)


class VpnPeerRead(ApiModel):
    id: str
    network_id: str
    name: str
    public_key: str
    address: str
    allowed_ips: str
    persistent_keepalive: int
    enabled: bool
    created_at: datetime
    revoked_at: datetime | None


class VpnPeerEnrollment(VpnPeerRead):
    client_config: str | None = None


class ClientVpnEnrollment(ApiModel):
    device_name: str = Field(min_length=1, max_length=128)


class ClientPolicy(ApiModel):
    version: int
    poll_interval_seconds: int = 15
    user: UserRead
    vpn: VpnNetworkRead | None
    devices: list[DeviceRead]
