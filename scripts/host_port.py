"""Prevent deployments from failing late when the published HTTP port is occupied."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess

def port_is_available(bind: str, port: int) -> bool:
    address = "127.0.0.1" if bind == "0.0.0.0" else bind
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((address, port)) != 0


def published_containers(docker: list[str], port: int) -> list[str]:
    result = subprocess.run(
        [*docker, "ps", "--quiet", "--filter", f"publish={port}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.split()


def is_g_one_web_container(docker: list[str], container_id: str) -> bool:
    result = subprocess.run(
        [*docker, "inspect", container_id], check=True, capture_output=True, text=True
    )
    details = json.loads(result.stdout)[0]
    labels = details.get("Config", {}).get("Labels") or {}
    image = details.get("Config", {}).get("Image", "")
    return labels.get("com.docker.compose.service") == "web" and (
        image == "g-one-web" or image.endswith("/g-one-web")
    )


def ensure_host_port(
    root: Path, docker: list[str], bind: str, port: int, replace_stale: bool = True
) -> None:
    if port_is_available(bind, port):
        print(f"Host port {bind}:{port} is available.")
        return

    containers = published_containers(docker, port)
    stale = [item for item in containers if is_g_one_web_container(docker, item)]
    if replace_stale and stale and len(stale) == len(containers):
        print(f"Removing {len(stale)} stale G-One web container(s) holding port {port}.")
        subprocess.run([*docker, "rm", "--force", *stale], check=True)
        if port_is_available(bind, port):
            return

    owners = ", ".join(containers) if containers else "a host process"
    raise RuntimeError(
        f"Host port {bind}:{port} is already used by {owners}. "
        "Stop that service or choose another port with: "
        f"python3 scripts/configure_server.py set http-port {port + 1}"
    )
