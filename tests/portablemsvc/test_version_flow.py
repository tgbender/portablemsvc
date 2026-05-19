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
    assert "msvc_toolset_version" in info, "Missing msvc_toolset_version"
    assert "msvc_package_version" in info, "Missing msvc_package_version"

    # MSVC: toolset should be contained in package (e.g., "14.44" in "14.44.17.14")
    toolset_msvc = info["msvc_toolset_version"]
    package_msvc = info["msvc_package_version"]
    assert toolset_msvc in package_msvc, (
        f"msvc_toolset_version {toolset_msvc} not in msvc_package_version {package_msvc}"
    )

    # Should have both SDK version fields
    assert "sdk_version" in info, "Missing sdk_version"
    assert "sdk_build_number" in info, "Missing sdk_build_number"

    # SDK: build number should be contained in version (e.g., "26100" in "10.0.26100.0")
    build_num = info["sdk_build_number"]
    sdk_ver = info["sdk_version"]
    assert build_num in sdk_ver, (
        f"sdk_build_number {build_num} not in sdk_version {sdk_ver}"
    )

    # Verify format: toolset version is short
    assert "." in toolset_msvc, (
        f"msvc_toolset_version should be format like '14.44': {toolset_msvc}"
    )
    assert build_num.isdigit(), (
        f"sdk_build_number should be numeric like '26100': {build_num}"
    )


