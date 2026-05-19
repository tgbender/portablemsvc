import logging
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, DATA_DIR, DEFAULT_HOST, DEFAULT_TARGET
from .download import download_files
from .download_manifest import download_manifest_files
from .extract import MsiExtractor, extract_package_files
from .install import _generate_env_spec, _write_activation_scripts, install_msvc_components
from .install_status import (
    get_installed_versions,
    is_version_installed,
)
from .lockfile import Lockfile
from .manifest import get_vs_manifest
from .parse_manifest import parse_vs_manifest
from .parse_msi import parse_msi_for_cabs

logger = logging.getLogger(__name__)

__all__ = ["get_available_versions", "install_msvc", "install_from_lockfile"]


def get_available_versions(
    *, channel: str = "release", cache: bool = True
) -> dict[str, list[str]]:
    """
    Return dict with 'msvc' and 'sdk' listing the available versions
    for the given channel.
    """
    vs_manifest, _ = get_vs_manifest(channel=channel, cache=cache)
    parsed = parse_vs_manifest(
        vs_manifest,
        host=DEFAULT_HOST,
        targets=[DEFAULT_TARGET],
    )
    return {
        "msvc": sorted(parsed["msvc_versions"].keys()),
        "sdk": sorted(parsed["sdk_versions"].keys()),
    }


def install_msvc(
    *,
    host: str = DEFAULT_HOST,
    targets: list[str] | None = None,
    msvc_version: str | None = None,
    sdk_version: str | None = None,
    channel: str = "release",
    cache: bool = True,
    force: bool = False,
    output_dir: Path | None = None,
    lockfile_path: Path | None = None,
    accept_license: bool = False,
    msi_extractor: MsiExtractor | None = None,
) -> dict[str, Any]:
    """
    Full portable-MSVC installation:
      1) check DB for existing install (unless force=True)
      2) download & parse VS manifest
      3) download ZIPs and MSIs
      4) scan MSIs for embedded CABs & download those
      5) extract everything
      6) post-extract setup (CRT, msdia, cleanup, batch files)
      7) record in installed.json
    """
    # Initialize lockfile
    lockfile = Lockfile(
        channel=channel,
        host=host,
        targets=targets if targets else [DEFAULT_TARGET],
        msvc_version=msvc_version,
        sdk_version=sdk_version,
    )

    # 0) license‐check: refuse to continue if no acceptance
    if not accept_license:
        raise RuntimeError("License not accepted; installation aborted.")

    if targets is None:
        targets = [DEFAULT_TARGET]

    # 1) fetch & parse manifest so we know the actual full versions
    vs_manifest, source_info = get_vs_manifest(channel=channel, cache=cache)

    # Record source manifests in lockfile
    lockfile.set_source_manifests(
        channel_manifest_url=source_info["channel_manifest_url"],
        channel_manifest_hash=source_info["channel_manifest_hash"],
        vs_manifest_url=source_info["vs_manifest_url"],
        vs_manifest_hash=source_info["vs_manifest_hash"],
    )

    parsed = parse_vs_manifest(
        vs_manifest,
        host=host,
        targets=targets,
        msvc_version=msvc_version,
        sdk_version=sdk_version,
    )

    # Record resolved versions in lockfile
    lockfile.set_resolved_versions(
        msvc_toolset_version=parsed["selected_msvc"]["toolset_version"],
        msvc_package_version=parsed["selected_msvc"]["package_version"],
        msvc_package_id=parsed["selected_msvc"]["package_id"],
        sdk_build_number=parsed["selected_sdk"]["build_number"],
        sdk_version=parsed["selected_sdk"]["version"],
        sdk_package_id=parsed["selected_sdk"]["package_id"],
    )

    # 2) skip if that exact full MSVC+SDK is already installed
    if not force:
        existing_id = is_version_installed(
            parsed["selected_msvc"]["toolset_version"],
            parsed["selected_sdk"]["build_number"],
            host,
            targets,
        )
        if existing_id:
            inst = get_installed_versions()[existing_id]
            logger.info(f"Already installed: {existing_id} → {inst['path']}")
            return {
                "already_installed": True,
                "install_id": existing_id,
                **inst,
            }

    # 3) download main payloads (ZIPs + MSIs)
    files_map = download_manifest_files(
        parsed,
        cache_dir=Path(CACHE_DIR),
        lockfile=lockfile,
    )

    # 4) scan MSIs for CABS & download those too
    sdk_info = parsed["selected_sdk"]["package_info"]
    cab_payloads = parse_msi_for_cabs(files_map, sdk_info, lockfile=lockfile)
    cab_downloads = download_files(
        cab_payloads, cache_dir=Path(CACHE_DIR), lockfile=lockfile
    )

    all_files = {**files_map, **cab_downloads}

    # 5) extract into final output_dir
    msvc_toolset = parsed["selected_msvc"]["toolset_version"]
    msvc_package = parsed["selected_msvc"]["package_version"]
    sdk_build = parsed["selected_sdk"]["build_number"]
    sdk_ver = parsed["selected_sdk"]["version"]
    if output_dir is None:
        output_dir = Path(DATA_DIR) / f"msvc-{msvc_package}_sdk-{sdk_build}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Extracting all packages to: {output_dir}")
    extracted = extract_package_files(
        all_files,
        output_dir,
        lockfile=lockfile,
        msi_extractor=msi_extractor,
    )

    # 6) post-extract install steps
    install_result = install_msvc_components(
        output_dir,
        extracted,
        host,
        targets,
        msvc_toolset_version=msvc_toolset,
        msvc_package_version=msvc_package,
        sdk_build_number=sdk_build,
        sdk_version=sdk_ver,
        lockfile=lockfile,
    )

    # emit env.json so registry_helpers and activation scripts know exactly what to set
    spec = _generate_env_spec(
        output_dir,
        host,
        targets,
        install_result["msvc_toolset_version"],
        install_result["msvc_package_version"],
        install_result["msvc_vctools_version"],
        install_result["sdk_build_number"],
        install_result["sdk_version"],
        tool_versions=install_result.get("tool_versions"),
    )
    _write_activation_scripts(output_dir, spec)

    # Save lockfile
    lockfile.set_env_spec(spec, output_dir)
    lockfile.set_install_id(install_result["install_id"])
    lockfile_path = lockfile_path or (output_dir / "portablemsvc.lock")
    lockfile.write(lockfile_path)
    logger.info(f"Lockfile written to: {lockfile_path}")

    # automatic registration into HKCU\Environment has been disabled;
    # run "portablemsvc register" manually if you want to set environment vars

    return {
        "already_installed": False,
        "install_id": install_result["install_id"],
        "path": str(output_dir),
        **install_result,
    }


