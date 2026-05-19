import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .install_status import (
    is_version_installed,
    save_installed_version,
)

if TYPE_CHECKING:
    from .lockfile import Lockfile

logger = logging.getLogger(__name__)

# Directories to clean up
CLEANUP_DIRS = {
    "common": ["Common7"],
    "msvc": ["Auxiliary"],
    "lib_subdirs": ["store", "uwp", "enclave", "onecore"],
    "sdk": [
        "Catalogs",
        "DesignTime",
        "bin/{sdk_version}/chpe",
        "Lib/{sdk_version}/ucrt_enclave",
    ],
}

# DIA SDK DLL paths by architecture
MSDIA140_PATHS = {
    "x86": "msdia140.dll",
    "x64": "amd64/msdia140.dll",
    "arm": "arm/msdia140.dll",
    "arm64": "arm64/msdia140.dll",
}


def _cleanup_unnecessary_files(
    output_dir: Path,
    msvc_version: str,
    sdk_version: str,
    host: str,
    targets: list[str],
    lockfile: Optional["Lockfile"] = None,
):
    """
    Remove unnecessary files and directories from the extracted components.

    Args:
        output_dir: Base directory where files were extracted
        msvc_version: Version of MSVC tools
        sdk_version: Version of Windows SDK
        host: Host architecture
        targets: List of target architectures
    """
    logger.info(f"Cleaning up unnecessary files in {output_dir}")

    # Remove common unnecessary directories
    for dir_path in CLEANUP_DIRS["common"]:
        full_path = output_dir / dir_path
        if full_path.exists() and lockfile is not None:
            lockfile.add_removed_file(full_path.relative_to(output_dir))
        shutil.rmtree(full_path, ignore_errors=True)

    # Remove MSVC-specific unnecessary directories
    msvc_base = output_dir / "VC/Tools/MSVC" / msvc_version
    for dir_path in CLEANUP_DIRS["msvc"]:
        full_path = msvc_base / dir_path
        if full_path.exists() and lockfile is not None:
            lockfile.add_removed_file(full_path.relative_to(output_dir))
        shutil.rmtree(full_path, ignore_errors=True)

    # Remove unnecessary target-specific libraries
    for target in targets:
        for subdir in CLEANUP_DIRS["lib_subdirs"]:
            full_path = msvc_base / "lib" / target / subdir
            if full_path.exists() and lockfile is not None:
                lockfile.add_removed_file(full_path.relative_to(output_dir))
            shutil.rmtree(full_path, ignore_errors=True)
        full_path = msvc_base / f"bin/Host{host}" / target / "onecore"
        if full_path.exists() and lockfile is not None:
            lockfile.add_removed_file(full_path.relative_to(output_dir))
        shutil.rmtree(full_path, ignore_errors=True)

    # Remove unnecessary SDK files
    sdk_base = output_dir / "Windows Kits/10"
    for dir_pattern in CLEANUP_DIRS["sdk"]:
        dir_path = dir_pattern.format(sdk_version=sdk_version)
        full_path = sdk_base / dir_path
        if full_path.exists() and lockfile is not None:
            lockfile.add_removed_file(full_path.relative_to(output_dir))
        shutil.rmtree(full_path, ignore_errors=True)

    # Remove architectures not in targets
    from .config import ALL_TARGETS

    for arch in ALL_TARGETS:
        if arch not in targets:
            full_path = sdk_base / "Lib" / sdk_version / "ucrt" / arch
            if full_path.exists() and lockfile is not None:
                lockfile.add_removed_file(full_path.relative_to(output_dir))
            shutil.rmtree(full_path, ignore_errors=True)
            full_path = sdk_base / "Lib" / sdk_version / "um" / arch
            if full_path.exists() and lockfile is not None:
                lockfile.add_removed_file(full_path.relative_to(output_dir))
            shutil.rmtree(full_path, ignore_errors=True)
        if arch != host:
            full_path = msvc_base / f"bin/Host{arch}"
            if full_path.exists() and lockfile is not None:
                lockfile.add_removed_file(full_path.relative_to(output_dir))
            shutil.rmtree(full_path, ignore_errors=True)
            full_path = sdk_base / "bin" / sdk_version / arch
            if full_path.exists() and lockfile is not None:
                lockfile.add_removed_file(full_path.relative_to(output_dir))
            shutil.rmtree(full_path, ignore_errors=True)

    # Remove telemetry artifacts (exe + DLL)
    for target in targets:
        bin_dir = msvc_base / f"bin/Host{host}" / target
        for filename in ["vctip.exe", "Microsoft.VisualStudio.Telemetry.dll"]:
            file_path = bin_dir / filename
            if file_path.exists() and lockfile is not None:
                lockfile.add_removed_file(file_path.relative_to(output_dir))
            file_path.unlink(missing_ok=True)


