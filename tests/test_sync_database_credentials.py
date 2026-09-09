from pathlib import Path
from unittest.mock import call, patch

import pytest

from scripts.sync_database_credentials import credential_statement, sql_string, synchronize


def write_environment(path: Path, *, username: str = "g_one") -> None:
    path.write_text(
        f"G_ONE_DB_USER={username}\n"
        "G_ONE_DB_PASSWORD=application-password\n"
        "G_ONE_DB_ROOT_PASSWORD=root-password\n"
    )


def test_sql_string_escapes_quotes_and_backslashes():
    assert sql_string("pass'word\\suffix") == "'pass''word\\\\suffix'"


def test_credential_statement_resets_root_and_application_users():
    assert credential_statement("g_one", "app-password", "root-password") == (
        "FLUSH PRIVILEGES;\n"
        "ALTER USER `root`@`localhost` IDENTIFIED BY 'root-password';\n"
        "ALTER USER `g_one`@`%` IDENTIFIED BY 'app-password';\n"
    )


def test_synchronize_uses_current_root_password_when_it_works(tmp_path):
    write_environment(tmp_path / ".env")

    with patch("scripts.sync_database_credentials.subprocess.run") as run:
        run.return_value.returncode = 0
        synchronize(tmp_path)

    assert run.call_count == 1
    assert run.call_args.kwargs["env"]["MYSQL_PWD"] == "root-password"
    assert "application-password" in run.call_args.kwargs["input"]
    assert run.call_args.kwargs["check"] is False


def test_synchronize_recovers_when_persisted_root_password_differs(tmp_path):
    write_environment(tmp_path / ".env")
    failed_authentication = type("Result", (), {"returncode": 1})()
    successful_command = type("Result", (), {"returncode": 0})()

    with (
        patch(
            "scripts.sync_database_credentials.subprocess.run",
            side_effect=[failed_authentication, successful_command, successful_command,
                         successful_command, successful_command],
        ) as run,
        patch("scripts.sync_database_credentials.compose_command") as compose,
    ):
        synchronize(tmp_path)

    compose.assert_has_calls(
        [
            call(tmp_path, "stop", "web", "database"),
            call(
                tmp_path, "run", "-d", "--rm", "--name",
                "g-one-database-credential-recovery", "--no-deps", "database",
                "--skip-grant-tables", "--skip-networking",
            ),
            call(tmp_path, "up", "-d", "database", "--wait", "--wait-timeout", "120"),
        ]
    )
    recovery_input = run.call_args_list[3].kwargs["input"]
    assert "ALTER USER `root`@`localhost`" in recovery_input
    assert "ALTER USER `g_one`@`%`" in recovery_input


def test_synchronize_rejects_unsafe_username(tmp_path):
    write_environment(tmp_path / ".env", username="g_one`@`localhost")

    with pytest.raises(RuntimeError, match="letters, numbers, and underscores"):
        synchronize(tmp_path)
