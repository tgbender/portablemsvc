import json
import uuid
import logging
import datetime
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

try:
    import filelock
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False

from .config import CONFIG_DIR, TEMP_DIR

logger = logging.getLogger(__name__)

STATUS_DB_FILENAME = "installed.json"
LOCK_TIMEOUT = 60  # seconds
LOCK_TTL = 300  # seconds (5 minutes)

def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """
    Atomically write `data` as JSON to `path`:
      1) dump into a temp file alongside `path`
      2) fsync and close it
      3) os.replace() it over the real file
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

def _cleanup_stale_lock(lock_file: Path) -> None:
    """Clean up stale lock file if it exists and is older than LOCK_TTL."""
    if lock_file.exists():
        try:
            # Check if lock file is stale
            mtime = lock_file.stat().st_mtime
            if (datetime.datetime.now().timestamp() - mtime) > LOCK_TTL:
                logger.warning(f"Removing stale lock file: {lock_file}")
                lock_file.unlink()
        except Exception as e:
            logger.error(f"Error checking lock file {lock_file}: {e}")

def get_installed_versions(db_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """
    Get a dictionary of installed MSVC versions from the database.
    
    Args:
        db_path: Path to the database file (default: CONFIG_DIR/installed.json)
        
    Returns:
        Dict with keys as installation IDs and values as installation details
    """
    if db_path is None:
        db_path = Path(CONFIG_DIR) / STATUS_DB_FILENAME
    
    if not db_path.exists():
        return {}
    
    lock_file = Path(str(db_path) + ".lock")
    lock = None
    
    try:
        if HAS_FILELOCK:
            _cleanup_stale_lock(lock_file)
            lock = filelock.FileLock(lock_file, timeout=LOCK_TIMEOUT)
            lock.acquire()
        
        return json.loads(db_path.read_text())
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read installation database at {db_path}: {e}")
        return {}
    finally:
        if lock and lock.is_locked:
            lock.release()

def save_installed_version(
    output_dir: Path,
    manifest_msvc_version: str,
    internal_msvc_version: str,
    sdk_version: str,
    host: str,
    targets: List[str],
    db_path: Optional[Path] = None
) -> str:
    """
    Save installation details to the database.
    
    Args:
        output_dir: Path to the installation directory
        msvc_version: MSVC version
        sdk_version: SDK version
        host: Host architecture
        targets: List of target architectures
        db_path: Path to the database file (default: CONFIG_DIR/installed.json)
        
    Returns:
        Installation ID
    """
    if db_path is None:
        db_path = Path(CONFIG_DIR) / STATUS_DB_FILENAME

    # If this exact toolchain is already recorded, skip writing a new entry
    existing_id = is_version_installed(
        manifest_msvc_version, sdk_version, host, targets, db_path
    )
    if existing_id:
        logger.info(f"Installation already recorded as {existing_id}, skipping write.")
        return existing_id

    # Generate a unique ID for this installation
    install_id = str(uuid.uuid4())
    
    lock_file = Path(str(db_path) + ".lock")
    lock = None
    
    try:
        if HAS_FILELOCK:
            _cleanup_stale_lock(lock_file)
            lock = filelock.FileLock(lock_file, timeout=LOCK_TIMEOUT)
            lock.acquire()
        
        # Get existing installations
        installations = {}
        if db_path.exists():
            try:
                installations = json.loads(db_path.read_text())
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Failed to read existing database, creating new one")
        
        # Add new installation
        installations[install_id] = {
            "path": str(output_dir.resolve()),
            "msvc_version": manifest_msvc_version,
            "msvc_internal_version": internal_msvc_version,
            "sdk_version": sdk_version,
            "host": host,
            "targets": targets,
            "installed_at": datetime.datetime.now().isoformat()
        }
        
        # Atomically persist the updated database
        _atomic_write_json(db_path, installations)
        
        return install_id
    finally:
        if lock and lock.is_locked:
            lock.release()

def is_version_installed(
    msvc_version: Optional[str],
    sdk_version: Optional[str],
    host: str,
    targets: List[str],
    db_path: Optional[Path] = None
) -> Optional[str]:
    """
    Check if a specific version is already installed.
    
    Args:
        msvc_version: MSVC version (None for any)
        sdk_version: SDK version (None for any)
        host: Host architecture
        targets: List of target architectures
        db_path: Path to the database file (default: CONFIG_DIR/installed.json)
        
    Returns:
        Installation ID if installed, None otherwise
    """
    installations = get_installed_versions(db_path)
    
    for install_id, details in installations.items():
        # Check if path exists
        if not Path(details["path"]).exists():
            continue
            
        # Check version match
        if msvc_version is not None and details["msvc_version"] != msvc_version:
            continue
            
        if sdk_version is not None and details["sdk_version"] != sdk_version:
            continue
            
        # Check host match
        if details["host"] != host:
            continue
            
        # Check targets match (all requested targets must be in installed targets)
        if not set(targets).issubset(set(details["targets"])):
            continue
            
        # All checks passed
        return install_id
    
    return None

def remove_installation(
    install_id: str,
    delete_files: bool = False,
    db_path: Optional[Path] = None
) -> bool:
    """
    Remove an installation from the database and optionally delete files.
    
    Args:
        install_id: Installation ID to remove
        delete_files: Whether to delete the installation files
        db_path: Path to the database file (default: CONFIG_DIR/installed.json)
        
    Returns:
        True if successful, False otherwise
    """
    if db_path is None:
        db_path = Path(CONFIG_DIR) / STATUS_DB_FILENAME
    
    lock_file = Path(str(db_path) + ".lock")
    lock = None
    
    try:
        if HAS_FILELOCK:
            _cleanup_stale_lock(lock_file)
            lock = filelock.FileLock(lock_file, timeout=LOCK_TIMEOUT)
            lock.acquire()
        
        # Get existing installations
        if not db_path.exists():
            return False
            
        try:
            installations = json.loads(db_path.read_text())
        except (json.JSONDecodeError, IOError):
            logger.error(f"Failed to read installation database")
            return False
        
        # Check if installation exists
        if install_id not in installations:
            logger.warning(f"Installation {install_id} not found in database")
            return False
        
        # Delete files if requested
        if delete_files:
            path = Path(installations[install_id]["path"])
            if path.exists():
                try:
                    shutil.rmtree(path)
                    logger.info(f"Deleted installation files at {path}")
                except Exception as e:
                    logger.error(f"Failed to delete installation files at {path}: {e}")
                    return False
        
        # Remove from database
        del installations[install_id]
        
        # Atomically persist the updated database
        _atomic_write_json(db_path, installations)
        
        return True
    finally:
        if lock and lock.is_locked:
            lock.release()
