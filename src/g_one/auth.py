from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: str
    roles: frozenset[str]

    def require_role(self, *allowed: str) -> None:
        if self.roles.isdisjoint(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")


bearer = HTTPBearer(auto_error=False)


def _decode_part(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValueError("invalid base64") from exc


def decode_token(token: str, settings: Settings) -> Principal:
    try:
        header_text, payload_text, signature_text = token.split(".")
        header = json.loads(_decode_part(header_text))
        payload = json.loads(_decode_part(payload_text))
        signature = _decode_part(signature_text)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid access token") from exc

    if header != {"alg": "HS256", "typ": "JWT"}:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unsupported access token")
    expected = hmac.new(
        settings.jwt_secret.encode(), f"{header_text}.{payload_text}".encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid access token")
    required = {"sub", "tenant_id", "roles", "exp", "iss", "aud"}
    if not required.issubset(payload):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "incomplete access token")
    if payload["iss"] != settings.jwt_issuer or payload["aud"] != settings.jwt_audience:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token scope")
    if not isinstance(payload["exp"], (int, float)) or payload["exp"] <= time.time():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "expired access token")
    if not all(isinstance(payload[key], str) and payload[key] for key in ("sub", "tenant_id")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token subject")
    if not isinstance(payload["roles"], list) or not all(isinstance(x, str) for x in payload["roles"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token roles")
    return Principal(payload["sub"], payload["tenant_id"], frozenset(payload["roles"]))


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bearer token required")
    return decode_token(credentials.credentials, request.app.state.settings)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

