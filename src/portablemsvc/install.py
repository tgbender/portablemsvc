import os
import shutil
import logging
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Any

from .install_status import (
    save_installed_version,
    is_version_installed,
    get_installed_versions,
    remove_installation
)

logger = logging.getLogger(__name__)

# Directories to clean up
CLEANUP_DIRS = {
    "common": ["Common7"],
    "msvc": ["Auxiliary"],
    "lib_subdirs": ["store", "uwp", "enclave", "onecore"],
    "sdk": ["Catalogs", "DesignTime", "bin/{sdk_version}/chpe", "Lib/{sdk_version}/ucrt_enclave"]
}

# DIA SDK DLL paths by architecture
MSDIA140_PATHS = {
    "x86": "msdia140.dll",
    "x64": "amd64/msdia140.dll",
    "arm": "arm/msdia140.dll",
    "arm64": "arm64/msdia140.dll",
}

def _cleanup_unnecessary_files(output_dir: Path, msvc_version: str, sdk_version: str, host: str, targets: List[str]):
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
        shutil.rmtree(output_dir / dir_path, ignore_errors=True)
    
    # Remove MSVC-specific unnecessary directories
    msvc_base = output_dir / "VC/Tools/MSVC" / msvc_version
    for dir_path in CLEANUP_DIRS["msvc"]:
        shutil.rmtree(msvc_base / dir_path, ignore_errors=True)
    
    # Remove unnecessary target-specific libraries
    for target in targets:
        for subdir in CLEANUP_DIRS["lib_subdirs"]:
            shutil.rmtree(msvc_base / "lib" / target / subdir, ignore_errors=True)
        shutil.rmtree(msvc_base / f"bin/Host{host}" / target / "onecore", ignore_errors=True)
    
    # Remove unnecessary SDK files
    sdk_base = output_dir / "Windows Kits/10"
    for dir_pattern in CLEANUP_DIRS["sdk"]:
        dir_path = dir_pattern.format(sdk_version=sdk_version)
        shutil.rmtree(sdk_base / dir_path, ignore_errors=True)
    
    # Remove architectures not in targets
    from .config import ALL_TARGETS
    import json
    for arch in ALL_TARGETS:
        if arch not in targets:
            shutil.rmtree(sdk_base / "Lib" / sdk_version / "ucrt" / arch, ignore_errors=True)
            shutil.rmtree(sdk_base / "Lib" / sdk_version / "um" / arch, ignore_errors=True)
        if arch != host:
            shutil.rmtree(msvc_base / f"bin/Host{arch}", ignore_errors=True)
            shutil.rmtree(sdk_base / "bin" / sdk_version / arch, ignore_errors=True)
    
    # Remove telemetry artifacts (exe + DLL)
    for target in targets:
        bin_dir = msvc_base / f"bin/Host{host}" / target
        (bin_dir / "vctip.exe").unlink(missing_ok=True)
        (bin_dir / "Microsoft.VisualStudio.Telemetry.dll").unlink(missing_ok=True)

def _setup_msdia140(output_dir: Path, msvc_version: str, host: str, targets: List[str]):
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
    
    for target in targets:
        shutil.copyfile(src, dst / target / src.name)
    
    shutil.rmtree(output_dir / "DIA%20SDK")

def _setup_debug_crt(output_dir: Path, msvc_version: str, host: str, targets: List[str]):
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
                    dst = output_dir / "VC/Tools/MSVC" / msvc_version / f"bin/Host{host}" / target
                    dst.mkdir(parents=True, exist_ok=True)
                    f.replace(dst / f.name)
        
        shutil.rmtree(redist)

def _create_setup_batch_files(output_dir: Path, msvc_version: str, sdk_version: str, host: str, targets: List[str]):
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
    (build / "vcvarsall.bat").write_text("rem both bat files are here only for nvcc, do not call them manually")
    (build / "vcvars64.bat").touch()
    
    # Create setup batch files for each target
    for target in targets:
        setup_content = fr"""@echo off

set VSCMD_ARG_HOST_ARCH={host}
set VSCMD_ARG_TGT_ARCH={target}

set VCToolsVersion={msvc_version}
set WindowsSDKVersion={sdk_version}\

set VCToolsInstallDir=%~dp0VC\Tools\MSVC\{msvc_version}\
set WindowsSdkBinPath=%~dp0Windows Kits\10\bin\

set PATH=%~dp0VC\Tools\MSVC\{msvc_version}\bin\Host{host}\{target};%~dp0Windows Kits\10\bin\{sdk_version}\{host};%~dp0Windows Kits\10\bin\{sdk_version}\{host}\ucrt;%PATH%
set INCLUDE=%~dp0VC\Tools\MSVC\{msvc_version}\include;%~dp0Windows Kits\10\Include\{sdk_version}\ucrt;%~dp0Windows Kits\10\Include\{sdk_version}\shared;%~dp0Windows Kits\10\Include\{sdk_version}\um;%~dp0Windows Kits\10\Include\{sdk_version}\winrt;%~dp0Windows Kits\10\Include\{sdk_version}\cppwinrt
set LIB=%~dp0VC\Tools\MSVC\{msvc_version}\lib\{target};%~dp0Windows Kits\10\Lib\{sdk_version}\ucrt\{target};%~dp0Windows Kits\10\Lib\{sdk_version}\um\{target}
"""
        (output_dir / f"setup_{target}.bat").write_text(setup_content)

