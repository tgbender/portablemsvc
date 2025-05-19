import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

from .manifest_items import (
    get_msvc_packages,
    get_sdk_packages,
    resolve_redist_packages
)
from .config import (
    MSVC_PACKAGE_PREFIX,
    MSVC_HOST_TARGET_SUFFIX,
    WIN10_SDK_PREFIX,
    WIN11_SDK_PREFIX
)

logger = logging.getLogger(__name__)

__all__ = ['parse_vs_manifest']

def _first(items, cond=lambda x: True):
    """Find the first item that matches the condition."""
    return next((item for item in items if cond(item)), None)

def _build_package_lookup(vs_manifest):
    """Build a normalized package lookup dictionary."""
    packages = {}
    try:
        for p in vs_manifest["packages"]:
            packages.setdefault(p["id"].lower(), []).append(p)
        return packages
    except KeyError as e:
        raise ValueError(f"Invalid manifest structure: missing 'packages' key") from e

def _find_msvc_versions(packages):
    """Find all MSVC versions in the package dictionary."""
    msvc_versions = {}
    for pid, p in packages.items():
        if pid.startswith(MSVC_PACKAGE_PREFIX.lower()) and pid.endswith(MSVC_HOST_TARGET_SUFFIX.lower()):
            try:
                pver = ".".join(pid.split(".")[2:4])
                if pver[0].isnumeric():
                    msvc_versions[pver] = pid
            except (IndexError, AttributeError) as e:
                logger.warning(f"Skipping malformed MSVC package ID: {pid}")
                continue
    
    if not msvc_versions:
        raise ValueError("No MSVC versions found in manifest")
    return msvc_versions

def _find_sdk_versions(packages):
    """Find all SDK versions in the package dictionary."""
    sdk_versions = {}
    for pid, p in packages.items():
        if (pid.startswith(WIN10_SDK_PREFIX.lower()) or 
            pid.startswith(WIN11_SDK_PREFIX.lower())):
            try:
                pver = pid.split(".")[-1]
                if pver.isnumeric():
                    sdk_versions[pver] = pid
            except (IndexError, AttributeError) as e:
                logger.warning(f"Skipping malformed SDK package ID: {pid}")
                continue
    
    if not sdk_versions:
        raise ValueError("No SDK versions found in manifest")
    return sdk_versions

def _select_msvc_version(msvc_versions, requested_version):
    """Select the MSVC version to use."""
    # Allow specifying a full 4-part build (e.g. "14.44.17.14") and map back to its major.minor bucket
    if requested_version and requested_version.count('.') == 3:
        for bucket, pid in msvc_versions.items():
            full = '.'.join(pid.split('.')[2:6])
            if full == requested_version:
                requested_version = bucket
                break
        else:
            raise ValueError(
                f"Specified full MSVC version {requested_version} not found. "
                f"Available: {', '.join(sorted(msvc_versions.keys()))}"
            )
    if requested_version:
        if requested_version in msvc_versions:
            selected_ver = requested_version
            selected_pid = msvc_versions[requested_version]
        else:
            raise ValueError(f"Specified MSVC version {requested_version} not found. Available versions: {', '.join(sorted(msvc_versions.keys()))}")
    else:
        selected_ver = max(sorted(msvc_versions.keys()))
        selected_pid = msvc_versions[selected_ver]
    
    # Get full MSVC version (includes build number)
    selected_full_ver = ".".join(selected_pid.split(".")[2:6])
    
    return {
        "version": selected_ver,
        "full_version": selected_full_ver,
        "package_id": selected_pid
    }

def _select_sdk_version(sdk_versions, requested_version):
    """Select the SDK version to use."""
    if requested_version:
        if requested_version in sdk_versions:
            selected_ver = requested_version
            selected_pid = sdk_versions[requested_version]
        else:
            raise ValueError(f"Specified SDK version {requested_version} not found. Available versions: {', '.join(sorted(sdk_versions.keys()))}")
    else:
        selected_ver = max(sorted(sdk_versions.keys()))
        selected_pid = sdk_versions[selected_ver]
    
    return {
        "version": selected_ver,
        "package_id": selected_pid
    }

def _get_sdk_package_info(packages, sdk_pid):
    """Get SDK package information."""
    try:
        sdk_pkg = packages[sdk_pid.lower()][0]
        if "dependencies" in sdk_pkg and sdk_pkg["dependencies"]:
            dep_id = _first(sdk_pkg["dependencies"]).lower()
            if dep_id in packages:
                return packages[dep_id][0]
        return None
    except (KeyError, IndexError) as e:
        logger.error(f"Error getting SDK package info: {e}")
        raise ValueError(f"Failed to get SDK package information: {e}") from e


