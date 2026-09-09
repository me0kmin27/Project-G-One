#!/usr/bin/env python3
"""Perform a repeatable first-time setup for a G-One Docker server."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from ensure_compose_env import ensure_environment


def run(command: list[str], root: Path) -> None:
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=root, check=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Initialize a G-One server")
    parser.add_argument("--no-start", action="store_true", help="prepare without starting containers")
    parser.add_argument("--skip-pull", action="store_true", help="do not pull container images")
    args = parser.parse_args()
    if shutil.which("docker") is None:
        parser.error("Docker is required. Install Docker Engine with the Compose plugin first.")
    additions = ensure_environment(root / ".env")
    print(f"Configuration ready ({len(additions)} setting(s) added).")
    run(["docker", "compose", "config", "--quiet"], root)
    if not args.skip_pull:
        run(["docker", "compose", "pull", "database"], root)
    run(["docker", "compose", "build", "web"], root)
    if not args.no_start:
        run([sys.executable, "scripts/manage_server.py", "start"], root)
        run([sys.executable, "scripts/manage_server.py", "doctor"], root)
        print("\nSetup complete. Open the HTTPS address configured in your reverse proxy.")
    else:
        print("Setup complete. Start later with: python3 scripts/manage_server.py start")


if __name__ == "__main__":
    main()
