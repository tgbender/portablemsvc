import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config              import CACHE_DIR, DATA_DIR, DEFAULT_HOST, DEFAULT_TARGET
from .registry_helpers    import register_toolchain
from .manifest            import get_vs_manifest
from .parse_manifest      import parse_vs_manifest
from .download_manifest   import download_manifest_files
from .parse_msi           import parse_msi_for_cabs
from .download            import download_files
from .extract             import extract_package_files
from .install             import install_msvc_components
from .install_status      import (
    is_version_installed,
    save_installed_version,
    get_installed_versions,
)
from .install             import _generate_env_spec

logger = logging.getLogger(__name__)

__all__ = ["get_available_versions", "install_msvc"]


def get_available_versions(
    *,
    channel: str = "release",
    cache: bool = True
) -> Dict[str, List[str]]:
    """
    Return dict with 'msvc' and 'sdk' listing the available versions
    for the given channel.
    """
    vs_manifest = get_vs_manifest(channel=channel, cache=cache)
    parsed      = parse_vs_manifest(
        vs_manifest,
        host=DEFAULT_HOST,
        targets=[DEFAULT_TARGET],
    )
    return {
        "msvc": sorted(parsed["msvc_versions"].keys()),
        "sdk":  sorted(parsed["sdk_versions"].keys()),
    }


def install_msvc(
    *,
    host: str = DEFAULT_HOST,
    targets: Optional[List[str]] = None,
    msvc_version: Optional[str] = None,
    sdk_version: Optional[str]  = None,
    channel: str = "release",
    cache: bool = True,
    force: bool = False,
    output_dir: Optional[Path] = None,
    accept_license: bool = False,
) -> Dict[str, Any]:
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
    # 0) license‐check: refuse to continue if no acceptance
    if not accept_license:
        raise RuntimeError("License not accepted; installation aborted.")

    if targets is None:
        targets = [DEFAULT_TARGET]

    # 1) fetch & parse manifest so we know the actual full versions
    vs_manifest = get_vs_manifest(channel=channel, cache=cache)
    parsed      = parse_vs_manifest(
        vs_manifest,
        host=host,
        targets=targets,
        msvc_version=msvc_version,
        sdk_version=sdk_version,
    )

    # 2) skip if that exact full MSVC+SDK is already installed
    if not force:
        sel_msvc = parsed["selected_msvc"]
        sel_sdk  = parsed["selected_sdk"]
        existing_id = is_version_installed(
            sel_msvc["full_version"],
            sel_sdk["version"],
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
    files_map = download_manifest_files(parsed, cache_dir=Path(CACHE_DIR))

    # 4) scan MSIs for CABS & download those too
    sdk_info     = parsed["selected_sdk"]["package_info"]
    cab_payloads = parse_msi_for_cabs(files_map, sdk_info)
    cab_downloads = download_files(cab_payloads, cache_dir=Path(CACHE_DIR))

    all_files = {**files_map, **cab_downloads}

    # 5) extract into final output_dir
    msvc_full = parsed["selected_msvc"]["full_version"]
    sdk_ver   = parsed["selected_sdk"]["version"]
    if output_dir is None:
        output_dir = Path(DATA_DIR) / f"msvc-{msvc_full}_sdk-{sdk_ver}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Extracting all packages to: {output_dir}")
    extracted = extract_package_files(all_files, output_dir)

    # 6) post-extract install steps
    install_result = install_msvc_components(
        output_dir,
        extracted,
        host,
        targets,
        manifest_msvc_version=msvc_full,
        sdk_version=sdk_ver,
    )


    # emit env.json so registry_helpers knows exactly what to register
    _generate_env_spec(
        output_dir,
        host,
        targets,
        install_result["msvc_internal_version"],
        install_result["sdk_version"],
    )
    # automatic registration into HKCU\Environment has been disabled;
    # run "portablemsvc register" manually if you want to set environment vars

    return {
        "already_installed": False,
        "install_id": install_result["install_id"],
        "path": str(output_dir),
        **install_result,
    }
