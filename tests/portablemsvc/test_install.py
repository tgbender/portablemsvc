"""Tests that create session-scoped installs. Skipped by default."""

import json
from pathlib import Path
from typing import Any

# Access the shared install_state from conftest
import conftest
import pytest
from plumbum import local

install_state: dict[str, dict[str, Any] | None] = conftest.install_state

pytestmark = pytest.mark.slow_install  # All tests in this file are slow


def test_install_normal(portablemsvc_exe, normal_install_dir: Path):
    """
    Create normal install for session.
    Stores in install_state.normal_test_install.
    """
    data_dir = normal_install_dir / "data"
    config_dir = normal_install_dir / "config"
    temp_dir = normal_install_dir / "temp"
    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    temp_dir.mkdir(parents=True)

    cmd = local[str(portablemsvc_exe)].with_env(
        PORTABLEMSVC_DATA=str(data_dir),
        PORTABLEMSVC_CONFIG=str(config_dir),
        PORTABLEMSVC_TEMP=str(temp_dir),
    )

    cmd["install", "--accept-license", "--target", "x64"]()

    install_path = next(data_dir.glob("msvc-*_sdk-*"))
    lockfile = install_path / "portablemsvc.lock"
    assert lockfile.exists()

    # Verify env.json was created
    env_json = install_path / "env.json"
    assert env_json.exists()
    env = json.loads(env_json.read_text())
    assert "CC" in env
    assert "PATH" in env

    # Store for other tests
    install_state["normal_test_install"] = {
        "data_dir": data_dir,
        "config_dir": config_dir,
        "temp_dir": temp_dir,
        "install_path": install_path,
        "lockfile": lockfile,
        "env": {
            "PORTABLEMSVC_DATA": str(data_dir),
            "PORTABLEMSVC_CONFIG": str(config_dir),
            "PORTABLEMSVC_TEMP": str(temp_dir),
        },
        "install_dir": normal_install_dir,
    }


def test_install_from_lockfile(portablemsvc_exe, lockfile_install_dir: Path):
    """
    Create lockfile install for session.
    Depends on normal_test_install already existing.
    """
    if install_state["normal_test_install"] is None:
        pytest.skip("Need normal_test_install first")
    normal_test_install = install_state["normal_test_install"]
    assert normal_test_install is not None

    data_dir = lockfile_install_dir / "data"
    config_dir = lockfile_install_dir / "config"
    temp_dir = lockfile_install_dir / "temp"
    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    temp_dir.mkdir(parents=True)

    cmd = local[str(portablemsvc_exe)].with_env(
        PORTABLEMSVC_DATA=str(data_dir),
        PORTABLEMSVC_CONFIG=str(config_dir),
        PORTABLEMSVC_TEMP=str(temp_dir),
    )

    cmd[
        "install-from-lockfile",
        str(normal_test_install["lockfile"]),
        "--accept-license",
    ]()

    install_path = next(data_dir.glob("msvc-*_sdk-*"))
    lockfile = install_path / "portablemsvc.lock"
    assert lockfile.exists()

    # Verify env.json was created
    env_json = install_path / "env.json"
    assert env_json.exists()
    env = json.loads(env_json.read_text())
    assert "CC" in env

    install_state["lockfile_test_install"] = {
        "data_dir": data_dir,
        "config_dir": config_dir,
        "temp_dir": temp_dir,
        "install_path": install_path,
        "lockfile": lockfile,
        "env": {
            "PORTABLEMSVC_DATA": str(data_dir),
            "PORTABLEMSVC_CONFIG": str(config_dir),
            "PORTABLEMSVC_TEMP": str(temp_dir),
        },
        "install_dir": lockfile_install_dir,
    }
