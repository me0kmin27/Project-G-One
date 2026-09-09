import stat

from scripts.configure_server import ALLOWED_SETTINGS, read_environment, write_setting
from scripts.ensure_compose_env import DEFAULTS, assigned_keys, ensure_environment


def test_creates_complete_private_environment(tmp_path):
    path = tmp_path / ".env"

    additions = ensure_environment(path)
    contents = path.read_text()

    assert len(additions) == 10
    assert assigned_keys(contents) == {
        "G_ONE_JWT_SECRET",
        "G_ONE_DB_PASSWORD",
        "G_ONE_DB_ROOT_PASSWORD",
        "G_ONE_CONSOLE_PASSWORD",
        *DEFAULTS,
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    secret = next(line.split("=", 1)[1] for line in contents.splitlines() if line.startswith("G_ONE_JWT_SECRET="))
    assert len(secret) >= 32


def test_preserves_existing_values_and_is_idempotent(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# operator setting\nG_ONE_JWT_SECRET=operator-owned-secret-with-32-bytes\nG_ONE_HTTP_PORT=9000\n")

    first_additions = ensure_environment(path)
    first_contents = path.read_text()
    second_additions = ensure_environment(path)

    assert len(first_additions) == 8
    assert second_additions == []
    assert path.read_text() == first_contents
    assert "G_ONE_HTTP_PORT=9000" in first_contents
    assert "operator-owned-secret-with-32-bytes" in first_contents


def test_configuration_updates_one_value_without_exposing_or_losing_others(tmp_path):
    path = tmp_path / ".env"
    path.write_text("G_ONE_JWT_SECRET=secret\nG_ONE_HTTP_PORT=8000\n")

    write_setting(path, "G_ONE_HTTP_PORT", "9000")

    assert read_environment(path) == {
        "G_ONE_JWT_SECRET": "secret",
        "G_ONE_HTTP_PORT": "9000",
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_http_bind_accepts_only_supported_listener_addresses():
    validator = ALLOWED_SETTINGS["http-bind"][1]

    assert validator("0.0.0.0")
    assert validator("127.0.0.1")
    assert not validator("192.0.2.10")
