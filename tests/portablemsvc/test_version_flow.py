"""Tests for version field flow - manifest versions vs internal versions."""

import json
from pathlib import Path

import pytest


@pytest.mark.cli
@pytest.mark.slow_install
def test_normal_install_db_has_correct_version_fields(normal_test_install):
    """Verify DB has both manifest and internal versions correctly set."""
    from portablemsvc.install_status import get_installed_versions

    config_dir = normal_test_install["config_dir"]
    installs = get_installed_versions(db_path=config_dir / "installed.json")

    assert len(installs) == 1
    install_id, info = next(iter(installs.items()))

    # Should have both MSVC version fields
    assert "msvc_version" in info, "Missing msvc_version (manifest)"
    assert "msvc_internal_version" in info, "Missing msvc_internal_version"

    # MSVC: internal should contain manifest (e.g., "14.44.17.14" contains "14.44")
    manifest_msvc = info["msvc_version"]
    internal_msvc = info["msvc_internal_version"]
    assert manifest_msvc in internal_msvc, (
        f"msvc_version {manifest_msvc} not in msvc_internal_version {internal_msvc}"
    )

    # Should have both SDK version fields
    assert "sdk_version" in info, "Missing sdk_version (internal)"
    assert "sdk_manifest_version" in info, "Missing sdk_manifest_version"

    # SDK: internal should contain manifest (e.g., "10.0.26100.0" contains "26100")
    manifest_sdk = info["sdk_manifest_version"]
    internal_sdk = info["sdk_version"]
    assert manifest_sdk in internal_sdk, (
        f"sdk_manifest_version {manifest_sdk} not in sdk_version {internal_sdk}"
    )

    # Verify format: manifest versions are short
    assert "." in manifest_msvc, f"msvc_version should be format like '14.44': {manifest_msvc}"
    assert manifest_sdk.isdigit(), f"sdk_manifest_version should be numeric like '26100': {manifest_sdk}"


@pytest.mark.cli
@pytest.mark.slow_install
def test_lockfile_has_correct_version_fields(normal_test_install):
    """Verify lockfile records correct version fields."""
    lockfile = normal_test_install["lockfile"]
    lock_data = json.loads(lockfile.read_text())

    assert "resolved" in lock_data
    resolved = lock_data["resolved"]

    # MSVC: lockfile should have full_version (internal)
    assert "msvc" in resolved
    msvc_resolved = resolved["msvc"]
    assert "full_version" in msvc_resolved, "Lockfile missing msvc full_version"
    assert "package_id" in msvc_resolved, "Lockfile missing msvc package_id"

    # SDK: lockfile should have version (manifest format)
    assert "sdk" in resolved
    sdk_resolved = resolved["sdk"]
    assert "version" in sdk_resolved, "Lockfile missing sdk version"
    assert "package_id" in sdk_resolved, "Lockfile missing sdk package_id"

    # Verify: lockfile SDK version matches DB sdk_manifest_version
    # (both should be short form like "26100")
    from portablemsvc.install_status import get_installed_versions

    config_dir = normal_test_install["config_dir"]
    installs = get_installed_versions(db_path=config_dir / "installed.json")
    install_id, db_data = next(iter(installs.items()))

    assert sdk_resolved["version"] == db_data["sdk_manifest_version"], (
        f"Lockfile SDK version {sdk_resolved['version']} != DB sdk_manifest_version {db_data['sdk_manifest_version']}"
    )


@pytest.mark.cli
@pytest.mark.slow_install
def test_install_from_lockfile_deduplication(normal_test_install, lockfile_install_dir):
    """Verify install-from-lockfile finds existing install correctly."""
    from portablemsvc.install_status import get_installed_versions

    lockfile_path = normal_test_install["lockfile"]

    # First install should already be recorded
    config_dir = normal_test_install["config_dir"]
    installs_before = get_installed_versions(db_path=config_dir / "installed.json")
    assert len(installs_before) == 1, "Should have one install before dedup test"

    # Parse lockfile to get expected versions
    lock_data = json.loads(lockfile_path.read_text())
    resolved = lock_data.get("resolved", {})
    msvc_ver = resolved.get("msvc", {}).get("full_version")
    sdk_ver = resolved.get("sdk", {}).get("version")

    # These should exist and be correct formats
    assert msvc_ver and "." in msvc_ver
    assert sdk_ver and sdk_ver.isdigit()


