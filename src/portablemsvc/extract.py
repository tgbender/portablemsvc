import os
import shutil
import zipfile
import tempfile
import logging

from .parse_msi import extract_cab_names as _get_msi_cab_files

from pathlib import Path
from typing import Dict, List, Set
from contextlib import contextmanager

from plumbum import local

from .config import TEMP_DIR

logger = logging.getLogger(__name__)



@contextmanager
def _prepare_working_directory(base_dir: Path) -> Path:
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


def _extract_zip_file(zip_path: Path, destination: Path, base_path: str = "Contents/") -> List[Path]:
    logger.info(f"Extracting ZIP: {zip_path} → {destination}")
    extracted = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if base_path and not name.startswith(base_path):
                continue
            rel = Path(name).relative_to(base_path) if base_path else Path(name)
            out_path = destination / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(zf.read(name))
            extracted.append(out_path)
    return extracted


def _extract_msi_file(msi_path: Path, destination: Path) -> bool:
    logger.info(f"Extracting MSI: {msi_path} → {destination}")
    try:
        msiexec = local["msiexec.exe"]
        msiexec["/a", str(msi_path), "/quiet", "/qn", f"TARGETDIR={destination.resolve()}"]()
        return True
    except Exception as exc:
        logger.error(f"MSI extraction failed for {msi_path}: {exc}")
        return False




def extract_package_files(
    files_map: Dict[str, Path],
    output_dir: Path,
    extract_msvc: bool = True,
    extract_sdk: bool = True
) -> Dict[str, Set[Path]]:
    """
    Extract package files from their cached locations to the output directory.
    Uses a temporary working directory that gets renamed to the final output directory.
    """
    # Create a temporary working directory next to the output directory
    import uuid
    temp_output_dir = output_dir.with_name(f"{output_dir.name}_temp_{uuid.uuid4().hex}")
    temp_output_dir.mkdir(parents=True, exist_ok=True)
    
    results = {'msvc': set(), 'sdk': set()}

    try:
        with _prepare_working_directory(Path(TEMP_DIR)) as workdir:
            # Extract files to the temporary directory
            # 1) Link or copy all cached files into workdir
            for orig_name, cached_path in files_map.items():
                dst = workdir / orig_name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(cached_path.read_bytes())

            # 2) Extract MSVC (.zip/.vsix) packages
            if extract_msvc:
                logger.info("Starting MSVC (ZIP/VSIX) extraction")
                for ext in ["*.zip", "*.vsix"]:
                    for zf in workdir.glob(ext):
                        out_files = _extract_zip_file(zf, temp_output_dir)
                        results['msvc'].update(out_files)

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
                    if _extract_msi_file(msi, temp_output_dir):
                        results['sdk'].add(output_msi)
                        # Unlink the MSI file from the output directory after extraction
                        if output_msi.exists():
                            logger.info(f"Removing extracted MSI file: {output_msi}")
                            output_msi.unlink()
        
        # If the output directory already exists, remove it
        if output_dir.exists():
            logger.info(f"Removing existing output directory: {output_dir}")
            shutil.rmtree(output_dir)
        
        # Rename the temporary directory to the final output directory
        logger.info(f"Renaming temporary directory to final output directory: {output_dir}")
        temp_output_dir.rename(output_dir)
        
    except Exception as e:
        # Clean up the temporary directory on failure
        logger.error(f"Extraction failed: {e}")
        if temp_output_dir.exists():
            logger.info(f"Cleaning up temporary directory: {temp_output_dir}")
            shutil.rmtree(temp_output_dir)
        raise

    return results



def extract_package_files_print(
    files_map: Dict[str, Path],
    output_dir: Path,
    extract_msvc: bool = True,
    extract_sdk: bool = True
) -> Dict[str, Set[Path]]:
    """
    Extract package files from their cached locations to the output directory.

    Returns a dict with two keys:
      - 'msvc': set of extracted paths from .zip packages
      - 'sdk':  set of extracted paths (the .msi files that were expanded)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {'msvc': set(), 'sdk': set()}

    with _prepare_working_directory(Path(TEMP_DIR)) as workdir:
        # 1) Link or copy all cached files into workdir
        for orig_name, cached_path in files_map.items():
            dst = workdir / orig_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(cached_path.read_bytes())
            #try:
            #    os.link(cached_path, dst)
            #except OSError:
            #    dst.write_bytes(cached_path.read_bytes())

            print(dst)
