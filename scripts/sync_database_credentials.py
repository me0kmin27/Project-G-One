#!/usr/bin/env python3
"""Synchronize the persisted MariaDB application user with the Compose environment."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from scripts.configure_server import read_environment


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def sql_string(value: str) -> str:
    """Return a MariaDB string literal without exposing quoting to the shell."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def synchronize(root: Path) -> None:
    values = read_environment(root / ".env")
    required = ("G_ONE_DB_USER", "G_ONE_DB_PASSWORD", "G_ONE_DB_ROOT_PASSWORD")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise RuntimeError(f"Missing database setting(s): {', '.join(missing)}")

    username = values["G_ONE_DB_USER"]
    if not SAFE_IDENTIFIER.fullmatch(username):
        raise RuntimeError("G_ONE_DB_USER may contain only letters, numbers, and underscores")

    statement = (
        f"ALTER USER `{username}`@`%` IDENTIFIED BY {sql_string(values['G_ONE_DB_PASSWORD'])};"
    )
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = values["G_ONE_DB_ROOT_PASSWORD"]
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "--env",
            "MYSQL_PWD",
            "database",
            "mariadb",
            "--protocol=socket",
            "--user=root",
        ],
        cwd=root,
        env=environment,
        input=statement,
        text=True,
        check=True,
    )
    print("Database application credentials synchronized.")


if __name__ == "__main__":
    synchronize(Path(__file__).resolve().parents[1])
