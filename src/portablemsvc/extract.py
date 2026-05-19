from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from typing import Protocol

from plumbum import local
from plumbum.commands import ProcessExecutionError

from .config import CACHE_DIR, CONFIG_DIR, DATA_DIR, TEMP_DIR
from .lockfile import Lockfile
from .parse_msi import extract_cab_names as _get_msi_cab_files

logger = logging.getLogger(__name__)


class MsiExtractionError(Exception):
    """Raised when MSI extraction fails or produces no output."""

    pass


class MsiExtractor(Protocol):
    """Extracts one MSI into a destination directory."""

    def extract(self, msi_path: Path, destination: Path) -> set[Path]:
        """Return paths created while extracting an MSI."""
        ...


SYSTEM_FOLDER_PROPERTIES = {
    "AdminToolsFolder",
    "AppDataFolder",
    "CommonAppDataFolder",
    "CommonFiles64Folder",
    "CommonFilesFolder",
    "DesktopFolder",
    "FavoritesFolder",
    "FontsFolder",
    "LocalAppDataFolder",
    "MyPicturesFolder",
    "NetHoodFolder",
    "PersonalFolder",
    "PrintHoodFolder",
    "ProgramFiles64Folder",
    "ProgramFilesFolder",
    "ProgramMenuFolder",
    "RecentFolder",
    "SendToFolder",
    "StartMenuFolder",
    "System16Folder",
    "System64Folder",
    "SystemFolder",
    "TempFolder",
    "TemplateFolder",
    "WindowsFolder",
}


def _safe_destination_path(destination: Path, relative_path: Path | str) -> Path:
    """Return a destination child path, rejecting archive paths that escape it."""
    destination_root = destination.resolve()
    target = (destination / relative_path).resolve()
    if target != destination_root and destination_root not in target.parents:
        raise ValueError(f"Archive path escapes destination: {relative_path}")
    return target


def _safe_artifact_name(name: str) -> str:
    """Return a safe artifact basename for staging downloaded payloads."""
    path = PureWindowsPath(name)
    if (
        path.is_absolute()
        or path.name != name
        or name in {"", ".", ".."}
        or ":" in name
    ):
        raise ValueError(f"Unsafe package artifact name: {name!r}")
    return name


def _looks_like_portablemsvc_output(path: Path) -> bool:
    lockfile = path / "portablemsvc.lock"
    if not lockfile.is_file():
        return False

    try:
        lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    return lock_data.get("lockfile_version") == "1.0"


def _validate_replaceable_output_dir(output_dir: Path) -> None:
    resolved = output_dir.resolve()

    if resolved == Path(resolved.anchor):
        raise ValueError(f"Refusing to replace drive root: {output_dir}")

    protected_dirs = {
        Path.cwd().resolve(),
        Path.home().resolve(),
        Path(TEMP_DIR).resolve(),
        Path(CACHE_DIR).resolve(),
        Path(CONFIG_DIR).resolve(),
        Path(DATA_DIR).resolve(),
    }
    if resolved in protected_dirs:
        raise ValueError(f"Refusing to replace protected directory: {output_dir}")

    if not output_dir.is_dir():
        raise ValueError(f"Refusing to replace non-directory output path: {output_dir}")

    if any(output_dir.iterdir()) and not _looks_like_portablemsvc_output(output_dir):
        raise ValueError(
            "Refusing to replace non-empty directory that does not look like a "
            f"PortableMSVC install: {output_dir}"
        )


def _msi_long_name(name: str) -> str:
    """Return the long filename from an MSI short|long name field."""
    return name.split("|", 1)[1] if "|" in name else name


def _created_paths_around_extraction(
    extractor_name: str,
    msi_path: Path,
    destination: Path,
    extract: Callable[[], None],
) -> set[Path]:
    files_before = set(destination.rglob("*")) if destination.exists() else set()
    extract()
    files_after = set(destination.rglob("*")) if destination.exists() else set()
    new_files = files_after - files_before

    if not new_files:
        raise MsiExtractionError(
            f"{extractor_name} extraction produced no files: {msi_path.name} "
            f"(target path length: {len(str(destination.resolve()))} chars)."
        )

    logger.info(
        f"{extractor_name} extraction successful: "
        f"{len(new_files)} new files from {msi_path.name}"
    )
    return new_files


