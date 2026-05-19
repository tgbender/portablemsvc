"""Manual test for MAX_PATH issue with MSI extraction."""

import json
import os
import shutil
from pathlib import Path

import pytest

from portablemsvc.config import CACHE_DIR
from portablemsvc.extract import MsiExtractionError, _extract_msi_file
from portablemsvc.parse_msi import get_msi_cab_files

# Constants
MAX_PATH = 260
# Buffer for internal MSI directory structure (e.g., "\x86\" or similar)
INTERNAL_PATH_BUFFER = 50


def _unc_path(path: Path) -> str:
    """Convert path to UNC extended-length format for bypassing MAX_PATH."""
    abs_path = path.resolve()
    return f"\\\\?\\{abs_path}"


def _get_cached_msi_info() -> tuple[Path, str, list[str]] | None:
    """
    Find a cached MSI and return (hash_path, original_name, cab_names).
    Uses hash_to_names.json to map hash filenames back to original names.
    Prefers MSIs with embedded CABs for more realistic testing.
    """
    hash_names_path = CACHE_DIR / "downloads" / "hash_to_names.json"
    if not hash_names_path.exists():
        return None

    hash_to_names = json.loads(hash_names_path.read_text(encoding="utf-8"))

    best_candidate = None
    best_cab_count = -1

    # Prefer MSIs with CABs for more realistic testing
    for hash_val, names in hash_to_names.items():
        for name in names:
            if name.endswith(".msi"):
                msi_path = CACHE_DIR / "downloads" / f"{hash_val}.msi"
                if msi_path.exists():
                    cab_names = get_msi_cab_files(msi_path)
                    # Prefer SDK MSIs with more CABs
                    is_sdk = "SDK" in name.upper()
                    cab_count = len(cab_names)
                    if is_sdk and cab_count > best_cab_count:
                        best_candidate = (msi_path, name, cab_names)
                        best_cab_count = cab_count
                    elif best_candidate is None:
                        best_candidate = (msi_path, name, cab_names)

    return best_candidate


def _calculate_max_filename_length(cab_names: list[str]) -> int:
    """Calculate the longest filename that will be extracted."""
    if not cab_names:
        # If no CABs, just use the MSI name as a conservative estimate
        return 50  # Typical MSI filename length
    return max(len(name) for name in cab_names)


@pytest.fixture
def msi_setup():
    """Fixture to set up MSI with calculated path requirements."""
    result = _get_cached_msi_info()
    if result is None:
        pytest.skip("No cached MSI found. Run an install first to populate cache.")

    hash_path, original_name, cab_names = result
    max_file_len = _calculate_max_filename_length(cab_names)

    # Calculate the target path length needed to hit MAX_PATH
    # total = target_path_len + internal_buffer + max_filename
    # We want total > MAX_PATH for failure test
    # So: target_path_len > MAX_PATH - internal_buffer - max_filename
    min_target_for_failure = MAX_PATH - INTERNAL_PATH_BUFFER - max_file_len + 1

    # For success: total < MAX_PATH
    # So: target_path_len < MAX_PATH - internal_buffer - max_filename
    # Use -20 for safety margin to ensure we're well under the limit
    max_target_for_success = MAX_PATH - INTERNAL_PATH_BUFFER - max_file_len - 20

    return {
        "hash_path": hash_path,
        "original_name": original_name,
        "cab_names": cab_names,
        "max_file_len": max_file_len,
        "min_target_for_failure": min_target_for_failure,
        "max_target_for_success": max_target_for_success,
    }


def _create_nested_path(base: Path, target_len: int) -> Path:
    """
    Create a directory under base to reach target_len total path length.

    Uses pytest tmp_path for automatic cleanup. Creates a single directory
    with a name made of 'a's to hit the target length exactly.
    """
    base_len = len(str(base.resolve()))

    if base_len >= target_len:
        return base

    # Create one directory with enough 'a's to reach target length
    # -1 accounts for the path separator
    needed = target_len - base_len - 1
    if needed < 1:
        return base

    # Windows has a max component length of 255, so cap at that
    dir_name = "a" * min(needed, 255)
    result = base / dir_name

    # Create using UNC prefix to bypass MAX_PATH
    os.makedirs(_unc_path(result), exist_ok=True)

    return result