def _setup_msdia140(output_dir: Path, msvc_version: str, host: str, targets: list[str]):
    """
    Copy msdia140.dll file into MSVC bin folder.

    Args:
        output_dir: Base directory where files were extracted
        msvc_version: Version of MSVC tools
        host: Host architecture
        targets: List of target architectures
    """
    logger.info("Setting up msdia140.dll")

    dst = output_dir / "VC/Tools/MSVC" / msvc_version / f"bin/Host{host}"
    src = output_dir / "DIA%20SDK/bin" / MSDIA140_PATHS[host]

    if not src.exists():
        candidates = list(src.parent.glob("msdia*.dll")) if src.parent.exists() else []
        if candidates:
            src = candidates[0]
        else:
            logger.warning(
                "msdia DLL not found — debug symbol support (DIA SDK) will be unavailable"
            )
            return

    for target in targets:
        shutil.copyfile(src, dst / target / src.name)

    shutil.rmtree(output_dir / "DIA%20SDK")


def _setup_debug_crt(
    output_dir: Path, msvc_version: str, host: str, targets: list[str]
):
    """
    Place debug CRT runtime files into MSVC bin folder.

    Args:
        output_dir: Base directory where files were extracted
        msvc_version: Version of MSVC tools
        host: Host architecture
        targets: List of target architectures
    """
    logger.info("Setting up debug CRT runtime files")

    redist = output_dir / "VC/Redist"

    if redist.exists():
        redistv = next((redist / "MSVC").glob("*")).name
        src = redist / "MSVC" / redistv / "debug_nonredist"

        for target in targets:
            target_src = src / target
            if target_src.exists():
                for f in target_src.glob("**/*.dll"):
                    dst = (
                        output_dir
                        / "VC/Tools/MSVC"
                        / msvc_version
                        / f"bin/Host{host}"
                        / target
                    )
                    dst.mkdir(parents=True, exist_ok=True)
                    f.replace(dst / f.name)

        shutil.rmtree(redist)


def _create_setup_batch_files(
    output_dir: Path, msvc_version: str, sdk_version: str, host: str, targets: list[str]
):
    """
    Create setup batch files for each target architecture.

    Args:
        output_dir: Base directory where files were extracted
        msvc_version: Version of MSVC tools
        sdk_version: Version of Windows SDK
        host: Host architecture
        targets: List of target architectures
    """
    logger.info("Creating setup batch files")

    # Create auxiliary build directory for nvcc
    build = output_dir / "VC/Auxiliary/Build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "vcvarsall.bat").write_text(
        "rem both bat files are here only for nvcc, do not call them manually"
    )
    (build / "vcvars64.bat").touch()
    # Write VCToolsVersion.default.txt so tools that probe this file work correctly
    (build / "Microsoft.VCToolsVersion.default.txt").write_text(
        msvc_version + "\n", encoding="utf-8"
    )

    # Create setup batch files for each target
    for target in targets:
        setup_path = (
            f"%~dp0VC\\Tools\\MSVC\\{msvc_version}\\bin\\Host{host}\\{target};"
            f"%~dp0Windows Kits\\10\\bin\\{sdk_version}\\{host};"
            f"%~dp0Windows Kits\\10\\bin\\{sdk_version}\\{host}\\ucrt;%PATH%"
        )
        setup_include = (
            f"%~dp0VC\\Tools\\MSVC\\{msvc_version}\\include;"
            f"%~dp0Windows Kits\\10\\Include\\{sdk_version}\\ucrt;"
            f"%~dp0Windows Kits\\10\\Include\\{sdk_version}\\shared;"
            f"%~dp0Windows Kits\\10\\Include\\{sdk_version}\\um;"
            f"%~dp0Windows Kits\\10\\Include\\{sdk_version}\\winrt;"
            f"%~dp0Windows Kits\\10\\Include\\{sdk_version}\\cppwinrt"
        )
        setup_lib = (
            f"%~dp0VC\\Tools\\MSVC\\{msvc_version}\\lib\\{target};"
            f"%~dp0Windows Kits\\10\\Lib\\{sdk_version}\\ucrt\\{target};"
            f"%~dp0Windows Kits\\10\\Lib\\{sdk_version}\\um\\{target}"
        )
        setup_content = rf"""@echo off

set VSCMD_ARG_HOST_ARCH={host}
set VSCMD_ARG_TGT_ARCH={target}

set VCToolsVersion={msvc_version}
set WindowsSDKVersion={sdk_version}\

set VCToolsInstallDir=%~dp0VC\Tools\MSVC\{msvc_version}\
set WindowsSdkBinPath=%~dp0Windows Kits\10\bin\

set PATH={setup_path}
set INCLUDE={setup_include}
set LIB={setup_lib}
"""
        (output_dir / f"setup_{target}.bat").write_text(setup_content)


