import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from g_one.config import Settings
from g_one.main import create_app


SECRET = "a-test-secret-with-at-least-thirty-two-bytes"


def token(subject: str, tenant: str, roles: list[str] | None = None) -> str:
    def encode(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")

    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode(
        {
            "sub": subject,
            "tenant_id": tenant,
            "roles": roles or ["user"],
            "exp": time.time() + 300,
            "iss": "test-issuer",
            "aud": "test-audience",
        }
    )
    signature = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"{header}.{payload}.{signature}"


@pytest.fixture
def client(tmp_path):
    artifact = tmp_path / "GOne.Client-x64.msi"
    artifact.write_bytes(b"MSI-test-client")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret=SECRET,
        jwt_issuer="test-issuer",
        jwt_audience="test-audience",
        windows_client_artifact=str(artifact),
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def auth(client):
    def provisioned_headers(subject, tenant, roles=None):
        administrator = {"Authorization": f"Bearer {token('__test_admin__', tenant, ['tenant_admin'])}"}
        response = client.get("/api/v1/workspace", headers=administrator)
        if response.status_code == 404:
            response = client.put("/api/v1/workspace", json={"name": tenant}, headers=administrator)
        assert response.status_code == 200
        return {"Authorization": f"Bearer {token(subject, tenant, roles)}"}

    return provisioned_headers
