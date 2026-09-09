import stat

from scripts.ensure_compose_env import DEFAULTS, assigned_keys, ensure_environment


def test_creates_complete_private_environment(tmp_path):
    path = tmp_path / ".env"

    additions = ensure_environment(path)
    contents = path.read_text()

    assert len(additions) == 4
    assert assigned_keys(contents) == {"G_ONE_JWT_SECRET", *DEFAULTS}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    secret = next(line.split("=", 1)[1] for line in contents.splitlines() if line.startswith("G_ONE_JWT_SECRET="))
    assert len(secret) >= 32


def test_preserves_existing_values_and_is_idempotent(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# operator setting\nG_ONE_JWT_SECRET=operator-owned-secret-with-32-bytes\nG_ONE_HTTP_PORT=9000\n")

    first_additions = ensure_environment(path)
    first_contents = path.read_text()
    second_additions = ensure_environment(path)

    assert len(first_additions) == 2
    assert second_additions == []
    assert path.read_text() == first_contents
    assert "G_ONE_HTTP_PORT=9000" in first_contents
    assert "operator-owned-secret-with-32-bytes" in first_contents

