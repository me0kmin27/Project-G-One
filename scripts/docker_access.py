"""Resolve Docker access without requiring the caller to guess about sudo."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def docker_prefix() -> list[str]:
    """Return a working Docker command prefix, elevating only Docker if needed."""
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is not installed or is not available in PATH.")
    probe = subprocess.run(
        ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
    if probe.returncode == 0:
        return ["docker"]
    if os.name != "nt" and shutil.which("sudo"):
        print("Docker socket access requires elevated permission; using sudo for Docker commands.")
        sudo_probe = subprocess.run(
            ["sudo", "docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if sudo_probe.returncode == 0:
            return ["sudo", "docker"]
    raise RuntimeError(
        "Docker permission denied. Run this once, sign out and back in, then retry:\n"
        "  sudo usermod -aG docker \"$USER\""
    )


def ensure_project_writable(root: Path) -> None:
    """Fail before setup with an actionable repair for root-owned checkouts/files."""
    env_file = root / ".env"
    target = env_file if env_file.exists() else root
    if os.access(target, os.W_OK):
        return
    command = f'sudo chown -R "$USER":"$(id -gn)" {root}'
    raise RuntimeError(f"Project files are not writable by the current user. Repair ownership with:\n  {command}")


def fail(message: str) -> None:
    print(f"Permission setup failed: {message}", file=sys.stderr)
    raise SystemExit(2)
