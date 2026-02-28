"""Tests specific to install behavior. Uses session test installs."""

import json
from pathlib import Path

import pytest


@pytest.mark.cli
def test_normal_vs_lockfile_same_versions(normal_test_install, lockfile_test_install):
    """Verify both installs have same versions."""
    normal_env = json.loads(
        (normal_test_install["install_path"] / "env.json").read_text()
    )
    lockfile_env = json.loads(
        (lockfile_test_install["install_path"] / "env.json").read_text()
    )

    assert normal_env["VCToolsVersion"] == lockfile_env["VCToolsVersion"]
    assert normal_env["WindowsSDKVersion"] == lockfile_env["WindowsSDKVersion"]


@pytest.mark.cli
def test_normal_install_has_lockfile(normal_test_install):
    """Normal install should create lockfile."""
    assert normal_test_install["lockfile"].exists()

    # Verify lockfile is valid JSON
    lock_data = json.loads(normal_test_install["lockfile"].read_text())
    assert "resolved" in lock_data
    assert "files" in lock_data


@pytest.mark.cli
def test_lockfile_install_matches_original(normal_test_install, lockfile_test_install):
    """Lockfile install should have same core files as original."""
    normal_path = normal_test_install["install_path"]
    lockfile_path = lockfile_test_install["install_path"]

    # Check core executables exist in both
    core_files = ["cl.exe", "link.exe", "lib.exe"]
    msvc_subdir = Path("VC") / "Tools" / "MSVC"

    # Find MSVC version dir (dynamic)
    normal_msvc = next((normal_path / msvc_subdir).glob("*"))
    lockfile_msvc = next((lockfile_path / msvc_subdir).glob("*"))

    for exe in core_files:
        normal_exe = normal_msvc / "bin" / "Hostx64" / "x64" / exe
        lockfile_exe = lockfile_msvc / "bin" / "Hostx64" / "x64" / exe
        assert normal_exe.exists(), f"{exe} missing in normal install"
        assert lockfile_exe.exists(), f"{exe} missing in lockfile install"


@pytest.mark.cli
def test_env_vars_point_to_correct_install(normal_test_install, tmp_path):
    """Using normal_test_install env vars should use that install."""

    env = json.loads((normal_test_install["install_path"] / "env.json").read_text())

    # cl.exe path should be inside normal_test_install
    cl_path = Path(env["CC"])
    assert cl_path.exists()
    assert str(normal_test_install["install_path"]) in str(cl_path)


@pytest.mark.cli
def test_env_json_valid_in_both_installs(normal_test_install, lockfile_test_install):
    """Verify both installs have valid env.json."""
    for name, install in [
        ("normal", normal_test_install),
        ("lockfile", lockfile_test_install),
    ]:
        env_path = install["install_path"] / "env.json"
        assert env_path.exists(), f"{name} install missing env.json"

        env = json.loads(env_path.read_text())
        assert "CC" in env, f"{name} install missing CC"
        assert "CXX" in env, f"{name} install missing CXX"
        assert "AR" in env, f"{name} install missing AR"
        assert "PATH" in env, f"{name} install missing PATH"
        assert "INCLUDE" in env, f"{name} install missing INCLUDE"
        assert "LIB" in env, f"{name} install missing LIB"


@pytest.mark.cli
def test_compile_with_normal_test_install(normal_test_install, tmp_path):
    """Compile using normal test install."""
    from plumbum import local

    env = json.loads((normal_test_install["install_path"] / "env.json").read_text())

    test_c = tmp_path / "test.c"
    test_c.write_text('#include <stdio.h>\nint main(){printf("NORMAL");return 0;}')

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
    assert local[str(out_exe)]().strip() == "NORMAL"


@pytest.mark.cli
def test_compile_with_lockfile_test_install(lockfile_test_install, tmp_path):
    """Compile using lockfile test install."""
    from plumbum import local

    env = json.loads((lockfile_test_install["install_path"] / "env.json").read_text())

    test_c = tmp_path / "test.c"
    test_c.write_text('#include <stdio.h>\nint main(){printf("LOCKFILE");return 0;}')

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
    assert local[str(out_exe)]().strip() == "LOCKFILE"


@pytest.mark.cli
def test_compile_cpp_with_normal_install(normal_test_install, tmp_path):
    """Compile C++ using normal test install."""
    from plumbum import local

    env = json.loads((normal_test_install["install_path"] / "env.json").read_text())

    test_cpp = tmp_path / "test.cpp"
    test_cpp.write_text(
        '#include <iostream>\nint main(){std::cout << "CPP_NORMAL";return 0;}'
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
    assert local[str(out_exe)]().strip() == "CPP_NORMAL"


@pytest.mark.cli
def test_windows_sdk_headers_with_lockfile_install(lockfile_test_install, tmp_path):
    """Compile with Windows SDK headers using lockfile install."""
    from plumbum import local

    env = json.loads((lockfile_test_install["install_path"] / "env.json").read_text())

    test_c = tmp_path / "test_win.c"
    test_c.write_text(
        "#include <windows.h>\n"
        "#include <stdio.h>\n"
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
def test_windows_sdk_headers_with_normal_install(normal_test_install, tmp_path):
    """Compile with Windows SDK headers using normal install."""
    from plumbum import local

    env = json.loads((normal_test_install["install_path"] / "env.json").read_text())

    test_c = tmp_path / "test_win.c"
    test_c.write_text(
        "#include <windows.h>\n"
        "#include <stdio.h>\n"
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
def test_static_lib_with_normal_install(normal_test_install, tmp_path):
    """Create static library using lib.exe from normal install."""
    from plumbum import local

    env = json.loads((normal_test_install["install_path"] / "env.json").read_text())

    # Create source file
    test_c = tmp_path / "test_lib.c"
    test_c.write_text("int test_func(){return 42;}")

    new_path = ";".join(env["PATH"]) + ";" + local.env["PATH"]

    # Compile to object file
    cl = local[env["CC"]].with_env(
        PATH=new_path,
        INCLUDE=";".join(env["INCLUDE"]),
    )

    obj_file = tmp_path / "test_lib.obj"
    cl["/nologo", "/c", f"/Fo:{obj_file}", str(test_c)]()
    assert obj_file.exists()

    # Create static library
    lib = local[env["AR"]].with_env(PATH=new_path)
    lib_file = tmp_path / "test_lib.lib"
    lib["/nologo", f"/OUT:{lib_file}", str(obj_file)]()

    assert lib_file.exists()
    assert lib_file.stat().st_size > 0


@pytest.mark.cli
def test_tool_versions_in_env_json(normal_test_install, lockfile_test_install):
    """Verify TOOL_VERSIONS are captured in both installs."""
    for name, install in [
        ("normal", normal_test_install),
        ("lockfile", lockfile_test_install),
    ]:
        env_path = install["install_path"] / "env.json"
        env = json.loads(env_path.read_text())

        assert "TOOL_VERSIONS" in env, f"{name} install missing TOOL_VERSIONS"
        tool_versions = env["TOOL_VERSIONS"]

        assert "cl.exe" in tool_versions, f"{name} missing cl.exe version"
        # cl.exe should have 19.x version (compiler ABI)
        assert tool_versions["cl.exe"].startswith("19."), (
            f"{name} cl.exe version should start with 19.: {tool_versions['cl.exe']}"
        )
