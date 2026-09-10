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


class SessionToken(ApiModel):
    access_token: str
    token_type: str = "bearer"


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
    created_at: datetime
    updated_at: datetime


class VpnPeerCreate(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    address: str = Field(max_length=64)
    public_key: str | None = Field(default=None, max_length=44)
    persistent_keepalive: int = Field(default=25, ge=0, le=65535)


class VpnPeerRead(ApiModel):
    id: str
    network_id: str
    name: str
    public_key: str
    address: str
    persistent_keepalive: int
    enabled: bool
    created_at: datetime
    revoked_at: datetime | None


class VpnPeerEnrollment(VpnPeerRead):
    client_config: str | None = None
