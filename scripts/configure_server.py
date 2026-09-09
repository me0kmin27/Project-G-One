#!/usr/bin/env python3
"""Safely inspect or update operator-owned G-One server settings."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile


ALLOWED_SETTINGS = {
    "http-port": ("G_ONE_HTTP_PORT", lambda value: 1 <= int(value) <= 65535),
    "http-bind": ("G_ONE_HTTP_BIND", lambda value: value in {"127.0.0.1", "0.0.0.0"}),
    "db-name": ("G_ONE_DB_NAME", lambda value: value.replace("_", "").isalnum()),
    "db-user": ("G_ONE_DB_USER", lambda value: value.replace("_", "").isalnum()),
    "jwt-issuer": ("G_ONE_JWT_ISSUER", lambda value: bool(value.strip())),
    "jwt-audience": ("G_ONE_JWT_AUDIENCE", lambda value: bool(value.strip())),
}
SECRET_MARKERS = ("SECRET", "PASSWORD")


def read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def write_setting(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{key}={value}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().split("=", 1)[0] == key:
            if not replaced:
                updated.append(replacement)
                replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(replacement)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("\n".join(updated) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Configure the G-One server")
    parser.add_argument("--path", type=Path, default=root / ".env")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("show", help="show current settings with secrets hidden")
    setter = subcommands.add_parser("set", help="change one supported setting")
    setter.add_argument("setting", choices=ALLOWED_SETTINGS)
    setter.add_argument("value")
    args = parser.parse_args()
    path = args.path.resolve()
    if args.command == "show":
        for key, value in sorted(read_environment(path).items()):
            displayed = "********" if any(marker in key for marker in SECRET_MARKERS) else value
            print(f"{key}={displayed}")
        return
    key, validator = ALLOWED_SETTINGS[args.setting]
    try:
        valid = validator(args.value)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        parser.error(f"invalid value for {args.setting}")
    write_setting(path, key, args.value)
    print(f"Updated {key} in {path}. Restart the server to apply it.")


if __name__ == "__main__":
    main()
