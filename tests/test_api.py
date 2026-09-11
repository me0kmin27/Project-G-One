def test_health_and_authentication(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    assert client.get("/api/v1/devices").status_code == 401


def test_admin_console_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "G-One · Control Plane" in response.text
    assert client.get("/assets/styles.css").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


def test_first_run_creates_only_the_administrator_then_requires_a_workspace(client):
    assert client.get("/api/v1/setup/status").json() == {"administrator_required": True}

    assert client.post(
        "/api/v1/session/login",
        json={"subject": "owner", "tenant_id": "acme", "password": "correct-horse"},
    ).status_code == 401

    response = client.post(
        "/api/v1/setup/administrator",
        json={"subject": "owner", "tenant_id": "acme", "password": "correct-horse", "display_name": "Owner"},
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/api/v1/me", headers=headers).json()["roles"] == ["tenant_admin"]
    assert client.get("/api/v1/setup/status").json() == {"administrator_required": False}
    assert client.get("/api/v1/workspace", headers=headers).status_code == 404
    assert client.post(
        "/api/v1/users",
        json={"subject": "alice", "display_name": "Alice", "password": "correct-horse"},
        headers=headers,
    ).status_code == 409
    assert client.post(
        "/api/v1/devices", json={"name": "Too Early"}, headers=headers
    ).status_code == 409

    workspace = client.put(
        "/api/v1/workspace", json={"name": "ACME Operations"}, headers=headers
    )
    assert workspace.status_code == 200
    assert workspace.json()["id"] == "acme"


def test_later_login_cannot_claim_an_administrator_account(client):
    client.post(
        "/api/v1/setup/administrator",
        json={"subject": "owner", "tenant_id": "acme", "password": "correct-horse", "display_name": "Owner"},
    )
    response = client.post(
        "/api/v1/setup/administrator",
        json={"subject": "attacker", "tenant_id": "other", "password": "another-password", "display_name": "Attacker"},
    )
    assert response.status_code == 409


def test_console_password_only_impersonates_a_provisioned_administrator(client):
    login = client.post(
        "/api/v1/setup/administrator",
        json={"subject": "owner", "tenant_id": "acme", "password": "correct-horse", "display_name": "Owner"},
    )
    assert login.status_code == 201
    response = client.post(
        "/api/v1/session/console",
        json={
            "subject": "owner",
            "tenant_id": "acme",
            "password": "development-console-password",
        },
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/api/v1/me", headers=headers).json() == {
        "subject": "owner",
        "tenant_id": "acme",
        "roles": ["tenant_admin"],
    }


def test_console_rejects_unprovisioned_identity(client):
    response = client.post(
        "/api/v1/session/console",
        json={"subject": "admin", "tenant_id": "demo", "password": "development-console-password"},
    )
    assert response.status_code == 401

def test_admin_manages_workspace_users_roles_and_tokens(client, auth):
    admin = auth("admin", "acme", ["tenant_admin"])
    workspace = client.put("/api/v1/workspace", json={"name": "ACME Operations"}, headers=admin)
    assert workspace.status_code == 200
    assert workspace.json()["id"] == "acme"
    assert client.get("/api/v1/workspace", headers=admin).json()["name"] == "ACME Operations"
    client.put(
        "/api/v1/vpn/network",
        json={"name": "ACME VPN", "address_cidr": "10.77.0.1/24", "endpoint": "vpn.acme.test"},
        headers=admin,
    )

    roles = client.get("/api/v1/roles", headers=admin).json()
    assert {role["id"] for role in roles} == {"tenant_admin", "support", "auditor", "member"}
    user = client.post(
        "/api/v1/users",
        json={"subject": "alice", "display_name": "Alice", "email": "alice@example.com", "password": "correct-horse", "roles": ["support"], "vpn_address": "10.77.0.10/32", "allowed_ips": "10.77.0.0/24, 192.168.10.12/24"},
        headers=admin,
    )
    assert user.status_code == 201
    updated = client.put(
        f"/api/v1/users/{user.json()['id']}",
        json={"display_name": "Alice Kim", "email": "alice@example.com", "roles": ["auditor", "support"], "status": "active", "vpn_address": "10.77.0.10/32", "allowed_ips": "10.77.0.0/24"},
        headers=admin,
    )
    assert updated.json()["roles"] == ["auditor", "support"]
    login = client.post("/api/v1/session/login", json={"subject": "alice", "tenant_id": "acme", "password": "correct-horse"})
    assert login.status_code == 200
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.app.state.settings.wireguard_private_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    assert client.post("/api/v1/client/bootstrap", json={"device_name": "ALICE-PC"}).status_code == 401
    bootstrap = client.post(
        "/api/v1/client/bootstrap", json={"device_name": "ALICE-PC"}, headers=user_headers
    )
    assert bootstrap.status_code == 200
    assert bootstrap.json()["user"]["subject"] == "alice"
    assert bootstrap.json()["vpn"]["endpoint"] == "vpn.acme.test"
    assert bootstrap.json()["device"]["name"] == "ALICE-PC"
    assert bootstrap.json()["file_shares"] == []
    assert "PrivateKey = " in bootstrap.json()["vpn_profile"]
    assert "Endpoint = vpn.acme.test:51820" in bootstrap.json()["vpn_profile"]

    client.app.state.settings.wireguard_private_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    enrollment = client.post(
        "/api/v1/client/vpn/enroll", json={"device_name": "ALICE-PC"}, headers=user_headers
    )
    assert enrollment.status_code == 200
    assert enrollment.json()["name"] == "client:alice:ALICE-PC"
    assert enrollment.json()["address"] == "10.77.0.10/32"
    assert "PrivateKey = " in enrollment.json()["client_config"]
    assert "Endpoint = vpn.acme.test:51820" in enrollment.json()["client_config"]

    rotated = client.post(
        "/api/v1/client/vpn/enroll", json={"device_name": "ALICE-PC"}, headers=user_headers
    )
    assert rotated.status_code == 200
    assert rotated.json()["id"] == enrollment.json()["id"]
    assert rotated.json()["public_key"] != enrollment.json()["public_key"]

    issued = client.post(
        "/api/v1/tokens",
        json={"name": "automation", "scopes": ["devices:read", "audit:read"], "lifetime_days": 30},
        headers=admin,
    )
    assert issued.status_code == 201
    assert issued.json()["token"].startswith("gone_")
    token_id = issued.json()["id"]
    listed = client.get("/api/v1/tokens", headers=admin).json()
    assert "token" not in listed[0]
    assert listed[0]["prefix"] == issued.json()["prefix"]
    assert client.delete(f"/api/v1/tokens/{token_id}", headers=admin).status_code == 204
    assert client.get("/api/v1/tokens", headers=admin).json()[0]["revoked_at"] is not None


def test_management_is_admin_only_and_tenant_scoped(client, auth):
    assert client.get("/api/v1/users", headers=auth("member", "a", ["member"])).status_code == 403
    a = auth("admin-a", "a", ["tenant_admin"])
    b = auth("admin-b", "b", ["tenant_admin"])
    client.post("/api/v1/users", json={"subject": "alice", "display_name": "Alice", "password": "correct-horse", "roles": ["member"]}, headers=a)
    assert len(client.get("/api/v1/users", headers=a).json()) == 1
    assert client.get("/api/v1/users", headers=b).json() == []


def test_devices_are_tenant_and_owner_scoped(client, auth):
    created = client.post(
        "/api/v1/devices", json={"name": "Office PC"}, headers=auth("alice", "tenant-a")
    )
    assert created.status_code == 201
    assert created.json()["owner_id"] == "alice"
    assert client.get("/api/v1/devices", headers=auth("bob", "tenant-a")).json() == []
    assert client.get(
        "/api/v1/devices", headers=auth("admin", "tenant-a", ["tenant_admin"])
    ).json()[0]["name"] == "Office PC"
    assert client.get(
        "/api/v1/devices", headers=auth("admin", "tenant-b", ["tenant_admin"])
    ).json() == []


def test_support_consent_lifecycle_and_audit(client, auth):
    device = client.post(
        "/api/v1/devices", json={"name": "Alice PC"}, headers=auth("alice", "tenant-a")
    ).json()
    requested = client.post(
        "/api/v1/support-requests",
        json={
            "target_device_id": device["id"],
            "purpose": "Resolve VPN connection issue",
            "permissions": ["screen_view", "input_control"],
        },
        headers=auth("helper", "tenant-a", ["support"]),
    )
    assert requested.status_code == 201
    request_id = requested.json()["id"]
    forbidden = client.post(
        f"/api/v1/support-requests/{request_id}/decision",
        json={"accept": True},
        headers=auth("mallory", "tenant-a"),
    )
    assert forbidden.status_code == 403
    accepted = client.post(
        f"/api/v1/support-requests/{request_id}/decision",
        json={"accept": True},
        headers=auth("alice", "tenant-a"),
    )
    assert accepted.json()["state"] == "accepted"
    ended = client.post(
        f"/api/v1/support-requests/{request_id}/end",
        headers=auth("helper", "tenant-a", ["support"]),
    )
    assert ended.json()["state"] == "ended"
    events = client.get(
        "/api/v1/audit-events", headers=auth("auditor", "tenant-a", ["auditor"])
    ).json()
    assert [event["action"] for event in events][:3] == [
        "support.ended",
        "support.accepted",
        "support.requested",
    ]


def test_support_request_cannot_cross_tenant(client, auth):
    device = client.post(
        "/api/v1/devices", json={"name": "Private PC"}, headers=auth("alice", "tenant-a")
    ).json()
    response = client.post(
        "/api/v1/support-requests",
        json={
            "target_device_id": device["id"],
            "purpose": "Attempt cross tenant access",
            "permissions": ["screen_view"],
        },
        headers=auth("helper", "tenant-b", ["support"]),
    )
    assert response.status_code == 404


def test_support_request_list_is_tenant_and_owner_scoped(client, auth):
    device = client.post(
        "/api/v1/devices", json={"name": "Alice PC"}, headers=auth("alice", "tenant-a")
    ).json()
    client.post(
        "/api/v1/support-requests",
        json={
            "target_device_id": device["id"],
            "purpose": "Check network settings",
            "permissions": ["screen_view"],
        },
        headers=auth("helper", "tenant-a", ["support"]),
    )

    assert len(client.get("/api/v1/support-requests", headers=auth("alice", "tenant-a")).json()) == 1
    assert client.get("/api/v1/support-requests", headers=auth("bob", "tenant-a")).json() == []
    assert client.get(
        "/api/v1/support-requests", headers=auth("admin", "tenant-b", ["tenant_admin"])
    ).json() == []


def test_admin_can_configure_vpn_and_manage_peer(client, auth):
    admin = auth("admin", "tenant-a", ["tenant_admin"])
    configured = client.put(
        "/api/v1/vpn/network",
        json={
            "name": "Office VPN",
            "address_cidr": "10.44.0.1/24",
            "endpoint": "vpn.example.com",
            "listen_port": 51820,
            "dns": "10.44.0.1",
        },
        headers=admin,
    )
    assert configured.status_code == 200
    assert configured.json()["runtime_enabled"] is False

    created = client.post(
        "/api/v1/vpn/peers",
        json={"name": "Alice laptop", "address": "10.44.0.2/32"},
        headers=admin,
    )
    assert created.status_code == 201
    assert created.json()["enabled"] is True
    assert created.json()["allowed_ips"] == "10.44.0.0/24"
    assert created.json()["client_config"] is None
    peer_id = created.json()["id"]
    assert len(client.get("/api/v1/vpn/peers", headers=admin).json()) == 1

    routes = client.put(
        f"/api/v1/vpn/peers/{peer_id}/routes",
        json={"allowed_ips": "10.44.0.0/24, 192.168.20.12/24"},
        headers=admin,
    )
    assert routes.status_code == 200
    assert routes.json()["allowed_ips"] == "10.44.0.0/24, 192.168.20.0/24"

    assert client.delete(f"/api/v1/vpn/peers/{peer_id}", headers=admin).status_code == 204
    assert client.get("/api/v1/vpn/peers", headers=admin).json()[0]["enabled"] is False


def test_vpn_is_tenant_scoped_and_admin_only(client, auth):
    body = {"name": "Private", "address_cidr": "10.8.0.1/24", "endpoint": "vpn.test"}
    assert client.put("/api/v1/vpn/network", json=body, headers=auth("user", "a")).status_code == 403
    assert client.get("/api/v1/vpn/network", headers=auth("admin", "b", ["tenant_admin"])).status_code == 404


def test_vpn_rejects_server_and_duplicate_peer_addresses(client, auth):
    admin = auth("admin", "tenant-a", ["tenant_admin"])
    client.put(
        "/api/v1/vpn/network",
        json={"name": "Private", "address_cidr": "10.8.0.1/24", "endpoint": "vpn.test"},
        headers=admin,
    )
    invalid = client.post(
        "/api/v1/vpn/peers", json={"name": "server", "address": "10.8.0.1/32"}, headers=admin
    )
    assert invalid.status_code == 422
    first = client.post(
        "/api/v1/vpn/peers", json={"name": "one", "address": "10.8.0.2/32"}, headers=admin
    )
    assert first.status_code == 201
    duplicate = client.post(
        "/api/v1/vpn/peers", json={"name": "two", "address": "10.8.0.2/32"}, headers=admin
    )
    assert duplicate.status_code == 409
