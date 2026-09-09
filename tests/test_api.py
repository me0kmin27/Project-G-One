def test_health_and_authentication(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    assert client.get("/api/v1/devices").status_code == 401


def test_admin_console_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "G-One · Overview" in response.text
    assert client.get("/assets/styles.css").status_code == 200


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
