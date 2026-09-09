from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.sync_database_credentials import sql_string, synchronize


def write_environment(path: Path, *, username: str = "g_one") -> None:
    path.write_text(
        f"G_ONE_DB_USER={username}\n"
        "G_ONE_DB_PASSWORD=application-password\n"
        "G_ONE_DB_ROOT_PASSWORD=root-password\n"
    )


def test_sql_string_escapes_quotes_and_backslashes():
    assert sql_string("pass'word\\suffix") == "'pass''word\\\\suffix'"


def test_synchronize_resets_persisted_user_password(tmp_path):
    write_environment(tmp_path / ".env")

    with patch("scripts.sync_database_credentials.subprocess.run") as run:
        synchronize(tmp_path)

    command = run.call_args.args[0]
    assert command[:7] == ["docker", "compose", "exec", "-T", "--env", "MYSQL_PWD", "database"]
    assert run.call_args.kwargs["input"] == (
        "ALTER USER `g_one`@`%` IDENTIFIED BY 'application-password';"
    )
    assert run.call_args.kwargs["env"]["MYSQL_PWD"] == "root-password"
    assert run.call_args.kwargs["text"] is True
    assert run.call_args.kwargs["check"] is True


def test_synchronize_rejects_unsafe_username(tmp_path):
    write_environment(tmp_path / ".env", username="g_one`@`localhost")

    with pytest.raises(RuntimeError, match="letters, numbers, and underscores"):
        synchronize(tmp_path)