def _detect_msvc_vctools_version(
    output_dir: Path, host: str, primary_target: str
) -> str:
    """
    Detect the actual on-disk VCToolsVersion by scanning VC/Tools/MSVC/.

    The VSIX package_version (e.g. 14.44.17.14) differs from the on-disk
    VCToolsVersion directory name (e.g. 14.44.35207).  We locate the
    highest-versioned subdirectory that actually contains both headers and
    the host/target compiler binary.
    """
    msvc_path = output_dir / "VC/Tools/MSVC"
    if not msvc_path.exists():
        raise ValueError(f"Cannot detect VCToolsVersion: {msvc_path} not found")
    dirs = sorted(
        (d for d in msvc_path.iterdir() if d.is_dir() and d.name[0].isdigit()),
        reverse=True,
    )
    for d in dirs:
        if (d / "include").exists() and (
            d / f"bin/Host{host}/{primary_target}/cl.exe"
        ).exists():
            return d.name
    raise ValueError(
        f"Cannot detect VCToolsVersion: no directory under {msvc_path} "
        f"contains both include/ and bin/Host{host}/{primary_target}/cl.exe"
    )


def install_msvc_components(
    output_dir: Path,
    extracted_files: dict[str, set[Path]],
    host: str,
    targets: list[str],
    msvc_toolset_version: str,
    msvc_package_version: str,
    sdk_build_number: str,
    sdk_version: str,
    lockfile: Optional["Lockfile"] = None,
) -> dict[str, Any]:
    """
    Install MSVC components after extraction.

    This function handles post-extraction setup including:
    - Cleaning up unnecessary files
    - Setting up msdia140.dll
    - Setting up debug CRT runtime files
    - Creating setup batch files

    Args:
        output_dir: Directory where files were extracted
        extracted_files: Dictionary with 'msvc' and 'sdk' keys mapping to sets of extracted paths
        host: Host architecture
        targets: List of target architectures
        msvc_version: Optional specific MSVC version (if None, will be detected)
        sdk_version: Optional specific SDK version (if None, will be detected)
        lockfile: Optional Lockfile instance to record installation

    Returns:
        Dictionary with detected 'msvc_version', 'sdk_version', 'install_id',
        and 'tool_versions'
    """
    actual_toolset = msvc_toolset_version
    actual_package = msvc_package_version
    actual_build_num = sdk_build_number
    actual_sdk_ver = sdk_version

    # Detect the actual on-disk VCToolsVersion (differs from package version)
    primary_tgt = targets[0] if targets else host
    actual_vctools = _detect_msvc_vctools_version(output_dir, host, primary_tgt)
    if lockfile is not None:
        lockfile.set_msvc_vctools_version(actual_vctools)

    logger.info(
        f"Installing MSVC toolset={actual_toolset} package={actual_package} "
        f"vctools={actual_vctools} SDK build={actual_build_num} host={host} targets={targets}"
    )

    # Check if this version is already installed
    existing_id = is_version_installed(actual_toolset, actual_build_num, host, targets)
    if existing_id:
        logger.info(f"Version already installed (ID: {existing_id})")
        return {
            "msvc_toolset_version": actual_toolset,
            "msvc_package_version": actual_package,
            "msvc_vctools_version": actual_vctools,
            "sdk_version": actual_sdk_ver,
            "sdk_build_number": actual_build_num,
            "install_id": existing_id,
        }

    # Perform installation steps
    _setup_debug_crt(output_dir, actual_vctools, host, targets)
    _setup_msdia140(output_dir, actual_vctools, host, targets)
    _cleanup_unnecessary_files(
        output_dir, actual_vctools, actual_sdk_ver, host, targets, lockfile
    )
    _create_setup_batch_files(output_dir, actual_vctools, actual_sdk_ver, host, targets)

    # Collect tool versions (guarded with timeout)
    tool_versions = _collect_tool_versions(
        output_dir, actual_vctools, host, targets, lockfile
    )

    # Save installation record
    install_id = save_installed_version(
        output_dir=output_dir,
        msvc_toolset_version=actual_toolset,
        msvc_package_version=actual_package,
        msvc_vctools_version=actual_vctools,
        sdk_version=actual_sdk_ver,
        sdk_build_number=actual_build_num,
        host=host,
        targets=targets,
    )

    return {
        "msvc_toolset_version": actual_toolset,
        "msvc_package_version": actual_package,
        "msvc_vctools_version": actual_vctools,
        "sdk_version": actual_sdk_ver,
        "sdk_build_number": actual_build_num,
        "install_id": install_id,
        "tool_versions": tool_versions,
    }