def _validate_manifest_ver(msvc_versions,msvc_ver):
    #First count # of . in msvc_ver
    if msvc_ver is None:
        return None
    num_periods = msvc_ver.count(".")
    if num_periods == 0:
        raise ValueError(f"{msvc_ver} is not a valid MSVC version")
    elif num_periods == 1:
        try:
            full_ver = msvc_versions[msvc_ver]
            full_ver = ".".join(full_ver.split(".")[2:6])
            return full_ver
        except KeyError:
            logger.error(f"MSVC version {msvc_ver} not found in manifest")
            raise ValueError(f"MSVC version {msvc_ver} not found in manifest")
    elif num_periods == 3:
        for value in msvc_versions.values():
            test_value = ".".join(value.split(".")[2:6])
            if msvc_ver == test_value:
                return msvc_ver
        raise ValueError(f"MSVC version {msvc_ver} not found in manifest")
    else:
        raise ValueError(f"MSVC version {msvc_ver} not found in manifest")


def parse_vs_manifest(
    vs_manifest: Dict[str, Any],
    *,
    host: str = "x64",
    targets: List[str] = ["x64"],
    msvc_version: Optional[str] = None,
    sdk_version: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parse the Visual Studio manifest to determine what packages need to be downloaded.
    
    Args:
        vs_manifest: The Visual Studio manifest dictionary
        host: Host architecture (e.g., "x64")
        targets: List of target architectures (e.g., ["x64", "x86"])
        msvc_version: Specific MSVC version to use, or None for latest
        sdk_version: Specific SDK version to use, or None for latest
    
    Returns:
        Dictionary containing:
        - msvc_versions: All available MSVC versions
        - sdk_versions: All available SDK versions
        - selected_msvc: Selected MSVC version and info
        - selected_sdk: Selected SDK version and info
        - msvc_packages: List of MSVC packages to download
        - sdk_packages: List of SDK packages to download
    
    Raises:
        ValueError: If specified versions are not found or manifest is invalid
        KeyError: If required keys are missing from the manifest
    """
    try:
        # Build package lookup
        packages = _build_package_lookup(vs_manifest)
        
        # Find available versions
        msvc_versions = _find_msvc_versions(packages)
        sdk_versions = _find_sdk_versions(packages)

        # Validate manifest version
        msvc_version = _validate_manifest_ver(msvc_versions, msvc_version)

        # Select versions to use
        selected_msvc = _select_msvc_version(msvc_versions, msvc_version)
        selected_sdk = _select_sdk_version(sdk_versions, sdk_version)
        
        # Get package lists
        msvc_packages = get_msvc_packages(selected_msvc["full_version"], host, targets)
        sdk_packages = get_sdk_packages(targets)
        
        # Resolve redist package dependencies
        msvc_packages = resolve_redist_packages(packages, msvc_packages, selected_msvc["full_version"], targets)
        
        # Get SDK package info
        sdk_pkg_info = _get_sdk_package_info(packages, selected_sdk["package_id"])
        if not sdk_pkg_info:
            raise ValueError("Could not find SDK package information")
        
        selected_sdk["package_info"] = sdk_pkg_info

        # Extract payload information for MSVC packages
        msvc_payloads = {}
        for pkg in sorted(msvc_packages):
            pkg_lower = pkg.lower()
            if pkg_lower not in packages:
                logger.warning(f"{pkg} ... !!! MISSING !!!")
                continue

            p = _first(packages[pkg_lower], lambda p: p.get("language") in (None, "en-US"))
            if p and "payloads" in p:
                for payload in p["payloads"]:
                    filename = payload["fileName"]
                    url = payload["url"]
                    sha256 = payload["sha256"]
                    msvc_payloads[filename] = {
                        "url": url,
                        "sha256": sha256,
                        "package": pkg
                    }

        # Extract SDK package payloads
        sdk_payloads = {}
        sdk_pkg_info = selected_sdk.get("package_info")
        if sdk_pkg_info and "payloads" in sdk_pkg_info:
            for pkg in sorted(sdk_packages):
                payload = _first(sdk_pkg_info["payloads"], lambda p: p["fileName"] == f"Installers\\{pkg}")
                if payload:
                    filename = pkg
                    url = payload["url"]
                    sha256 = payload["sha256"]
                    sdk_payloads[filename] = {
                        "url": url,
                        "sha256": sha256,
                        "package": "sdk"
                    }

        # Return the parsed information including payloads
        return {
            "msvc_versions": msvc_versions,
            "sdk_versions": sdk_versions,
            "selected_msvc": selected_msvc,
            "selected_sdk": selected_sdk,
            "msvc_packages": msvc_packages,
            "sdk_packages": sdk_packages,
            "packages": packages,
            "msvc_payloads": msvc_payloads,
            "sdk_payloads": sdk_payloads
        }

        # Return the parsed information
        #return {
        #    "msvc_versions": msvc_versions,
        #    "sdk_versions": sdk_versions,
        #    "selected_msvc": selected_msvc,
        #    "selected_sdk": selected_sdk,
        #    "msvc_packages": msvc_packages,
        #    "sdk_packages": sdk_packages,
        #    "packages": packages,
        #}
        
    except Exception as e:
        logger.error(f"Error parsing VS manifest: {e}")
        raise
