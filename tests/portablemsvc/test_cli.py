"""Fast CLI tests using system install."""

import json
from pathlib import Path

import pytest


@pytest.mark.cli
def test_list_system_install_json(portablemsvc, system_install):
    """list --json against system install."""
    result = portablemsvc["list", "--json"]()
    data = json.loads(result)

    # Should find our system install
    assert system_install["install_id"] in data


@pytest.mark.cli
def test_env_json_system_install(system_install):
    """Verify system install has valid env.json."""
    env_path = system_install["install_path"] / "env.json"
    assert env_path.exists()

    env = json.loads(env_path.read_text())
    assert "CC" in env
    assert "PATH" in env
    assert Path(env["CC"]).exists()


@pytest.mark.cli
def test_compile_with_system_install(system_install, tmp_path):
    """Actually compile using system install's env."""
    from plumbum import local

    env = json.loads((system_install["install_path"] / "env.json").read_text())

    test_c = tmp_path / "test.c"
    test_c.write_text('#include <stdio.h>\nint main(){printf("OK");return 0;}')

    new_path = ";".join(env["PATH"]) + ";" + local.env["PATH"]
    cl = local[env["CC"]].with_env(
        PATH=new_path,
        INCLUDE=";".join(env["INCLUDE"]),
        LIB=";".join(env["LIB"]),
    )

    out_exe = tmp_path / "test.exe"
    cl["/nologo", f"/Fe:{out_exe}", str(test_c)]()

    assert out_exe.exists()
    assert local[str(out_exe)]().strip() == "OK"


@pytest.mark.cli
def test_search_json_output(portablemsvc):
    """search --json returns expected structure."""
    result = portablemsvc["search", "--json"]()
    data = json.loads(result)

    assert "msvc" in data
    assert "sdk" in data
    assert isinstance(data["msvc"], list)
    assert isinstance(data["sdk"], list)


@pytest.mark.cli
def test_search_full_json(portablemsvc):
    """search --full --json returns full version strings."""
    result = portablemsvc["search", "--full", "--json"]()
    data = json.loads(result)

    # Full versions should be 4-part (14.44.17.14)
    for ver in data["msvc"]:
        assert ver.count(".") == 3, f"Expected full version, got {ver}"


@pytest.mark.cli
def test_list_empty_directory(portablemsvc_isolated, empty_data_dir, monkeypatch):
    """list with PORTABLEMSVC_DATA pointing to empty dir."""
    monkeypatch.setenv("PORTABLEMSVC_DATA", str(empty_data_dir))
    cmd = portablemsvc_isolated.with_env(PORTABLEMSVC_DATA=str(empty_data_dir))

    result = cmd["list", "--json"]()
    data = json.loads(result)
    assert data == {}


@pytest.mark.cli
def test_list_nonexistent_directory(portablemsvc, tmp_path):
    """list with PORTABLEMSVC_DATA pointing to non-existent dir."""
    fake_path = tmp_path / "does_not_exist"
    cmd = portablemsvc.with_env(PORTABLEMSVC_DATA=str(fake_path))

    result = cmd["list", "--json"]()
    data = json.loads(result)
    assert data == {}


@pytest.mark.cli
def test_help_shows_commands(portablemsvc):
    """--help lists expected commands."""
    result = portablemsvc["--help"]()
    assert "list" in result
    assert "search" in result
    assert "install" in result
