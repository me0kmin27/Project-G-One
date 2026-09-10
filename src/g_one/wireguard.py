"""Validation and rendering for the WireGuard data plane."""

import base64
import ipaddress
from pathlib import Path
import secrets
import subprocess

from .config import Settings


def validate_key(value: str) -> str:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("WireGuard key must be valid base64") from exc
    if len(raw) != 32:
        raise ValueError("WireGuard key must contain 32 bytes")
    return value


def public_key(private_key: str) -> str:
    scalar = bytearray(base64.b64decode(validate_key(private_key)))
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    # RFC 7748 Montgomery ladder with the Curve25519 base point (u = 9).
    p, x_1 = 2**255 - 19, 9
    x_2, z_2, x_3, z_3, swap = 1, 0, x_1, 1, 0
    value = int.from_bytes(scalar, "little")
    for position in range(254, -1, -1):
        bit = (value >> position) & 1
        swap ^= bit
        if swap:
            x_2, x_3, z_2, z_3 = x_3, x_2, z_3, z_2
        swap = bit
        a, aa = (x_2 + z_2) % p, (x_2 + z_2) ** 2 % p
        b, bb = (x_2 - z_2) % p, (x_2 - z_2) ** 2 % p
        e, c, d = (aa - bb) % p, (x_3 + z_3) % p, (x_3 - z_3) % p
        da, cb = d * a % p, c * b % p
        x_3, z_3 = (da + cb) ** 2 % p, x_1 * (da - cb) ** 2 % p
        x_2, z_2 = aa * bb % p, e * (aa + 121665 * e) % p
    if swap:
        x_2, x_3, z_2, z_3 = x_3, x_2, z_3, z_2
    result = x_2 * pow(z_2, p - 2, p) % p
    return base64.b64encode(result.to_bytes(32, "little")).decode()


def generate_keypair() -> tuple[str, str]:
    private = base64.b64encode(secrets.token_bytes(32)).decode()
    return private, public_key(private)


def render_server_config(network, peers, private_key: str) -> str:
    validate_key(private_key)
    lines = ["[Interface]", f"PrivateKey = {private_key}", f"Address = {network.address_cidr}", f"ListenPort = {network.listen_port}"]
    for peer in peers:
        if peer.enabled:
            lines += ["", "[Peer]", f"# {peer.name}", f"PublicKey = {peer.public_key}", f"AllowedIPs = {peer.address}"]
            if peer.persistent_keepalive:
                lines.append(f"PersistentKeepalive = {peer.persistent_keepalive}")
    return "\n".join(lines) + "\n"


def render_client_config(network, private_key: str, address: str, server_public_key: str) -> str:
    vpn_routes = str(ipaddress.ip_interface(network.address_cidr).network)
    lines = ["[Interface]", f"PrivateKey = {private_key}", f"Address = {address}"]
    if network.dns:
        lines.append(f"DNS = {network.dns}")
    lines += ["", "[Peer]", f"PublicKey = {server_public_key}", f"Endpoint = {network.endpoint}:{network.listen_port}", f"AllowedIPs = {vpn_routes}", "PersistentKeepalive = 25"]
    return "\n".join(lines) + "\n"


def address_belongs(network_cidr: str, address: str) -> str:
    network = ipaddress.ip_interface(network_cidr).network
    interface = ipaddress.ip_interface(address)
    if interface.ip not in network or interface.ip == ipaddress.ip_interface(network_cidr).ip:
        raise ValueError("peer address must be an unused host in the VPN network")
    return str(interface)


def apply_config(config: str, settings: Settings) -> None:
    if not settings.wireguard_apply:
        return
    path = Path(settings.wireguard_config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config, encoding="utf-8")
    path.chmod(0o600)
    subprocess.run(["wg-quick", "down", settings.wireguard_interface], check=False, capture_output=True)
    subprocess.run(["wg-quick", "up", str(path)], check=True, capture_output=True, text=True)
