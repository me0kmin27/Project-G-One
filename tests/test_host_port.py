import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.host_port import ensure_host_port, is_g_one_web_container


def completed(stdout: str = "") -> Mock:
    return Mock(stdout=stdout, returncode=0)


@patch("scripts.host_port.port_is_available", return_value=True)
def test_available_port_needs_no_docker_commands(_available, tmp_path):
    ensure_host_port(tmp_path, ["docker"], "0.0.0.0", 8000)


@patch("scripts.host_port.port_is_available", side_effect=[False, True])
@patch("scripts.host_port.is_g_one_web_container", return_value=True)
@patch("scripts.host_port.subprocess.run", side_effect=[completed("abc123\n"), completed()])
def test_removes_stale_g_one_container(_run, _is_g_one, _available, tmp_path):
    ensure_host_port(tmp_path, ["sudo", "docker"], "0.0.0.0", 8000)
    assert _run.call_args_list[1].args[0] == ["sudo", "docker", "rm", "--force", "abc123"]


@patch("scripts.host_port.port_is_available", return_value=False)
@patch("scripts.host_port.is_g_one_web_container", return_value=False)
@patch("scripts.host_port.subprocess.run", return_value=completed("foreign123\n"))
def test_does_not_remove_unrelated_port_owner(_run, _is_g_one, _available, tmp_path):
    with pytest.raises(RuntimeError, match="foreign123"):
        ensure_host_port(tmp_path, ["docker"], "0.0.0.0", 8000)


@patch("scripts.host_port.subprocess.run")
def test_identifies_g_one_web_image(run):
    run.return_value = completed(
        json.dumps([{"Config": {"Image": "g-one-web", "Labels": {"com.docker.compose.service": "web"}}}])
    )
    assert is_g_one_web_container(["docker"], "abc123") is True
