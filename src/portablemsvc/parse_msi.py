import re
import logging

from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def extract_cab_names(data: bytes) -> List[str]:
    """Return embedded .cab filenames found in MSI binary data using original script approach."""
    names = []
    index = 0
    while True:
        index = data.find(b".cab", index + 4)
        if index < 0:
            break
        try:
            cab_name = data[index - 32:index + 4].decode('ascii')
            names.append(cab_name)
        except UnicodeDecodeError:
            pass
    return names

def get_msi_cab_files(path: Path) -> List[str]:
    """Read an MSI file and return embedded .cab filenames."""
    return extract_cab_names(path.read_bytes())

def parse_msi_for_cabs(
    files_map: Dict[str, Path],
    sdk_pkg_info: Dict[str, Any]
) -> Dict[str, Dict[str, str]]:
    """
    Scan downloaded .msi files for embedded .cab names,
    map each to its URL/hash via sdk_pkg_info['payloads'].
    """
    cab_payloads: Dict[str, Dict[str, str]] = {}
    payloads = sdk_pkg_info.get("payloads", [])

    # Create lookup of payloads by filename (case-insensitive)
    payload_lookup = {
        Path(p["fileName"]).name.lower(): p
        for p in payloads
        if "fileName" in p
    }

    for fname, path in files_map.items():
        if not fname.lower().endswith(".msi"):
            continue

        for cab in extract_cab_names(path.read_bytes()):
            cab_name = Path(cab).name.lower()
            if cab_name in payload_lookup:
                match = payload_lookup[cab_name]
                cab_payloads[cab_name] = {
                    "url": match["url"],
                    "hash": match["sha256"],
                    "name": cab_name
                }
            else:
                # Skip logging for known non-critical CABs
                if not cab_name.startswith(("exit.", "inserted.")):
                    logger.warning(f"No payload record for embedded CAB {cab}")

    return cab_payloads