@pytest.mark.cli
@pytest.mark.slow_install
def test_lockfile_has_correct_version_fields(normal_test_install):
    """Verify lockfile records correct version fields."""
    lockfile = normal_test_install["lockfile"]
    lock_data = json.loads(lockfile.read_text())

    assert "resolved" in lock_data
    resolved = lock_data["resolved"]

    # MSVC: lockfile should have toolset_version and package_version
    assert "msvc" in resolved
    msvc_resolved = resolved["msvc"]
    assert "toolset_version" in msvc_resolved, "Lockfile missing msvc toolset_version"
    assert "package_version" in msvc_resolved, "Lockfile missing msvc package_version"
    assert "package_id" in msvc_resolved, "Lockfile missing msvc package_id"

    # SDK: lockfile should have build_number and version
    assert "sdk" in resolved
    sdk_resolved = resolved["sdk"]
    assert "build_number" in sdk_resolved, "Lockfile missing sdk build_number"
    assert "version" in sdk_resolved, "Lockfile missing sdk version"
    assert "package_id" in sdk_resolved, "Lockfile missing sdk package_id"

    # Verify: lockfile SDK build_number matches DB sdk_build_number
    from portablemsvc.install_status import get_installed_versions

    config_dir = normal_test_install["config_dir"]
    installs = get_installed_versions(db_path=config_dir / "installed.json")
    install_id, db_data = next(iter(installs.items()))

    assert sdk_resolved["build_number"] == db_data["sdk_build_number"], (
        f"Lockfile SDK build_number {sdk_resolved['build_number']} "
        f"!= DB sdk_build_number {db_data['sdk_build_number']}"
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
    msvc_ver = resolved.get("msvc", {}).get("package_version")
    sdk_ver = resolved.get("sdk", {}).get("build_number")

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

    # VCToolsVersion in env.json should match the on-disk vctools version
    assert env["VCToolsVersion"] == db_data["msvc_vctools_version"], (
        f"env.json VCToolsVersion {env['VCToolsVersion']} "
        f"!= DB msvc_vctools_version {db_data['msvc_vctools_version']}"
    )

    # WindowsSDKVersion in env.json should match internal SDK version
    assert env["WindowsSDKVersion"] == db_data["sdk_version"], (
        f"env.json WindowsSDKVersion {env['WindowsSDKVersion']} "
        f"!= DB sdk_version {db_data['sdk_version']}"
    )


@pytest.mark.cli
@pytest.mark.slow_install
def test_get_path_finds_by_lockfile(
    normal_test_install, lockfile_test_install, portablemsvc_exe
):
    """Verify get-path --lockfile finds the correct install for both install types."""
    from plumbum import local
    from plumbum.commands import ProcessExecutionError

    for name, install in [
        ("normal", normal_test_install),
        ("lockfile", lockfile_test_install),
    ]:
        lockfile_path = install.get("lockfile") or (
            install["install_path"] / "portablemsvc.lock"
        )
        cmd = local[str(portablemsvc_exe)].with_env(**install["env"])

        try:
            result = cmd["get-path", "--lockfile", str(lockfile_path)]()
            found_path = result.strip()
            assert found_path, f"{name}: get-path returned empty"
            assert Path(found_path).exists(), (
                f"{name}: get-path returned non-existent path: {found_path}"
            )
            assert found_path == str(install["install_path"]), (
                f"{name}: get-path returned {found_path}, expected {install['install_path']}"
            )
        except ProcessExecutionError as e:
            pytest.fail(f"{name}: get-path --lockfile failed: {e}")


@pytest.mark.cli
@pytest.mark.slow_install
def test_lockfile_resolved_fields_complete(normal_test_install, lockfile_test_install):
    """Verify lockfile resolved section is fully populated for both install types."""
    for name, install in [
        ("normal", normal_test_install),
        ("lockfile", lockfile_test_install),
    ]:
        lockfile_path = install.get("lockfile") or (
            install["install_path"] / "portablemsvc.lock"
        )
        lock_data = json.loads(lockfile_path.read_text())
        resolved = lock_data.get("resolved", {})

        msvc = resolved.get("msvc", {})
        assert msvc.get("toolset_version"), (
            f"{name}: msvc.toolset_version missing or null"
        )
        assert msvc.get("package_version"), (
            f"{name}: msvc.package_version missing or null"
        )
        assert msvc.get("vctools_version"), (
            f"{name}: msvc.vctools_version missing or null"
        )
        assert msvc.get("package_id"), f"{name}: msvc.package_id missing or null"

        sdk = resolved.get("sdk", {})
        assert sdk.get("build_number"), f"{name}: sdk.build_number missing or null"
        assert sdk.get("version"), f"{name}: sdk.version missing or null"
        assert sdk.get("package_id"), f"{name}: sdk.package_id missing or null"


@pytest.mark.cli
@pytest.mark.slow_install
def test_version_consistency_between_installs(
    normal_test_install, lockfile_test_install
):
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
        msvc_toolset = info["msvc_toolset_version"]
        msvc_package = info["msvc_package_version"]
        sdk_build = info["sdk_build_number"]
        sdk_full = info["sdk_version"]

        # MSVC toolset should be major.minor (e.g., "14.44")
        parts = msvc_toolset.split(".")
        assert len(parts) == 2, (
            f"{name}: msvc_toolset_version should be X.Y format: {msvc_toolset}"
        )
        assert all(p.isdigit() for p in parts), (
            f"{name}: msvc_toolset_version parts should be numeric"
        )

        # MSVC package should be X.Y.Z.W or similar
        package_parts = msvc_package.split(".")
        assert len(package_parts) >= 2, (
            f"{name}: msvc_package_version should have more parts"
        )

        # SDK build number should be numeric (e.g., "26100")
        assert sdk_build.isdigit(), (
            f"{name}: sdk_build_number should be numeric: {sdk_build}"
        )

        # SDK version should be Windows SDK format (e.g., "10.0.26100.0")
        sdk_parts = sdk_full.split(".")
        assert len(sdk_parts) == 4, (
            f"{name}: sdk_version should be 10.0.NNNNN.0 format: {sdk_full}"
        )
        assert sdk_parts[0] == "10" and sdk_parts[1] == "0", (
            f"{name}: sdk_version should start with 10.0"
        )
        assert sdk_parts[2] == sdk_build, (
            f"{name}: sdk_version part 3 should match build_number: {sdk_parts[2]} vs {sdk_build}"
        )