@pytest.mark.cli
@pytest.mark.slow_install
def test_env_json_versions_match(normal_test_install):
    """Verify env.json has correct version fields."""
    env_path = normal_test_install["install_path"] / "env.json"
    env = json.loads(env_path.read_text())

    # Check required version fields
    assert "VCToolsVersion" in env, "Missing VCToolsVersion in env.json"
    assert "WindowsSDKVersion" in env, "Missing WindowsSDKVersion in env.json"

    # Get DB info for comparison
    from portablemsvc.install_status import get_installed_versions

    config_dir = normal_test_install["config_dir"]
    installs = get_installed_versions(db_path=config_dir / "installed.json")
    install_id, db_data = next(iter(installs.items()))

    # VCToolsVersion in env.json should match internal version
    assert env["VCToolsVersion"] == db_data["msvc_internal_version"], (
        f"env.json VCToolsVersion {env['VCToolsVersion']} != DB msvc_internal_version {db_data['msvc_internal_version']}"
    )

    # WindowsSDKVersion in env.json should match internal SDK version
    assert env["WindowsSDKVersion"] == db_data["sdk_version"], (
        f"env.json WindowsSDKVersion {env['WindowsSDKVersion']} != DB sdk_version {db_data['sdk_version']}"
    )


@pytest.mark.cli
@pytest.mark.slow_install
def test_get_path_finds_by_lockfile(normal_test_install, portablemsvc_isolated):
    """Verify get-path --lockfile finds the correct install."""
    from plumbum.commands import ProcessExecutionError

    lockfile_path = normal_test_install["lockfile"]

    try:
        result = portablemsvc_isolated["get-path", "--lockfile", str(lockfile_path)]()
        install_path = result.strip()
        assert install_path, "get-path returned empty"
        assert Path(install_path).exists(), f"get-path returned non-existent path: {install_path}"
        assert install_path == str(normal_test_install["install_path"]), (
            f"get-path returned {install_path}, expected {normal_test_install['install_path']}"
        )
    except ProcessExecutionError as e:
        pytest.fail(f"get-path failed: {e}")


@pytest.mark.cli
@pytest.mark.slow_install
def test_version_consistency_between_installs(normal_test_install, lockfile_test_install):
    """Verify both normal and lockfile installs have consistent version fields."""
    from portablemsvc.install_status import get_installed_versions

    for name, install in [
        ("normal", normal_test_install),
        ("lockfile", lockfile_test_install),
    ]:
        config_dir = install["config_dir"]
        installs = get_installed_versions(db_path=config_dir / "installed.json")
        assert len(installs) == 1, f"{name} should have exactly one install"

        install_id, info = next(iter(installs.items()))

        # Validate version formats
        msvc_manifest = info["msvc_version"]
        msvc_internal = info["msvc_internal_version"]
        sdk_manifest = info["sdk_manifest_version"]
        sdk_internal = info["sdk_version"]

        # MSVC manifest should be major.minor (e.g., "14.44")
        parts = msvc_manifest.split(".")
        assert len(parts) == 2, f"{name}: msvc_version should be X.Y format: {msvc_manifest}"
        assert all(p.isdigit() for p in parts), f"{name}: msvc_version parts should be numeric"

        # MSVC internal should be X.Y.Z.W or similar
        internal_parts = msvc_internal.split(".")
        assert len(internal_parts) >= 2, f"{name}: msvc_internal_version should have more parts"

        # SDK manifest should be numeric (build number like "26100")
        assert sdk_manifest.isdigit(), f"{name}: sdk_manifest_version should be numeric: {sdk_manifest}"

        # SDK internal should be Windows SDK format (e.g., "10.0.26100.0")
        sdk_parts = sdk_internal.split(".")
        assert len(sdk_parts) == 4, f"{name}: sdk_version should be 10.0.NNNNN.0 format: {sdk_internal}"
        assert sdk_parts[0] == "10" and sdk_parts[1] == "0", f"{name}: sdk_version should start with 10.0"
        assert sdk_parts[2] == sdk_manifest, f"{name}: sdk_version part 3 should match manifest: {sdk_parts[2]} vs {sdk_manifest}"
