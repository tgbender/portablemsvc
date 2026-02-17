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
    out_obj = tmp_path / "test.obj"
    cl["/nologo", f"/Fe:{out_exe}", f"/Fo:{out_obj}", str(test_c)]()

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
def test_list_nonexistent_directory(portablemsvc_isolated, tmp_path):
    """list with PORTABLEMSVC_DATA pointing to non-existent dir."""
    fake_path = tmp_path / "does_not_exist"
    cmd = portablemsvc_isolated.with_env(PORTABLEMSVC_DATA=str(fake_path))

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


@pytest.mark.cli
def test_compile_cpp_with_system_install(system_install, tmp_path):
    """Compile C++ code using system install's env."""
    from plumbum import local

    env = json.loads((system_install["install_path"] / "env.json").read_text())

    test_cpp = tmp_path / "test.cpp"
    test_cpp.write_text(
        '#include <iostream>\n'
        'int main(){std::cout << "CPP_OK";return 0;}'
    )

    new_path = ";".join(env["PATH"]) + ";" + local.env["PATH"]
    cl = local[env["CXX"]].with_env(
        PATH=new_path,
        INCLUDE=";".join(env["INCLUDE"]),
        LIB=";".join(env["LIB"]),
    )

    out_exe = tmp_path / "test.exe"
    out_obj = tmp_path / "test.obj"
    cl["/nologo", f"/Fe:{out_exe}", f"/Fo:{out_obj}", str(test_cpp)]()

    assert out_exe.exists()
    assert local[str(out_exe)]().strip() == "CPP_OK"


@pytest.mark.cli
def test_env_json_has_all_required_vars(system_install):
    """Verify env.json contains all required compiler variables."""
    env_path = system_install["install_path"] / "env.json"
    env = json.loads(env_path.read_text())

    required_vars = [
        "CC", "CXX", "AR", "MAKE",
        "VCINSTALLDIR", "VCToolsInstallDir", "WindowsSDKDir",
        "VCToolsVersion", "WindowsSDKVersion",
        "VSCMD_ARG_HOST_ARCH", "VSCMD_ARG_TGT_ARCH",
        "PATH", "INCLUDE", "LIB", "LIBPATH",
    ]

    for var in required_vars:
        assert var in env, f"Missing required env var: {var}"


@pytest.mark.cli
def test_compiler_paths_exist(system_install):
    """Verify compiler executables referenced in env.json exist."""
    env = json.loads((system_install["install_path"] / "env.json").read_text())

    assert Path(env["CC"]).exists(), f"CC not found: {env['CC']}"
    assert Path(env["CXX"]).exists(), f"CXX not found: {env['CXX']}"
    assert Path(env["AR"]).exists(), f"AR not found: {env['AR']}"


@pytest.mark.cli
def test_include_paths_exist(system_install):
    """Verify INCLUDE paths from env.json exist."""
    env = json.loads((system_install["install_path"] / "env.json").read_text())

    for inc_path in env["INCLUDE"]:
        assert Path(inc_path).exists(), f"INCLUDE path not found: {inc_path}"


@pytest.mark.cli
def test_lib_paths_exist(system_install):
    """Verify LIB paths from env.json exist."""
    env = json.loads((system_install["install_path"] / "env.json").read_text())

    for lib_path in env["LIB"]:
        assert Path(lib_path).exists(), f"LIB path not found: {lib_path}"


@pytest.mark.cli
def test_compile_with_windows_headers(system_install, tmp_path):
    """Compile code that includes Windows SDK headers."""
    from plumbum import local

    env = json.loads((system_install["install_path"] / "env.json").read_text())

    test_c = tmp_path / "test_win.c"
    test_c.write_text(
        '#include <windows.h>\n'
        '#include <stdio.h>\n'
        'int main(){printf("WIN_OK");return 0;}'
    )

    new_path = ";".join(env["PATH"]) + ";" + local.env["PATH"]
    cl = local[env["CC"]].with_env(
        PATH=new_path,
        INCLUDE=";".join(env["INCLUDE"]),
        LIB=";".join(env["LIB"]),
    )

    out_exe = tmp_path / "test.exe"
    out_obj = tmp_path / "test.obj"
    cl["/nologo", f"/Fe:{out_exe}", f"/Fo:{out_obj}", str(test_c)]()

    assert out_exe.exists()
    assert local[str(out_exe)]().strip() == "WIN_OK"


@pytest.mark.cli
def test_compiler_version_matches_env(system_install):
    """Verify TOOL_VERSIONS in env.json matches expected format.

    Tool versions should contain cl.exe with 19.x (compiler ABI)
    and other tools with matching minor/build numbers.
    """
    env = json.loads((system_install["install_path"] / "env.json").read_text())

    assert "TOOL_VERSIONS" in env, "TOOL_VERSIONS not found in env.json"
    tool_versions = env["TOOL_VERSIONS"]

    assert "cl.exe" in tool_versions, "cl.exe version not recorded"
    cl_version = tool_versions["cl.exe"]

    # cl.exe uses compiler ABI version (19.x)
    assert cl_version.startswith("19."), f"Expected cl.exe 19.x, got {cl_version}"

    # Extract minor version from cl.exe (e.g., "44" from "19.44.35222.0")
    cl_minor = cl_version.split(".")[1]
    vc_minor = env["VCToolsVersion"].split(".")[1]

    # Minor versions should match between compiler and toolset
    assert cl_minor == vc_minor, (
        f"Version mismatch: cl.exe minor {cl_minor} != VCToolsVersion minor {vc_minor}"
    )


@pytest.mark.cli
def test_ar_lib_tool_works(system_install, tmp_path):
    """Test that lib.exe (AR) can create a static library."""
    from plumbum import local

    env = json.loads((system_install["install_path"] / "env.json").read_text())

    # Create a simple object file first
    test_c = tmp_path / "test_lib.c"
    test_c.write_text("int test_func(){return 42;}")

    new_path = ";".join(env["PATH"]) + ";" + local.env["PATH"]
    cl = local[env["CC"]].with_env(
        PATH=new_path,
        INCLUDE=";".join(env["INCLUDE"]),
    )

    obj_file = tmp_path / "test_lib.obj"
    cl["/nologo", "/c", f"/Fo:{obj_file}", str(test_c)]()
    assert obj_file.exists()

    # Now use lib.exe to create static library
    lib = local[env["AR"]].with_env(PATH=new_path)
    lib_file = tmp_path / "test_lib.lib"
    lib["/nologo", f"/OUT:{lib_file}", str(obj_file)]()

    assert lib_file.exists()
    assert lib_file.stat().st_size > 0