def test_msi_extract_path_calculation(msi_setup: dict):
    """
    Verify our path length calculations are correct.
    This helps debug path length issues.
    """
    print(f"MSI: {msi_setup['original_name']}")
    print(f"Max filename: {msi_setup['max_file_len']} chars")
    print(f"Min target for failure: {msi_setup['min_target_for_failure']} chars")
    print(f"Max target for success: {msi_setup['max_target_for_success']} chars")

    # Sanity checks
    assert msi_setup["min_target_for_failure"] > 0
    assert msi_setup["max_target_for_success"] > 0
    assert msi_setup["min_target_for_failure"] > msi_setup["max_target_for_success"]


def test_msi_extract_short_path_succeeds(msi_setup: dict, tmp_path: Path):
    """
    Verify MSI extraction succeeds when total path < MAX_PATH.

    Creates a target path such that:
    target_len + internal_buffer + max_filename < 260
    """
    # Create temp work dir with MSI
    msi_work_dir = tmp_path / "msi_work"
    msi_work_dir.mkdir(parents=True, exist_ok=True)

    hash_path = msi_setup["hash_path"]
    original_name = msi_setup["original_name"]
    max_target = msi_setup["max_target_for_success"]

    # Copy MSI with original name
    msi_dest = msi_work_dir / original_name
    shutil.copy2(hash_path, msi_dest)

    # Copy companion CAB files
    hash_names_path = CACHE_DIR / "downloads" / "hash_to_names.json"
    hash_to_names = json.loads(hash_names_path.read_text(encoding="utf-8"))
    for hash_val, names in hash_to_names.items():
        for name in names:
            if name.endswith(".cab"):
                cab_path = CACHE_DIR / "downloads" / f"{hash_val}.cab"
                if cab_path.exists():
                    cab_dest = msi_work_dir / name
                    shutil.copy2(cab_path, cab_dest)

    # Create target path at calculated safe length
    target_path = _create_nested_path(tmp_path / "short", max_target)

    actual_len = len(str(target_path.resolve()))
    print(f"Short path test: target={actual_len}, max_allowed={max_target}")
    assert actual_len <= max_target, f"Path too long: {actual_len} > {max_target}"

    # Should succeed
    new_files = _extract_msi_file(msi_dest, target_path)
    assert len(new_files) > 0


def test_msi_extract_long_path_fails(msi_setup: dict, tmp_path: Path):
    """
    Verify MSI extraction fails when total path > MAX_PATH.

    Creates a target path such that:
    target_len + internal_buffer + max_filename > 260

    This should cause msiexec to fail (typically with exit code 1603),
    but only if Windows long paths are NOT enabled.
    """
    from portablemsvc.registry_helpers import check_long_paths_enabled

    if check_long_paths_enabled():
        pytest.skip(
            "Windows long paths are enabled in registry. "
            "msiexec will succeed at long paths, so this test is not applicable."
        )

    # Create temp work dir with MSI
    msi_work_dir = tmp_path / "msi_work"
    msi_work_dir.mkdir(parents=True, exist_ok=True)

    hash_path = msi_setup["hash_path"]
    original_name = msi_setup["original_name"]
    min_target = msi_setup["min_target_for_failure"]

    # Copy MSI with original name
    msi_dest = msi_work_dir / original_name
    shutil.copy2(hash_path, msi_dest)

    # Copy companion CAB files
    hash_names_path = CACHE_DIR / "downloads" / "hash_to_names.json"
    hash_to_names = json.loads(hash_names_path.read_text(encoding="utf-8"))
    for hash_val, names in hash_to_names.items():
        for name in names:
            if name.endswith(".cab"):
                cab_path = CACHE_DIR / "downloads" / f"{hash_val}.cab"
                if cab_path.exists():
                    cab_dest = msi_work_dir / name
                    shutil.copy2(cab_path, cab_dest)

    # Create target path at calculated failure length
    target_base = tmp_path / "long"
    target_path = _create_nested_path(target_base, min_target)

    # Use UNC prefix to create the directory (bypasses MAX_PATH for Python)
    unc_target = _unc_path(target_path)
    try:
        os.makedirs(unc_target, exist_ok=True)
    except OSError as e:
        pytest.skip(f"Cannot create deeply nested path: {e}")

    actual_len = len(str(target_path.resolve()))
    print(f"Long path test: target={actual_len}, min_required={min_target}")
    assert actual_len >= min_target, f"Path too short: {actual_len} < {min_target}"

    # Should fail with MsiExtractionError
    with pytest.raises(MsiExtractionError) as exc_info:
        _extract_msi_file(msi_dest, target_path)

    error_msg = str(exc_info.value)
    assert "path length" in error_msg.lower() or "260" in error_msg
