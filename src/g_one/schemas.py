from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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

