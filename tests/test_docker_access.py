from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.docker_access import docker_prefix, ensure_project_writable


def result(code: int) -> Mock:
    return Mock(returncode=code)


@patch("scripts.docker_access.shutil.which", return_value="/usr/bin/docker")
@patch("scripts.docker_access.subprocess.run", return_value=result(0))
def test_uses_unprivileged_docker_when_socket_is_accessible(run, _which):
    assert docker_prefix() == ["docker"]
    assert run.call_args.args[0] == ["docker", "info"]


@patch("scripts.docker_access.shutil.which", side_effect=lambda command: f"/usr/bin/{command}")
@patch("scripts.docker_access.subprocess.run", side_effect=[result(1), result(0)])
def test_elevates_only_docker_when_sudo_has_access(run, _which):
    assert docker_prefix() == ["sudo", "docker"]
    assert run.call_args_list[1].args[0] == ["sudo", "docker", "info"]


@patch("scripts.docker_access.shutil.which", side_effect=lambda command: f"/usr/bin/{command}")
@patch("scripts.docker_access.subprocess.run", side_effect=[result(1), result(1)])
def test_reports_permanent_docker_permission_fix(_run, _which):
    with pytest.raises(RuntimeError, match="usermod -aG docker"):
        docker_prefix()


def test_accepts_writable_project(tmp_path: Path):
    ensure_project_writable(tmp_path)
