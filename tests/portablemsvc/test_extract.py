import json
import shutil
import zipfile
from pathlib import Path

import pytest

from portablemsvc.config import CACHE_DIR
from portablemsvc.extract import (
    MsiexecMsiExtractor,
    PyMsiExtractor,
    _extract_msi_file,
    _extract_zip_file,
    _safe_destination_path,
    _validate_replaceable_output_dir,
    extract_package_files,
)
from portablemsvc.parse_msi import get_msi_cab_files


def _get_cached_sdk_msi_payloads() -> dict[str, Path] | None:
    hash_names_path = CACHE_DIR / "downloads" / "hash_to_names.json"
    if not hash_names_path.exists():
        return None

    hash_to_names = json.loads(hash_names_path.read_text(encoding="utf-8"))
    best_msi: tuple[str, Path, int] | None = None
    payloads: dict[str, Path] = {}

    for hash_val, names in hash_to_names.items():
        for name in names:
            cached_path = CACHE_DIR / "downloads" / f"{hash_val}{Path(name).suffix}"
            if not cached_path.exists():
                continue

            if name.lower().endswith(".cab"):
                payloads[Path(name).name] = cached_path
                continue

            if not name.lower().endswith(".msi"):
                continue

            cab_count = len(get_msi_cab_files(cached_path))
            is_sdk = "sdk" in name.lower()
            score = cab_count + (1000 if is_sdk else 0)
            if best_msi is None or score > best_msi[2]:
                best_msi = (Path(name).name, cached_path, score)

    if best_msi is None:
        return None

    return {best_msi[0]: best_msi[1], **payloads}


@pytest.fixture
def cached_sdk_msi_payloads() -> dict[str, Path]:
    payloads = _get_cached_sdk_msi_payloads()
    if payloads is None:
        pytest.skip("No cached SDK MSI payloads found. Run an install first.")
    assert payloads is not None
    return payloads


def _assert_real_sdk_extract(output_dir: Path) -> None:
    files = [path for path in output_dir.rglob("*") if path.is_file()]
    assert files
    assert any("Windows Kits" in path.parts for path in files)


def test_extract_package_files_with_pymsi_real_cached_msi(
    cached_sdk_msi_payloads: dict[str, Path],
    tmp_path: Path,
):
    output_dir = tmp_path / "pymsi"

    extract_package_files(
        cached_sdk_msi_payloads,
        output_dir,
        extract_msvc=False,
        msi_extractor=PyMsiExtractor(),
    )

    _assert_real_sdk_extract(output_dir)


def test_extract_package_files_with_msiexec_real_cached_msi(
    cached_sdk_msi_payloads: dict[str, Path],
    tmp_path: Path,
):
    output_dir = tmp_path / "msiexec"

    extract_package_files(
        cached_sdk_msi_payloads,
        output_dir,
        extract_msvc=False,
        msi_extractor=MsiexecMsiExtractor(),
    )

    _assert_real_sdk_extract(output_dir)


def test_extract_msi_file_preserves_msiexec_path(
    cached_sdk_msi_payloads: dict[str, Path],
    tmp_path: Path,
):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    output_dir = tmp_path / "legacy"
    msi_path: Path | None = None

    for name, source in cached_sdk_msi_payloads.items():
        target = work_dir / name
        shutil.copy2(source, target)
        if name.lower().endswith(".msi"):
            msi_path = target

    assert msi_path is not None

    _extract_msi_file(msi_path, output_dir)

    _assert_real_sdk_extract(output_dir)


def test_safe_destination_path_rejects_escape(tmp_path: Path):
    destination = tmp_path / "out"
    destination.mkdir()

    with pytest.raises(ValueError, match="escapes destination"):
        _safe_destination_path(destination, Path("..") / "evil.txt")


def test_zip_extraction_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Contents/../evil.txt", "bad")

    with pytest.raises(ValueError, match="escapes destination"):
        _extract_zip_file(archive, tmp_path / "out")

    assert not (tmp_path / "evil.txt").exists()


def test_output_replacement_rejects_arbitrary_non_empty_directory(tmp_path: Path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "important.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to replace non-empty directory"):
        _validate_replaceable_output_dir(output)

    assert (output / "important.txt").exists()


def test_output_replacement_allows_existing_portablemsvc_install(tmp_path: Path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "portablemsvc.lock").write_text("{}", encoding="utf-8")

    _validate_replaceable_output_dir(output)
