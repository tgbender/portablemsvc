import json
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from portablemsvc import __version__
from portablemsvc.install import _generate_env_spec, _write_activation_scripts
from portablemsvc.registry_helpers import (
    REG_EXPAND_SZ,
    REG_SZ,
    _registration_update,
    _unregistration_update,
)


def _write_scripts(root: Path) -> dict:
    spec = _generate_env_spec(
        root,
        "x64",
        ["x64"],
        "14.44",
        "14.44.17.14",
        "14.44.35207",
        "26100",
        "10.0.26100.0",
    )
    _write_activation_scripts(root, spec)
    return spec


def test_package_version_matches_installed_metadata():
    assert __version__ == version("portablemsvc")


def test_powershell_activation_preserves_absolute_paths(tmp_path):
    spec = _write_scripts(tmp_path)
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not available")

    command = (
        "$InformationPreference='SilentlyContinue'; "
        f'& "{tmp_path / "activate.ps1"}" 6>$null | Out-Null; '
        "[Console]::Out.Write($env:PATH)"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )

    expected = spec["PATH"][0]
    assert result.stdout.split(";", 1)[0] == expected
    assert f"{tmp_path}\\{expected}" not in result.stdout


def test_xonsh_activation_script_handles_absolute_paths(tmp_path):
    spec = _write_scripts(tmp_path)
    script = (tmp_path / "activate.xsh").read_text(encoding="utf-8")

    assert "def resolve_portable_path(path):" in script
    assert "p if p.is_absolute() else here / p" in script
    assert "here / p" in script
    assert spec["PATH"][0] in json.loads((tmp_path / "env.json").read_text())["PATH"]


def test_registry_update_helpers_restore_scalar_values():
    install_value = _registration_update("old-cl.exe", "new-cl.exe")
    assert install_value.value == "new-cl.exe"
    assert install_value.value_type == REG_SZ

    restore_value = _unregistration_update("new-cl.exe", "new-cl.exe", "old-cl.exe")
    assert restore_value.value == "old-cl.exe"
    assert restore_value.value_type == REG_SZ

    delete_value = _unregistration_update("new-cl.exe", "new-cl.exe", None)
    assert delete_value.value is None
    assert delete_value.value_type is None

    newer_value = _unregistration_update("newer-cl.exe", "new-cl.exe", "old-cl.exe")
    assert newer_value.value == "newer-cl.exe"
    assert newer_value.value_type == REG_SZ


def test_registry_update_helpers_remove_only_inserted_path_entries():
    install_value = _registration_update("C:\\Existing;C:\\Other", ["C:\\New"])
    assert install_value.value == "C:\\New;C:\\Existing;C:\\Other"
    assert install_value.value_type == REG_EXPAND_SZ

    restore_value = _unregistration_update(
        "C:\\New;C:\\Existing;C:\\Other",
        ["C:\\New"],
        "ignored-for-list-vars",
    )
    assert restore_value.value == "C:\\Existing;C:\\Other"
    assert restore_value.value_type == REG_EXPAND_SZ

    delete_value = _unregistration_update("C:\\New", ["C:\\New"], None)
    assert delete_value.value is None
    assert delete_value.value_type is None


def test_package_import_does_not_exit():
    result = subprocess.run(
        [sys.executable, "-c", "import portablemsvc; print(portablemsvc.__version__)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == __version__
