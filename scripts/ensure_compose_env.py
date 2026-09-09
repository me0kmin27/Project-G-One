#!/usr/bin/env python3
"""Create missing Docker Compose settings without replacing operator values."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import tempfile


DEFAULTS = {
    "G_ONE_JWT_ISSUER": "g-one",
    "G_ONE_JWT_AUDIENCE": "g-one-api",
    "G_ONE_BIND_ADDRESS": "0.0.0.0",
    "G_ONE_HTTP_PORT": "8000",
    "G_ONE_DB_NAME": "g_one",
    "G_ONE_DB_USER": "g_one",
}


def assigned_keys(contents: str) -> set[str]:
    keys: set[str] = set()
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() and value.strip():
            keys.add(key.strip())
    return keys


def ensure_environment(path: Path) -> list[str]:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    keys = assigned_keys(existing)
    values = {
        "G_ONE_JWT_SECRET": secrets.token_urlsafe(48),
        "G_ONE_DB_PASSWORD": secrets.token_urlsafe(32),
        "G_ONE_DB_ROOT_PASSWORD": secrets.token_urlsafe(48),
        **DEFAULTS,
    }
    additions = [f"{key}={value}" for key, value in values.items() if key not in keys]
    if not additions:
        os.chmod(path, 0o600)
        return []

    separator = "" if not existing or existing.endswith("\n") else "\n"
    updated = existing + separator + "\n".join(additions) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(updated)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return additions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="environment file to create or update",
    )
    args = parser.parse_args()
    additions = ensure_environment(args.path.resolve())
    if additions:
        print(f"Added {len(additions)} missing setting(s) to {args.path}")
    else:
        print(f"Environment already complete: {args.path}")


if __name__ == "__main__":
    main()