def _collect_tool_versions(
    output_dir: Path,
    msvc_version: str,
    host: str,
    targets: list[str],
    lockfile: Optional["Lockfile"] = None,
) -> dict[str, str]:
    """
    Collect PE file versions from MSVC tools (cl.exe, lib.exe, link.exe, nmake.exe).

    Uses pefile to read version info from PE headers.
    Returns empty dict if version collection fails.
    """
    try:
        import pefile
    except ImportError:
        logger.debug("pefile not available, skipping tool version collection")
        return {}

    msvc_bin_root = (
        output_dir / "VC" / "Tools" / "MSVC" / msvc_version / f"bin/Host{host}"
    )
    primary_tgt = targets[0] if targets else host
    msvc_bin = msvc_bin_root / primary_tgt

    tools = {
        "cl.exe": msvc_bin / "cl.exe",
        "lib.exe": msvc_bin / "lib.exe",
        "link.exe": msvc_bin / "link.exe",
    }

    # nmake.exe might be in a different location
    nmake_paths = [
        msvc_bin / "nmake.exe",
        output_dir
        / "VC"
        / "Tools"
        / "MSVC"
        / msvc_version
        / "bin"
        / "Hostx64"
        / "x64"
        / "nmake.exe",
    ]
    for nmake_path in nmake_paths:
        if nmake_path.exists():
            tools["nmake.exe"] = nmake_path
            break

    tool_versions: dict[str, str] = {}

    for tool_name, tool_path in tools.items():
        if not tool_path.exists():
            logger.debug(f"Tool not found: {tool_path}")
            continue

        try:
            pe = pefile.PE(str(tool_path), fast_load=True)
            try:
                pe.parse_data_directories(
                    directories=[
                        pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]
                    ]
                )

                if hasattr(pe, "FileInfo") and pe.FileInfo:
                    for file_info in pe.FileInfo:
                        for entry in file_info:
                            if hasattr(entry, "Key") and entry.Key == b"StringFileInfo":
                                for table in entry.StringTable:
                                    if b"FileVersion" in table.entries:
                                        version = table.entries[b"FileVersion"].decode(
                                            "utf-8", errors="ignore"
                                        )
                                        if version:
                                            tool_versions[tool_name] = version
                                            logger.debug(f"{tool_name}: {version}")
                                        break
            finally:
                pe.close()
        except Exception as e:
            logger.warning(f"Failed to get version for {tool_name}: {e}")

    # Record in lockfile if available
    if lockfile is not None and tool_versions:
        lockfile.set_tool_versions(tool_versions)

    return tool_versions


