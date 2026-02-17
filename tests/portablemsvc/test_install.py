"""Tests that create session-scoped installs. Skipped by default."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from plumbum import local

# Access the shared install_state from conftest
import conftest
install_state: Dict[str, Optional[Dict[str, Any]]] = conftest.install_state

pytestmark = pytest.mark.slow_install  # All tests in this file are slow


def test_install_normal(portablemsvc_exe, normal_install_dir: Path):
    """
    Create normal install for session.
    Stores in install_state.normal_test_install.
    """
    data_dir = normal_install_dir / "data"
    config_dir = normal_install_dir / "config"
    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    cmd = local[str(portablemsvc_exe)].with_env(
        PORTABLEMSVC_DATA=str(data_dir),
        PORTABLEMSVC_CONFIG=str(config_dir),
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
        "install_path": install_path,
        "lockfile": lockfile,
        "env": {
            "PORTABLEMSVC_DATA": str(data_dir),
            "PORTABLEMSVC_CONFIG": str(config_dir),
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

    data_dir = lockfile_install_dir / "data"
    config_dir = lockfile_install_dir / "config"
    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    cmd = local[str(portablemsvc_exe)].with_env(
        PORTABLEMSVC_DATA=str(data_dir),
        PORTABLEMSVC_CONFIG=str(config_dir),
    )

    cmd[
        "install-from-lockfile",
        str(install_state["normal_test_install"]["lockfile"]),
        "--accept-license",
    ]()

    install_path = next(data_dir.glob("msvc-*_sdk-*"))

    # Verify env.json was created
    env_json = install_path / "env.json"
    assert env_json.exists()
    env = json.loads(env_json.read_text())
    assert "CC" in env

    install_state["lockfile_test_install"] = {
        "data_dir": data_dir,
        "config_dir": config_dir,
        "install_path": install_path,
        "env": {
            "PORTABLEMSVC_DATA": str(data_dir),
            "PORTABLEMSVC_CONFIG": str(config_dir),
        },
        "install_dir": lockfile_install_dir,
    }