class PyMsiExtractor:
    """Pure-Python MSI extractor backed by python-msi/pymsi."""

    def extract(self, msi_path: Path, destination: Path) -> set[Path]:
        logger.info(f"Extracting MSI with pymsi: {msi_path} → {destination}")
        destination.mkdir(parents=True, exist_ok=True)

        try:
            from pymsi.msi import Msi
            from pymsi.package import Package
        except ImportError as exc:
            raise MsiExtractionError("python-msi is not installed") from exc

        def run_pymsi() -> None:
            shutil.copy2(msi_path, destination / msi_path.name)
            with Package(msi_path) as package:
                msi = Msi(package, load_data=True, strict=False)
                self._extract_root(msi.root, destination)

        try:
            return _created_paths_around_extraction(
                "pymsi", msi_path, destination, run_pymsi
            )
        except MsiExtractionError:
            raise
        except Exception as exc:
            raise MsiExtractionError(
                f"pymsi extraction failed for {msi_path.name}: {exc}"
            ) from exc

    def _extract_root(self, root, output: Path, is_root: bool = True) -> None:
        output.mkdir(parents=True, exist_ok=True)

        for component in root.components.values():
            for file in component.files.values():
                if getattr(file, "media", None) is None:
                    continue
                cab_file = file.resolve()
                out_path = _safe_destination_path(output, _msi_long_name(file.name))
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(cab_file.decompress())

        for child in root.children.values():
            folder_name = _msi_long_name(child.name)
            if is_root:
                if "." in child.id:
                    folder_name = child.id.split(".", 1)[0]
                elif child.id in SYSTEM_FOLDER_PROPERTIES:
                    folder_name = "."
            self._extract_root(
                child, _safe_destination_path(output, folder_name), False
            )


class MsiexecMsiExtractor:
    """MSI extractor backed by the legacy msiexec /a extraction hack."""

    def extract(self, msi_path: Path, destination: Path) -> set[Path]:
        logger.info(f"Extracting MSI with msiexec: {msi_path} → {destination}")

        target_dir = str(destination.resolve())
        if len(target_dir) > 200:
            logger.warning(
                f"Target path is {len(target_dir)} chars, likely to hit 260 char "
                f"limit for nested files: {target_dir}"
            )

        msiexec = local["msiexec.exe"]

        try:
            return _created_paths_around_extraction(
                "msiexec",
                msi_path,
                destination,
                lambda: msiexec[
                    "/a", str(msi_path), "/quiet", "/qn", f"TARGETDIR={target_dir}"
                ](),
            )
        except ProcessExecutionError as e:
            raise MsiExtractionError(
                f"MSI extraction failed for {msi_path.name}: "
                f"msiexec exited with code {e.retcode}. "
                f"Target path is {len(target_dir)} chars. "
                f"This often indicates the path exceeded Windows' 260 char limit."
            ) from e


class FallbackMsiExtractor:
    """Try a primary extractor and fall back if it cannot extract the MSI."""

    def __init__(self, primary: MsiExtractor, fallback: MsiExtractor) -> None:
        self.primary = primary
        self.fallback = fallback

    def extract(self, msi_path: Path, destination: Path) -> set[Path]:
        try:
            return self.primary.extract(msi_path, destination)
        except MsiExtractionError as exc:
            logger.warning(
                f"Primary MSI extractor failed for {msi_path.name}; "
                f"falling back to msiexec: {exc}"
            )
            return self.fallback.extract(msi_path, destination)


def default_msi_extractor() -> MsiExtractor:
    """Return the production MSI extractor stack."""
    requested = os.environ.get("PORTABLEMSVC_MSI_EXTRACTOR", "").strip().lower()
    if requested in {"", "auto", "pymsi"}:
        return PyMsiExtractor()
    if requested == "msiexec":
        return MsiexecMsiExtractor()
    if requested == "fallback":
        return FallbackMsiExtractor(PyMsiExtractor(), MsiexecMsiExtractor())
    if requested and requested not in {"auto", "fallback"}:
        logger.warning(
            f"Unknown PORTABLEMSVC_MSI_EXTRACTOR={requested!r}; using pymsi"
        )
    return PyMsiExtractor()


@contextmanager
def _prepare_working_directory(base_dir: Path) -> Generator[Path, None, None]:
    """
    Create a temporary working directory under `base_dir`, yield it,
    then delete it on exit (even if errors occur).
    """
    tmp_dir = Path(tempfile.mkdtemp(dir=str(base_dir)))
    logger.info(f"Created working directory: {tmp_dir}")
    try:
        yield tmp_dir
    finally:
        try:
            shutil.rmtree(tmp_dir)
            logger.info(f"Removed working directory: {tmp_dir}")
        except Exception as exc:
            logger.error(f"Failed to remove {tmp_dir}: {exc}")


