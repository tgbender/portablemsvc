import logging
from pathlib import Path
from typing import Any

from .config import CACHE_DIR
from .download import download_files
from .lockfile import Lockfile

logger = logging.getLogger(__name__)

__all__ = ["download_manifest_files"]


def download_manifest_files(
    parsed_manifest: dict[str, Any],
    cache_dir: Path = CACHE_DIR,
    lockfile: Lockfile | None = None,
) -> dict[str, Path]:
    """
    Download files specified in the parsed manifest.

    Args:
        parsed_manifest: Output from parse_vs_manifest
        cache_dir: Directory to store cached downloads
        lockfile: Optional Lockfile instance to record downloads

    Returns:
        Dictionary mapping original filenames to their local file paths
    """
    logger.info("Preparing to download files from manifest")

    # Combine MSVC and SDK payloads
    all_payloads = {}

    # Add MSVC payloads
    for filename, payload_info in parsed_manifest.get("msvc_payloads", {}).items():
        all_payloads[filename] = {
            "url": payload_info["url"],
            "hash": payload_info["sha256"],
            "name": filename,
        }
        if lockfile is not None:
            file_type = (
                "zip"
                if filename.endswith(".zip")
                else "vsix"
                if filename.endswith(".vsix")
                else "unknown"
            )
            lockfile.add_file(
                file_id=f"msvc_{payload_info['package']}",
                filename=filename,
                url=payload_info["url"],
                sha256=payload_info["sha256"],
                file_type=file_type,
                package_ref=payload_info["package"],
            )

    # Add SDK payloads (MSI files)
    for filename, payload_info in parsed_manifest.get("sdk_payloads", {}).items():
        all_payloads[filename] = {
            "url": payload_info["url"],
            "hash": payload_info["sha256"],
            "name": filename,
        }
        if lockfile is not None:
            lockfile.add_file(
                file_id=f"sdk_{filename}",
                filename=filename,
                url=payload_info["url"],
                sha256=payload_info["sha256"],
                file_type="msi",
                package_ref=payload_info["package"],
            )

    # Download all files
    logger.info(f"Downloading {len(all_payloads)} files")
    downloaded_files = download_files(all_payloads, cache_dir, lockfile=lockfile)

    # Create a mapping from original filenames to file paths
    files_map = {}
    for file_id, file_path in downloaded_files.items():
        files_map[file_id] = file_path

    logger.info(f"Successfully downloaded {len(files_map)} files")
    return files_map
