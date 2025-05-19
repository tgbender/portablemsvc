import logging
from pathlib import Path
from typing import Dict, Any

from .download import download_files
from .config import CACHE_DIR

logger = logging.getLogger(__name__)

__all__ = ['download_manifest_files']

def download_manifest_files(parsed_manifest: Dict[str, Any], cache_dir: Path = CACHE_DIR) -> Dict[str, Path]:
    """
    Download files specified in the parsed manifest.
    
    Args:
        parsed_manifest: Output from parse_vs_manifest
        cache_dir: Directory to store cached downloads
        
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
            "name": filename
        }
    
    # Add SDK payloads (MSI files)
    for filename, payload_info in parsed_manifest.get("sdk_payloads", {}).items():
        all_payloads[filename] = {
            "url": payload_info["url"],
            "hash": payload_info["sha256"],
            "name": filename
        }
    
    # Download all files
    logger.info(f"Downloading {len(all_payloads)} files")
    downloaded_files = download_files(all_payloads, cache_dir)
    
    # Create a mapping from original filenames to file paths
    files_map = {}
    for file_id, file_path in downloaded_files.items():
        files_map[file_id] = file_path
    
    logger.info(f"Successfully downloaded {len(files_map)} files")
    return files_map
