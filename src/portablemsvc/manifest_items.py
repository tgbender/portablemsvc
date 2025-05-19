import logging
from typing import List, Dict, Any
from .config import DEFAULT_HOST, DEFAULT_TARGET

logger = logging.getLogger(__name__)

def get_msvc_packages(msvc_full_ver, host, targets):
    """Get the list of MSVC packages needed."""
    try:
        # Base packages
        msvc_packages = [
            f"microsoft.visualcpp.dia.sdk",
            f"microsoft.vc.{msvc_full_ver}.crt.headers.base",
            f"microsoft.vc.{msvc_full_ver}.crt.source.base",
            f"microsoft.vc.{msvc_full_ver}.asan.headers.base",
            f"microsoft.vc.{msvc_full_ver}.pgo.headers.base",
        ]

        # Target-specific packages
        for target in targets:
            target_packages = [
                f"microsoft.vc.{msvc_full_ver}.tools.host{host}.target{target}.base",
                f"microsoft.vc.{msvc_full_ver}.tools.host{host}.target{target}.res.base",
                f"microsoft.vc.{msvc_full_ver}.crt.{target}.desktop.base",
                f"microsoft.vc.{msvc_full_ver}.crt.{target}.store.base",
                f"microsoft.vc.{msvc_full_ver}.premium.tools.host{host}.target{target}.base",
                f"microsoft.vc.{msvc_full_ver}.pgo.{target}.base",
            ]
            msvc_packages.extend(target_packages)
            
            # ASAN packages only for x86/x64
            if target in ["x86", "x64"]:
                msvc_packages.append(f"microsoft.vc.{msvc_full_ver}.asan.{target}.base")

            # Redist packages
            redist_suffix = ".onecore.desktop" if target == "arm" else ""
            redist_pkg = f"microsoft.vc.{msvc_full_ver}.crt.redist.{target}{redist_suffix}.base"
            msvc_packages.append(redist_pkg)
        
        return msvc_packages
    except Exception as e:
        logger.error(f"Error determining MSVC packages: {e}")
        raise ValueError(f"Failed to determine required MSVC packages: {e}") from e


def get_sdk_packages(targets):
    """Get the list of SDK packages needed."""
    from .config import ALL_TARGETS

    try:
        # Base SDK packages
        sdk_packages = [
            f"Windows SDK for Windows Store Apps Tools-x86_en-us.msi",
            f"Windows SDK for Windows Store Apps Headers-x86_en-us.msi",
            f"Windows SDK for Windows Store Apps Headers OnecoreUap-x86_en-us.msi",
            f"Windows SDK for Windows Store Apps Libs-x86_en-us.msi",
            f"Universal CRT Headers Libraries and Sources-x86_en-us.msi",
        ]

        # All architectures need headers
        for target in ALL_TARGETS:
            sdk_packages.extend([
                f"Windows SDK Desktop Headers {target}-x86_en-us.msi",
                f"Windows SDK OnecoreUap Headers {target}-x86_en-us.msi",
            ])

        # Only requested targets need libs
        for target in targets:
            sdk_packages.append(f"Windows SDK Desktop Libs {target}-x86_en-us.msi")
        
        return sdk_packages
    except Exception as e:
        logger.error(f"Error determining SDK packages: {e}")
        raise ValueError(f"Failed to determine required SDK packages: {e}") from e

def resolve_redist_packages(packages, msvc_packages, msvc_full_ver, targets):
    """Resolve redist package dependencies."""
    resolved_packages = []
    
    for pkg in msvc_packages:
        pkg_lower = pkg.lower()
        if pkg_lower in packages:
            resolved_packages.append(pkg)
            continue
            
        # Special handling for redist packages
        if "crt.redist" in pkg_lower:
            for target in targets:
                redist_suffix = ".onecore.desktop" if target == "arm" else ""
                if f".{target}{redist_suffix}." in pkg_lower:
                    redist_name = f"microsoft.visualcpp.crt.redist.{target}{redist_suffix}"
                    if redist_name.lower() in packages:
                        redist = _first(packages[redist_name.lower()])
                        if redist and "dependencies" in redist:
                            dep = _first(redist["dependencies"], lambda dep: dep.endswith(".base"))
                            if dep:
                                resolved_packages.append(dep)
                                continue
        
        # If we get here, we couldn't resolve the package
        logger.warning(f"Package {pkg} not found in manifest")
        resolved_packages.append(pkg)  # Keep it in the list anyway
    
    return resolved_packages

def _first(items, cond=lambda x: True):
    """Find the first item that matches the condition."""
    return next((item for item in items if cond(item)), None)

