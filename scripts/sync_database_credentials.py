#!/usr/bin/env python3
"""Synchronize persisted MariaDB credentials with the Compose environment."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import time

from scripts.configure_server import read_environment


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
RECOVERY_CONTAINER = "g-one-database-credential-recovery"


def sql_string(value: str) -> str:
    """Return a MariaDB string literal without exposing quoting to the shell."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def compose_command(root: Path, *arguments: str, **options) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *arguments], cwd=root, check=True, **options
    )


def credential_statement(username: str, password: str, root_password: str) -> str:
    return (
        "FLUSH PRIVILEGES;\n"
        f"ALTER USER `root`@`localhost` IDENTIFIED BY {sql_string(root_password)};\n"
        f"ALTER USER `{username}`@`%` IDENTIFIED BY {sql_string(password)};\n"
    )


def authenticate_and_update(root: Path, statement: str, root_password: str) -> bool:
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = root_password
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "--env", "MYSQL_PWD", "database",
            "mariadb", "--protocol=socket", "--user=root",
        ],
        cwd=root,
        env=environment,
        input=statement,
        text=True,
        check=False,
    )
    return result.returncode == 0


def recover_credentials(root: Path, statement: str) -> None:
    """Reset credentials offline when the persisted root password is unknown."""
    print("Stored root password differs from .env; starting offline credential recovery.")
    compose_command(root, "stop", "web", "database")
    subprocess.run(["docker", "rm", "-f", RECOVERY_CONTAINER], check=False, capture_output=True)
    try:
        compose_command(
            root,
            "run", "-d", "--rm", "--name", RECOVERY_CONTAINER, "--no-deps",
            "database", "--skip-grant-tables", "--skip-networking",
        )
        for _ in range(30):
            probe = subprocess.run(
                ["docker", "exec", RECOVERY_CONTAINER, "mariadb-admin", "ping", "--silent"],
                check=False,
                capture_output=True,
            )
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("MariaDB recovery server did not become ready")
        subprocess.run(
            ["docker", "exec", "-i", RECOVERY_CONTAINER, "mariadb", "--user=root"],
            input=statement,
            text=True,
            check=True,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", RECOVERY_CONTAINER], check=False, capture_output=True)
    compose_command(root, "up", "-d", "database", "--wait", "--wait-timeout", "120")


def synchronize(root: Path) -> None:
    values = read_environment(root / ".env")
    required = ("G_ONE_DB_USER", "G_ONE_DB_PASSWORD", "G_ONE_DB_ROOT_PASSWORD")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise RuntimeError(f"Missing database setting(s): {', '.join(missing)}")

    username = values["G_ONE_DB_USER"]
    if not SAFE_IDENTIFIER.fullmatch(username):
        raise RuntimeError("G_ONE_DB_USER may contain only letters, numbers, and underscores")

    statement = credential_statement(
        username, values["G_ONE_DB_PASSWORD"], values["G_ONE_DB_ROOT_PASSWORD"]
    )
    if not authenticate_and_update(root, statement, values["G_ONE_DB_ROOT_PASSWORD"]):
        recover_credentials(root, statement)
    print("Database credentials synchronized.")


if __name__ == "__main__":
    synchronize(Path(__file__).resolve().parents[1])
