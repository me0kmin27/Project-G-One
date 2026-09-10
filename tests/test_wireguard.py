import base64
from types import SimpleNamespace

import pytest

from g_one.wireguard import (
    generate_keypair,
    normalize_allowed_ips,
    render_client_config,
    render_server_config,
)


def test_generates_wireguard_keypair_and_split_tunnel_config():
    private_key, public_key = generate_keypair()
    assert len(base64.b64decode(private_key)) == 32
    assert len(base64.b64decode(public_key)) == 32

    network = SimpleNamespace(
        address_cidr="10.44.0.1/24",
        endpoint="vpn.example.com",
        listen_port=51820,
        dns="10.44.0.1",
    )
    config = render_client_config(network, private_key, "10.44.0.2/32", public_key)
    assert "Address = 10.44.0.2/32" in config
    assert "Endpoint = vpn.example.com:51820" in config
    assert "AllowedIPs = 10.44.0.0/24" in config


def test_server_config_excludes_revoked_peers():
    private_key, active_public_key = generate_keypair()
    _, revoked_public_key = generate_keypair()
    network = SimpleNamespace(address_cidr="10.44.0.1/24", listen_port=51820)
    peers = [
        SimpleNamespace(
            enabled=True,
            name="active",
            public_key=active_public_key,
            address="10.44.0.2/32",
            persistent_keepalive=25,
        ),
        SimpleNamespace(
            enabled=False,
            name="revoked",
            public_key=revoked_public_key,
            address="10.44.0.3/32",
            persistent_keepalive=25,
        ),
    ]
    config = render_server_config(network, peers, private_key)
    assert active_public_key in config
    assert revoked_public_key not in config


def test_normalizes_client_routes_and_rejects_invalid_values():
    assert normalize_allowed_ips("10.44.0.7/24, 192.168.10.0/24") == (
        "10.44.0.0/24, 192.168.10.0/24"
    )

    with pytest.raises(ValueError, match="valid IPv4 or IPv6 CIDR"):
        normalize_allowed_ips("not-a-network")
