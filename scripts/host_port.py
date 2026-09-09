"""Prevent deployments from failing late when the published HTTP port is occupied."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time

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


def is_g_one_web_container(docker: list[str], container_id: str, root: Path | None = None) -> bool:
    result = subprocess.run(
        [*docker, "inspect", container_id], check=True, capture_output=True, text=True
    )
    details = json.loads(result.stdout)[0]
    labels = details.get("Config", {}).get("Labels") or {}
    image = details.get("Config", {}).get("Image", "")
    working_directory = labels.get("com.docker.compose.project.working_dir")
    return labels.get("com.docker.compose.service") == "web" and (
        image == "g-one-web"
        or image.endswith("/g-one-web")
        or (root is not None and working_directory == str(root.resolve()))
    )


def listener_inodes(port: int) -> set[str]:
    """Return Linux socket inodes listening on a TCP port."""
    matches: set[str] = set()
    encoded_port = f"{port:04X}"
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not table.exists():
            continue
        for line in table.read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1].rsplit(":", 1)[-1] == encoded_port and fields[3] == "0A":
                matches.add(fields[9])
    return matches


def legacy_g_one_processes(root: Path, port: int) -> list[int]:
    """Find only legacy, non-container G-One uvicorn processes on the port."""
    inodes = listener_inodes(port)
    matches: list[int] = []
    if not inodes:
        return matches
    for process in Path("/proc").glob("[0-9]*"):
        try:
            descriptors = process.joinpath("fd").iterdir()
            owns_listener = any(
                descriptor.is_symlink()
                and os.readlink(descriptor) in {f"socket:[{inode}]" for inode in inodes}
                for descriptor in descriptors
            )
            if not owns_listener:
                continue
            command = process.joinpath("cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            working_directory = process.joinpath("cwd").resolve()
        except (OSError, PermissionError):
            continue
        is_g_one_command = "g_one.main:app" in command and "uvicorn" in command
        is_project_uvicorn = working_directory == root.resolve() and "uvicorn" in command
        if is_g_one_command or is_project_uvicorn:
            matches.append(int(process.name))
    return matches


def stop_legacy_processes(root: Path, bind: str, port: int) -> bool:
    processes = legacy_g_one_processes(root, port)
    if not processes:
        return False
    print(f"Stopping {len(processes)} legacy G-One process(es) holding port {port}: {processes}")
    for process_id in processes:
        os.kill(process_id, 15)
    for _ in range(20):
        if port_is_available(bind, port):
            return True
        time.sleep(0.25)
    return False


def ensure_host_port(
    root: Path, docker: list[str], bind: str, port: int, replace_stale: bool = True
) -> None:
    if port_is_available(bind, port):
        print(f"Host port {bind}:{port} is available.")
        return

    containers = published_containers(docker, port)
    stale = [item for item in containers if is_g_one_web_container(docker, item, root)]
    if replace_stale and stale and len(stale) == len(containers):
        print(f"Removing {len(stale)} stale G-One web container(s) holding port {port}.")
        subprocess.run([*docker, "rm", "--force", *stale], check=True)
        if port_is_available(bind, port):
            return

    if not containers and stop_legacy_processes(root, bind, port):
        return

    owners = ", ".join(containers) if containers else "a host process"
    raise RuntimeError(
        f"Host port {bind}:{port} is already used by {owners}. "
        "Stop that service or choose another port with: "
        f"python3 scripts/configure_server.py set http-port {port + 1}"
    )