def _extract_zip_file(
    zip_path: Path, destination: Path, base_path: str = "Contents/"
) -> list[Path]:
    logger.info(f"Extracting ZIP: {zip_path} → {destination}")
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            if base_path and not name.startswith(base_path):
                continue
            rel = Path(name).relative_to(base_path) if base_path else Path(name)
            out_path = _safe_destination_path(destination, rel)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(zf.read(name))
            extracted.append(out_path)
    return extracted


def _extract_msi_file(msi_path: Path, destination: Path) -> set[Path]:
    """
    Extract an MSI file with the original msiexec /a path.

    This is intentionally kept as a direct legacy helper so callers can still
    exercise the old behavior explicitly. The package flow uses
    default_msi_extractor(), which tries pymsi first and falls back to this
    implementation.
    """
    return MsiexecMsiExtractor().extract(msi_path, destination)


def extract_package_files(
    files_map: dict[str, Path],
    output_dir: Path,
    extract_msvc: bool = True,
    extract_sdk: bool = True,
    lockfile: Lockfile | None = None,
    msi_extractor: MsiExtractor | None = None,
) -> dict[str, set[Path]]:
    """
    Extract package files from their cached locations to the output directory.
    Uses a temporary working directory that gets renamed to the final output directory.
    """
    output_dir = output_dir.resolve()
    # Create a temporary working directory next to the output directory
    import uuid

    temp_output_dir = output_dir.with_name(f"{output_dir.name}_{uuid.uuid4().hex[:8]}")
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    msi_extractor = msi_extractor or default_msi_extractor()

    results: dict[str, set[Path]] = {"msvc": set(), "sdk": set()}

    try:
        with _prepare_working_directory(Path(TEMP_DIR)) as workdir:
            # Extract files to the temporary directory
            # 1) Link or copy all cached files into workdir
            for orig_name, cached_path in files_map.items():
                safe_name = _safe_artifact_name(orig_name)
                dst = workdir / safe_name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(cached_path.read_bytes())

            # 2) Extract MSVC (.zip/.vsix) packages
            if extract_msvc:
                logger.info("Starting MSVC (ZIP/VSIX) extraction")
                for ext in ["*.zip", "*.vsix"]:
                    for zf in sorted(workdir.glob(ext)):
                        rel_name = zf.name
                        out_files = _extract_zip_file(zf, temp_output_dir)
                        if lockfile is not None:
                            for out_file in out_files:
                                rel_path = out_file.relative_to(temp_output_dir)
                                lockfile.add_file_extraction(rel_name, rel_path)
                        results["msvc"].update(out_files)

            # 3) Extract SDK (.msi) packages
            if extract_sdk:
                logger.info("Starting SDK (MSI) extraction")
                msi_list = list(workdir.glob("*.msi"))

                # (Optional) gather CAB filenames
                cab_names = {
                    cab
                    for msi in msi_list
                    for cab in _get_msi_cab_files(msi.read_bytes())
                }
                logger.debug(f"Found CABs in MSIs: {cab_names}")

                # Perform the admin‐install
                for msi in msi_list:
                    output_msi = temp_output_dir / msi.name
                    msi_name = msi.name

                    new_files = msi_extractor.extract(msi, temp_output_dir)
                    results["sdk"].add(output_msi)

                    if lockfile is not None:
                        for ef in sorted(new_files):
                            if ef.is_file():
                                rel_path = ef.relative_to(temp_output_dir)
                                lockfile.add_file_extraction(msi_name, rel_path)

                    # Unlink the MSI file from the output directory after extraction
                    if output_msi.exists():
                        logger.info(f"Removing extracted MSI file: {output_msi}")
                        output_msi.unlink()

        # If the output directory already exists, remove it
        if output_dir.exists():
            _validate_replaceable_output_dir(output_dir)
            logger.info(f"Removing existing output directory: {output_dir}")
            shutil.rmtree(output_dir)

        # Rename the temporary directory to the final output directory
        logger.info(
            f"Renaming temporary directory to final output directory: {output_dir}"
        )
        temp_output_dir.rename(output_dir)

    except Exception as e:
        # Clean up the temporary directory on failure
        logger.error(f"Extraction failed: {e}")
        if temp_output_dir.exists():
            logger.info(f"Cleaning up temporary directory: {temp_output_dir}")
            shutil.rmtree(temp_output_dir)
        raise

    return results
