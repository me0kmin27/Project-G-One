#!/usr/bin/env python3
"""Single command entry point for routine G-One server operations."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from configure_server import read_environment
from docker_access import docker_prefix, ensure_project_writable, fail
from ensure_compose_env import ensure_environment

DOCKER = ["docker"]

def compose(root: Path, *arguments: str, check: bool = True) -> int:
    return subprocess.run([*DOCKER, "compose", *arguments], cwd=root, check=check).returncode


def wait_until_ready(port: str, timeout: int = 90) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/readyz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    print(f"G-One is ready: http://127.0.0.1:{port}/")
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(2)
    print("Server did not become ready in time. Run the 'logs' command for details.", file=sys.stderr)
    return False


def check_http_endpoint(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            healthy = response.status == 200
    except (OSError, urllib.error.URLError) as error:
        print(f"[FAIL] {url} ({error})")
        return False
    print(f"[ OK ] {url}")
    return healthy


def doctor(root: Path, bind: str, port: str) -> bool:
    """Check every local hop that commonly causes a reverse-proxy 502."""
    print("\n1/3 Checking containers")
    if compose(root, "ps", check=False) != 0:
        print("[FAIL] Docker Compose status could not be read.")
        return False

    print("\n2/3 Checking the published HTTP endpoints")
    endpoints = ("healthz", "readyz", "assets/app.js")
    healthy = all(check_http_endpoint(f"http://127.0.0.1:{port}/{path}") for path in endpoints)
    if not healthy:
        print("\nG-One is not ready. Inspect it with:")
        print("  python3 scripts/manage_server.py logs")
        return False

    print("\n3/3 Reverse-proxy upstream")
    if bind == "127.0.0.1":
        print(f"Use http://127.0.0.1:{port} only when the proxy runs on this server.")
        print("For a proxy on another server, run:")
        print("  python3 scripts/configure_server.py set http-bind 0.0.0.0 && python3 scripts/manage_server.py restart")
    else:
        print(f"Set the proxy upstream to http://<G_ONE_SERVER_IP>:{port}")
        print(f"Allow TCP {port} in the G-One server firewall only from the proxy server IP.")
    print("\nAll local checks passed. A remaining 502 is in the proxy target, firewall, or DNS/TLS configuration.")
    return True


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Manage the G-One server")
    parser.add_argument("command", choices=("start", "stop", "restart", "status", "logs", "update", "doctor"))
    parser.add_argument("--follow", action="store_true", help="follow logs continuously")
    args = parser.parse_args()
    if not (root / ".env").exists():
        parser.error("Server is not initialized. Run python3 scripts/setup_server.py first.")
    try:
        ensure_project_writable(root)
        global DOCKER
        DOCKER = docker_prefix()
    except RuntimeError as error:
        fail(str(error))
    additions = ensure_environment(root / ".env")
    if additions:
        print(f"Added {len(additions)} setting(s) required by this version.")
    env = read_environment(root / ".env")
    port = env.get("G_ONE_HTTP_PORT", "8000")
    bind = env.get("G_ONE_HTTP_BIND", "0.0.0.0")
    if args.command == "start":
        compose(root, "up", "-d", "--build", "--remove-orphans")
        raise SystemExit(0 if wait_until_ready(port) else 1)
    if args.command == "stop":
        compose(root, "down")
    elif args.command == "restart":
        compose(root, "restart")
        raise SystemExit(0 if wait_until_ready(port) else 1)
    elif args.command == "status":
        compose(root, "ps")
    elif args.command == "logs":
        arguments = ["logs", "--tail", "200"]
        if args.follow:
            arguments.append("--follow")
        compose(root, *arguments)
    elif args.command == "update":
        compose(root, "pull")
        compose(root, "up", "-d", "--build", "--remove-orphans")
        raise SystemExit(0 if wait_until_ready(port) else 1)
    elif args.command == "doctor":
        raise SystemExit(0 if doctor(root, bind, port) else 1)


if __name__ == "__main__":
    main()
