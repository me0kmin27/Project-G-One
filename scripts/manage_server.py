#!/usr/bin/env python3
"""Single command entry point for routine G-One server operations."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from configure_server import read_environment
from ensure_compose_env import ensure_environment


def compose(root: Path, *arguments: str, check: bool = True) -> int:
    return subprocess.run(["docker", "compose", *arguments], cwd=root, check=check).returncode


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


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Manage the G-One server")
    parser.add_argument("command", choices=("start", "stop", "restart", "status", "logs", "update"))
    parser.add_argument("--follow", action="store_true", help="follow logs continuously")
    args = parser.parse_args()
    if shutil.which("docker") is None:
        parser.error("Docker is required. Install Docker Engine with the Compose plugin first.")
    if not (root / ".env").exists():
        parser.error("Server is not initialized. Run python3 scripts/setup_server.py first.")
    additions = ensure_environment(root / ".env")
    if additions:
        print(f"Added {len(additions)} setting(s) required by this version.")
    env = read_environment(root / ".env")
    port = env.get("G_ONE_HTTP_PORT", "8000")
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


if __name__ == "__main__":
    main()