def _generate_env_spec(
    install_root: Path,
    host: str,
    targets: list[str],
    msvc_toolset_version: str,
    msvc_package_version: str,
    msvc_vctools_version: str,
    sdk_build_number: str,
    sdk_version: str,
    tool_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build and write install_root/env.json describing all env vars
    needed to activate this MSVC install.
    """
    install_root = install_root.resolve()
    msvc_bin_root = (
        install_root
        / "VC"
        / "Tools"
        / "MSVC"
        / msvc_vctools_version
        / f"bin/Host{host}"
    )
    # Pick a primary target for CC/CXX/AR; first requested, or host as fallback
    primary_tgt = targets[0] if targets else host
    msvc_bin_primary = msvc_bin_root / primary_tgt

    spec: dict[str, Any] = {
        "VSCMD_ARG_HOST_ARCH": host,
        "VSCMD_ARG_TGT_ARCH": targets,
        "VCToolsVersion": msvc_vctools_version,
        "WindowsSDKVersion": sdk_version,
        # Portable-MSVC metadata (all version strings explicitly)
        "PORTABLE_MSVC_TOOLSET_VERSION": msvc_toolset_version,
        "PORTABLE_MSVC_PACKAGE_VERSION": msvc_package_version,
        "PORTABLE_MSVC_VCTOOLS_VERSION": msvc_vctools_version,
        "PORTABLE_SDK_BUILD_NUMBER": sdk_build_number,
        "PORTABLE_SDK_VERSION": sdk_version,
        # Compiler / tool variables (absolute paths)
        "CC": str(msvc_bin_primary / "cl.exe"),
        "CXX": str(msvc_bin_primary / "cl.exe"),
        "AR": str(msvc_bin_primary / "lib.exe"),
        # nmake resolves via PATH
        "MAKE": "nmake",
        # classic VS variable pointing at VC root
        "VCINSTALLDIR": str(install_root / "VC") + "\\",
        # legacy compatibility variables
        "VCToolsInstallDir": str(
            install_root / "VC" / "Tools" / "MSVC" / msvc_vctools_version
        )
        + "\\",
        "WindowsSDKDir": str(install_root / "Windows Kits" / "10") + "\\",
    }

    # PATH entries
    path_entries: list[str] = []
    for tgt in targets:
        path_entries.append(str(msvc_bin_root / tgt))

    # Add MSVC CRT redist folders to PATH if present (runtime DLLs)
    # Layout example:
    #   VC/Redist/MSVC/<redist_version>/<arch>/Microsoft.VC*.CRT/
    redist_root = install_root / "VC" / "Redist" / "MSVC"
    if redist_root.exists():
        for ver_dir in sorted(p for p in redist_root.iterdir() if p.is_dir()):
            for tgt in targets:
                arch_root = ver_dir / tgt
                if not arch_root.exists():
                    continue
                for crt_dir in arch_root.glob("Microsoft.VC*.CRT"):
                    if crt_dir.is_dir():
                        path_entries.append(str(crt_dir))

    path_entries.append(
        str(install_root / "Windows Kits" / "10" / "bin" / sdk_version / host)
    )
    path_entries.append(
        str(install_root / "Windows Kits" / "10" / "bin" / sdk_version / host / "ucrt")
    )
    spec["PATH"] = path_entries

    # INCLUDE entries
    spec["INCLUDE"] = [
        str(install_root / "VC" / "Tools" / "MSVC" / msvc_vctools_version / "include"),
        *(
            str(install_root / "Windows Kits" / "10" / "Include" / sdk_version / sub)
            for sub in ["ucrt", "shared", "um", "winrt", "cppwinrt"]
        ),
    ]

    # LIB and LIBPATH entries
    lib_entries: list[str] = []
    for tgt in targets:
        lib_entries += [
            str(
                install_root
                / "VC"
                / "Tools"
                / "MSVC"
                / msvc_vctools_version
                / "lib"
                / tgt
            ),
            *(
                str(
                    install_root
                    / "Windows Kits"
                    / "10"
                    / "Lib"
                    / sdk_version
                    / sub
                    / tgt
                )
                for sub in ["ucrt", "um"]
            ),
        ]
    spec["LIB"] = lib_entries
    spec["LIBPATH"] = lib_entries.copy()

    # Add tool versions if available
    if tool_versions:
        spec["TOOL_VERSIONS"] = tool_versions

    # persist JSON
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "env.json").write_text(json.dumps(spec, indent=2))
    return spec


def _write_activation_scripts(
    install_root: Path, spec: dict[str, Any] | None = None
) -> None:
    """
    Emit activate.cmd and activate.ps1 under install_root,
    reading env.json if spec is None.
    """
    install_root = install_root.resolve()
    if spec is None:
        spec = json.loads((install_root / "env.json").read_text())
    assert spec is not None

    # --- activate.cmd ---
    cmd = ["@echo off", "REM Activate portable MSVC\n"]
    # Portable version metadata
    for key in (
        "PORTABLE_MSVC_TOOLSET_VERSION",
        "PORTABLE_MSVC_PACKAGE_VERSION",
        "PORTABLE_MSVC_VCTOOLS_VERSION",
        "PORTABLE_SDK_BUILD_NUMBER",
        "PORTABLE_SDK_VERSION",
    ):
        val = spec[key]
        cmd.append(f'set "{key}={val}"')
    # simple vars
    for key in (
        "VSCMD_ARG_HOST_ARCH",
        "VSCMD_ARG_TGT_ARCH",
        "VCToolsVersion",
        "WindowsSDKVersion",
        "CC",
        "CXX",
        "AR",
        "MAKE",
        "VCINSTALLDIR",
    ):
        val = spec[key]
        if isinstance(val, list):
            val = " ".join(val)
        cmd.append(f'set "{key}={val}"')
    # PATH/INCLUDE/LIB/LIBPATH
    for var in ("PATH", "INCLUDE", "LIB", "LIBPATH"):
        entries = spec.get(var, [])
        joined = ";".join(entries) + f";%{var}%"
        cmd.append(f'set "{var}={joined}"')
    cmd.append("echo MSVC %VCToolsVersion% / SDK %WindowsSDKVersion% activated.")
    (install_root / "activate.cmd").write_text(
        "\r\n".join(cmd) + "\r\n", encoding="utf-8"
    )

    # --- activate.ps1 ---
    ps = [
        "# PowerShell Activate for portable MSVC",
        "param()",
        "$here = $PSScriptRoot",
        "",
        "# load JSON spec",
        '$json = Get-Content "$here\\env.json" -Raw | ConvertFrom-Json',
        "",
        "function Resolve-PortablePath($path) {",
        "    if ([System.IO.Path]::IsPathRooted($path)) { return $path }",
        "    return (Join-Path $here $path)",
        "}",
        "",
        "# set portable version metadata",
        "$env:PORTABLE_MSVC_TOOLSET_VERSION  = $json.PORTABLE_MSVC_TOOLSET_VERSION",
        "$env:PORTABLE_MSVC_PACKAGE_VERSION  = $json.PORTABLE_MSVC_PACKAGE_VERSION",
        "$env:PORTABLE_MSVC_VCTOOLS_VERSION  = $json.PORTABLE_MSVC_VCTOOLS_VERSION",
        "$env:PORTABLE_SDK_BUILD_NUMBER      = $json.PORTABLE_SDK_BUILD_NUMBER",
        "$env:PORTABLE_SDK_VERSION           = $json.PORTABLE_SDK_VERSION",
        "",
        "# set simple vars",
        "$env:VSCMD_ARG_HOST_ARCH = $json.VSCMD_ARG_HOST_ARCH",
        '$env:VSCMD_ARG_TGT_ARCH  = $json.VSCMD_ARG_TGT_ARCH -join " "',
        "$env:VCToolsVersion      = $json.VCToolsVersion",
        "$env:WindowsSDKVersion   = $json.WindowsSDKVersion",
        "# Compiler / tool variables",
        "$env:CC                  = $json.CC",
        "$env:CXX                 = $json.CXX",
        "$env:AR                  = $json.AR",
        "$env:MAKE                = $json.MAKE",
        "$env:VCINSTALLDIR        = $json.VCINSTALLDIR",
        "",
        "# prepend PATH",
        "$newPath = $json.PATH | ForEach-Object { Resolve-PortablePath $_ }",
        '$env:PATH = ($newPath -join ";") + ";" + $env:PATH',
        "",
        "# prepend INCLUDE",
        "$newInc = $json.INCLUDE | ForEach-Object { Resolve-PortablePath $_ }",
        '$env:INCLUDE = ($newInc -join ";") + ";" + $env:INCLUDE',
        "",
        "# prepend LIB/LIBPATH",
        "$newLib = $json.LIB | ForEach-Object       { Resolve-PortablePath $_ }",
        '$env:LIB     = ($newLib -join ";")     + ";" + $env:LIB',
        "$newLibPath = $json.LIBPATH | ForEach-Object { Resolve-PortablePath $_ }",
        '$env:LIBPATH = ($newLibPath -join ";") + ";" + $env:LIBPATH',
        "",
        'Write-Host "MSVC $($env:VCToolsVersion) / SDK $($env:WindowsSDKVersion) activated."',
    ]
    (install_root / "activate.ps1").write_text("\n".join(ps) + "\n", encoding="utf-8")

    # --- activate.xsh (xonsh) ---
    xsh = [
        "#!/usr/bin/env xonsh",
        "# Activate portable MSVC for xonsh",
        "",
        "import os",
        "import json",
        "import pathlib",
        "",
        "here = pathlib.Path(__file__).parent.resolve()",
        "",
        "# load JSON spec",
        'spec_path = here / "env.json"',
        "with open(spec_path) as f:",
        "    spec = json.load(f)",
        "",
        "def resolve_portable_path(path):",
        "    p = pathlib.Path(path)",
        "    return str(p if p.is_absolute() else here / p)",
        "",
        "# set portable version metadata",
        '$"PORTABLE_MSVC_TOOLSET_VERSION" = spec["PORTABLE_MSVC_TOOLSET_VERSION"]',
        '$"PORTABLE_MSVC_PACKAGE_VERSION" = spec["PORTABLE_MSVC_PACKAGE_VERSION"]',
        '$"PORTABLE_MSVC_VCTOOLS_VERSION" = spec["PORTABLE_MSVC_VCTOOLS_VERSION"]',
        '$"PORTABLE_SDK_BUILD_NUMBER" = spec["PORTABLE_SDK_BUILD_NUMBER"]',
        '$"PORTABLE_SDK_VERSION" = spec["PORTABLE_SDK_VERSION"]',
        "",
        "# set simple vars",
    ]
    for key in (
        "VSCMD_ARG_HOST_ARCH",
        "VCToolsVersion",
        "WindowsSDKVersion",
        "CC",
        "CXX",
        "AR",
        "MAKE",
        "VCINSTALLDIR",
    ):
        xsh.append(f'$"{key}" = spec["{key}"]')
    # VSCMD_ARG_TGT_ARCH is a list
    xsh.append('$"VSCMD_ARG_TGT_ARCH" = " ".join(spec["VSCMD_ARG_TGT_ARCH"])')
    xsh.extend(
        [
            "",
            "# prepend PATH/INCLUDE/LIB/LIBPATH",
            'for var in ["PATH", "INCLUDE", "LIB", "LIBPATH"]:',
            "    entries = spec.get(var, [])",
            "    new_paths = [resolve_portable_path(p) for p in entries]",
            '    os.environ[var] = ";".join(new_paths) + ";" + os.environ.get(var, "")',
            "",
            'print(f"MSVC {$VCToolsVersion} / SDK {$WindowsSDKVersion} activated.")',
        ]
    )
    (install_root / "activate.xsh").write_text("\n".join(xsh) + "\n", encoding="utf-8")