def _detect_versions(output_dir: Path) -> Dict[str, str]:
    """
    Detect MSVC and SDK versions from the extracted files.
    
    Args:
        output_dir: Directory where files were extracted
        
    Returns:
        Dictionary with 'msvc_version' and 'sdk_version'
    """
    versions = {}
    
    # Detect MSVC version by finding the folder that actually has link.exe
    msvc_path = output_dir / "VC/Tools/MSVC"
    if not msvc_path.exists():
        raise ValueError("Could not detect MSVC version (no VC/Tools/MSVC folder)")

    msvc_version = None
    for d in sorted(msvc_path.iterdir()):
        bin_root = d / "bin"
        if bin_root.exists() and any(bin_root.rglob("link.exe")):
            msvc_version = d.name
            break
    if not msvc_version:
        raise ValueError("Could not detect MSVC version (no link.exe found in any subfolder)")
    versions['msvc_version'] = msvc_version
    
    # Detect SDK version
    sdk_path = output_dir / "Windows Kits/10/bin"
    if sdk_path.exists():
        versions['sdk_version'] = next(sdk_path.glob("*")).name
    else:
        raise ValueError("Could not detect SDK version")
    
    return versions

def install_msvc_components(
    output_dir: Path,
    extracted_files: Dict[str, Set[Path]],
    host: str,
    targets: List[str],
    manifest_msvc_version: Optional[str] = None,
    sdk_manifest_version: Optional[str] = None
) -> Dict[str, str]:
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
        
    Returns:
        Dictionary with detected 'msvc_version' and 'sdk_version'
    """
    # ----------------------------------------------------------------
    # Step 1: discover the folder that actually contains link.exe
    detected_versions = _detect_versions(output_dir)
    internal_msvc = detected_versions['msvc_version']
    internal_sdk  = detected_versions['sdk_version']
    # Use manifest version if provided; record manifest vs internal SDK
    manifest_ver     = manifest_msvc_version or internal_msvc
    manifest_sdk     = sdk_manifest_version
    # Always use the detected internal SDK version for env.json and installation record
    sdk_ver          = internal_sdk
    # Override locals for downstream steps
    msvc_version = internal_msvc
    sdk_version = sdk_ver
    # ----------------------------------------------------------------
    
    logger.info(f"Installing MSVC manifest={manifest_ver} internal={internal_msvc} SDK={sdk_ver} host={host} targets={targets}")

    # Check if this version is already installed
    existing_id = is_version_installed(msvc_version, sdk_version, host, targets)
    if existing_id:
        logger.info(f"Version already installed (ID: {existing_id})")
        return {
            'msvc_version': msvc_version,
            'sdk_version': sdk_version,
            'install_id': existing_id
        }
    
    # Perform installation steps
    _setup_debug_crt(output_dir, msvc_version, host, targets)
    _setup_msdia140(output_dir, msvc_version, host, targets)
    _cleanup_unnecessary_files(output_dir, msvc_version, sdk_version, host, targets)
    _create_setup_batch_files(output_dir, msvc_version, sdk_version, host, targets)
    
    # Save installation record
    install_id = save_installed_version(
        output_dir=output_dir,
        manifest_msvc_version=manifest_ver,
        internal_msvc_version=internal_msvc,
        sdk_version=sdk_ver,
        host=host,
        targets=targets
    )
    
    return {
        'msvc_manifest_version': manifest_ver,
        'msvc_internal_version': internal_msvc,
        'sdk_version':           sdk_ver,
        'install_id':            install_id
    }


def _generate_env_spec(
    install_root: Path,
    host: str,
    targets: List[str],
    msvc_version: str,
    sdk_version: str
) -> Dict[str, Any]:
    """
    Build and write install_root/env.json describing all env vars
    needed to activate this MSVC install.
    """
    install_root = install_root.resolve()
    spec: Dict[str, Any] = {
        "VSCMD_ARG_HOST_ARCH": host,
        "VSCMD_ARG_TGT_ARCH": targets,
        "VCToolsVersion": msvc_version,
        "WindowsSDKVersion": sdk_version,
        # legacy compatibility variables
        "VCToolsInstallDir": str(install_root / "VC" / "Tools" / "MSVC" / msvc_version) + "\\",
        "WindowsSDKDir":     str(install_root / "Windows Kits" / "10") + "\\",
    }

    # PATH entries
    path_entries: List[str] = []
    for tgt in targets:
        path_entries.append(str(
            install_root / "VC" / "Tools" / "MSVC" / msvc_version
                          / f"bin/Host{host}" / tgt
        ))
    path_entries.append(str(
        install_root / "Windows Kits" / "10" / "bin" / sdk_version / host
    ))
    path_entries.append(str(
        install_root / "Windows Kits" / "10" / "bin" / sdk_version / host / "ucrt"
    ))
    spec["PATH"] = path_entries

    # INCLUDE entries
    spec["INCLUDE"] = [
        str(install_root / "VC" / "Tools" / "MSVC" / msvc_version / "include"),
        *(str(install_root / "Windows Kits" / "10" / "Include" / sdk_version / sub)
          for sub in ["ucrt","shared","um","winrt","cppwinrt"])
    ]

    # LIB and LIBPATH entries
    lib_entries: List[str] = []
    for tgt in targets:
        lib_entries += [
            str(install_root / "VC" / "Tools" / "MSVC" / msvc_version / "lib" / tgt),
            *(str(install_root / "Windows Kits" / "10" / "Lib" / sdk_version / sub / tgt)
              for sub in ["ucrt","um"])
        ]
    spec["LIB"] = lib_entries
    spec["LIBPATH"] = lib_entries.copy()

    # persist JSON
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "env.json").write_text(json.dumps(spec, indent=2))
    return spec


def _write_activation_scripts(
    install_root: Path,
    spec: Optional[Dict[str, Any]] = None
) -> None:
    """
    Emit activate.cmd and activate.ps1 under install_root,
    reading env.json if spec is None.
    """
    install_root = install_root.resolve()
    if spec is None:
        spec = json.loads((install_root / "env.json").read_text())

    # --- activate.cmd ---
    cmd = ["@echo off", "REM Activate portable MSVC\n"]
    # simple vars
    for key in ("VSCMD_ARG_HOST_ARCH","VSCMD_ARG_TGT_ARCH",
                "VCToolsVersion","WindowsSDKVersion"):
        val = spec[key]
        if isinstance(val, list):
            val = " ".join(val)
        cmd.append(f'set "{key}={val}"')
    # PATH/INCLUDE/LIB/LIBPATH
    for var in ("PATH","INCLUDE","LIB","LIBPATH"):
        entries = spec.get(var, [])
        joined = ";".join(entries) + f";%{var}%"
        cmd.append(f'set "{var}={joined}"')
    cmd.append('echo MSVC %VCToolsVersion% / SDK %WindowsSDKVersion% activated.')
    (install_root / "activate.cmd").write_text("\r\n".join(cmd)+"\r\n", encoding="utf-8")

    # --- activate.ps1 ---
    ps = [
        "# PowerShell Activate for portable MSVC",
        "param()",
        "$here = Split-Path -LiteralPath $MyInvocation.MyCommand.Definition -Parent",
        "",
        "# load JSON spec",
        "$json = Get-Content \"$here\\env.json\" -Raw | ConvertFrom-Json",
        "",
        "# set simple vars",
        '$env:VSCMD_ARG_HOST_ARCH = $json.VSCMD_ARG_HOST_ARCH',
        '$env:VSCMD_ARG_TGT_ARCH  = $json.VSCMD_ARG_TGT_ARCH -join " "',
        '$env:VCToolsVersion      = $json.VCToolsVersion',
        '$env:WindowsSDKVersion   = $json.WindowsSDKVersion',
        "",
        "# prepend PATH",
        '$newPath = $json.PATH | ForEach-Object { Join-Path $here $_ }',
        '$env:PATH = ($newPath -join ";") + ";" + $env:PATH',
        "",
        "# prepend INCLUDE",
        '$newInc = $json.INCLUDE | ForEach-Object { Join-Path $here $_ }',
        '$env:INCLUDE = ($newInc -join ";") + ";" + $env:INCLUDE',
        "",
        "# prepend LIB/LIBPATH",
        '$newLib = $json.LIB | ForEach-Object       { Join-Path $here $_ }',
        '$env:LIB     = ($newLib -join ";")     + ";" + $env:LIB',
        '$newLibPath = $json.LIBPATH | ForEach-Object { Join-Path $here $_ }',
        '$env:LIBPATH = ($newLibPath -join ";") + ";" + $env:LIBPATH',
        "",
        'Write-Host "MSVC $($env:VCToolsVersion) / SDK $($env:WindowsSDKVersion) activated."'
    ]
    (install_root / "activate.ps1").write_text("\n".join(ps)+"\n", encoding="utf-8")