def install_from_lockfile(
    *,
    lockfile_path: Path,
    output_dir: Path | None = None,
    accept_license: bool = False,
    msi_extractor: MsiExtractor | None = None,
) -> dict[str, Any]:
    """
    Install MSVC from an existing lockfile for reproducible builds.
    Uses the exact URLs and hashes recorded in the lockfile.
    """
    if not accept_license:
        raise RuntimeError("License not accepted; installation aborted.")

    logger.info(f"Loading lockfile from: {lockfile_path}")
    lockfile = Lockfile.load(lockfile_path)
    lock_data = lockfile.to_dict()

    resolved = lock_data.get("resolved", {})
    msvc_toolset_ver = resolved.get("msvc", {}).get("toolset_version", "unknown")
    msvc_package_ver = resolved.get("msvc", {}).get("package_version", "unknown")
    sdk_build_num = resolved.get("sdk", {}).get("build_number", "unknown")
    sdk_full_ver = resolved.get("sdk", {}).get("version", "unknown")
    host = lock_data.get("host", "x64")
    targets = lock_data.get("targets", [host])

    # Determine output directory
    if output_dir is None:
        output_dir = Path(DATA_DIR) / f"msvc-{msvc_package_ver}_sdk-{sdk_build_num}"

    # Check if already installed (same as normal flow)
    existing_id = is_version_installed(msvc_toolset_ver, sdk_build_num, host, targets)
    if existing_id:
        inst = get_installed_versions()[existing_id]
        logger.info(f"Already installed: {existing_id} -> {inst['path']}")
        return {
            "already_installed": True,
            "install_id": existing_id,
            **inst,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Installing to: {output_dir}")

    # Build download list from lockfile entries
    files_to_download = {}
    for file_entry in lock_data.get("files", []):
        filename = file_entry["filename"]
        files_to_download[filename] = {
            "url": file_entry["url"],
            "hash": file_entry["sha256"],
            "name": filename,
        }

    # Download all files (reuse existing download infrastructure)
    logger.info(f"Downloading {len(files_to_download)} files from lockfile")
    downloaded_files = download_files(files_to_download, cache_dir=Path(CACHE_DIR))

    # Build files_map compatible with extract_package_files
    # (maps original filename -> local cached path, same shape as normal flow)
    files_map: dict[str, Path] = {}
    for filename, cached_path in downloaded_files.items():
        files_map[filename] = cached_path

    # Extract using the same function as the normal flow
    logger.info(f"Extracting all packages to: {output_dir}")
    extracted = extract_package_files(
        files_map,
        output_dir,
        msi_extractor=msi_extractor,
    )

    # Post-extract install (debug CRT, msdia140, cleanup, batch files, tool versions)
    install_result = install_msvc_components(
        output_dir,
        extracted,
        host,
        targets,
        msvc_toolset_version=msvc_toolset_ver,
        msvc_package_version=msvc_package_ver,
        sdk_build_number=sdk_build_num,
        sdk_version=sdk_full_ver,
        lockfile=lockfile,
    )

    # Generate env spec and activation scripts (same as normal flow)
    spec = _generate_env_spec(
        output_dir,
        host,
        targets,
        install_result["msvc_toolset_version"],
        install_result["msvc_package_version"],
        install_result["msvc_vctools_version"],
        install_result["sdk_build_number"],
        install_result["sdk_version"],
        tool_versions=install_result.get("tool_versions"),
    )
    _write_activation_scripts(output_dir, spec)

    # Write an updated copy of the lockfile that describes this install.
    lockfile.set_env_spec(spec, output_dir)
    lockfile.set_install_id(install_result["install_id"])
    lockfile.write(output_dir / "portablemsvc.lock")

    return {
        "already_installed": False,
        "install_id": install_result["install_id"],
        "path": str(output_dir),
        "msvc_toolset_version": install_result["msvc_toolset_version"],
        "msvc_package_version": install_result["msvc_package_version"],
        "msvc_vctools_version": install_result["msvc_vctools_version"],
        "sdk_version": install_result["sdk_version"],
        "sdk_build_number": install_result["sdk_build_number"],
    }
