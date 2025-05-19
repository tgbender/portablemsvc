import io
import hashlib
import json
import logging
import os
from pathlib import Path
import requests
import time
from typing import Dict, Any, Tuple, List, Optional

try:
    from filelock import FileLock, Timeout
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False
    logger = logging.getLogger(__name__)
    logger.warning("filelock package not found; concurrent downloads may have issues with the hash map")

from .config import CACHE_DIR

# Constants for download operations
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for downloads
HASH_MAP_FILENAME = "hash_to_names.json"
DEFAULT_TIMEOUT = 30  # seconds
LOCK_TIMEOUT = 60  # seconds
LOCK_TTL = 300  # seconds (5 minutes)

logger = logging.getLogger(__name__)

__all__ = ['download_file', 'download_files']

def _load_hash_map(hash_map_file: Path) -> Dict[str, Any]:
    """Load the hash-to-names mapping from disk."""
    if hash_map_file.exists():
        try:
            with open(hash_map_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Corrupted hash map file: {hash_map_file}")
            return {}
    return {}

def _save_hash_map(hash_map_file: Path, hash_to_names: Dict[str, Any]):
    """Save the hash-to-names mapping to disk."""
    try:
        with open(hash_map_file, 'w') as f:
            json.dump(hash_to_names, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save hash map: {e}")

def _save_hash_map_atomic(hash_map_file: Path, hash_to_names: Dict[str, Any]):
    """Save the hash map to file using atomic operations."""
    temp_path = f"{hash_map_file}.tmp"
    try:
        with open(temp_path, 'w') as f:
            json.dump(hash_to_names, f, indent=2)
        os.replace(temp_path, str(hash_map_file))  # Atomic operation
    except IOError as e:
        logger.error(f"Error saving hash map: {e}")
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass

def _stream_download(url: str, original_name: str, max_retries: int = 3, base_wait_time: float = 2.0) -> Tuple[bytes, str]:
    """
    Stream download a file while calculating its hash incrementally.
    Supports retries and resuming downloads.
    
    Args:
        url: URL to download from
        original_name: Original filename for logging
        max_retries: Maximum number of retry attempts
        base_wait_time: Base time for exponential backoff between retries
        
    Returns:
        Tuple of (file_data, actual_hash)
    """
    logger.info(f"Downloading {original_name} from {url}")
    
    data = io.BytesIO()
    hash_obj = hashlib.sha256()
    downloaded = 0
    
    for retry in range(max_retries):
        try:
            headers = {}
            if downloaded > 0:
                headers['Range'] = f'bytes={downloaded}-'
                logger.info(f"Resuming download of {original_name} from byte {downloaded}")
            
            response = requests.get(url, stream=True, timeout=DEFAULT_TIMEOUT, headers=headers)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0)) + downloaded
            
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    data.write(chunk)
                    hash_obj.update(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = downloaded * 100 // total_size
                        logger.debug(f"Downloaded {percent}% of {original_name}")
            
            # If we get here, download completed successfully
            break
            
        except requests.exceptions.RequestException as e:
            if retry < max_retries - 1:
                wait_time = base_wait_time ** retry
                logger.warning(f"Download attempt {retry+1} failed for {original_name}: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)  # Exponential backoff
            else:
                logger.error(f"Download failed after {max_retries} attempts: {e}")
                raise
    
    data_bytes = data.getvalue()
    actual_hash = hash_obj.hexdigest().lower()
    
    return data_bytes, actual_hash

def _download_file(url: str, expected_hash: str, original_name: str, 
                  cache_dir: Path, hash_to_names: Dict[str, Any],
                  max_retries: int = 3, base_wait_time: float = 2.0) -> Tuple[bytes, Path, bool]:
    """
    Download a file, validate its hash, and cache it.
    
    Args:
        url: URL to download from
        expected_hash: Expected SHA256 hash of the file
        original_name: Original filename
        cache_dir: Directory to store cached files
        hash_to_names: Dictionary mapping hashes to original filenames
        
    Returns:
        Tuple of (file_data, cache_path, hash_map_updated)
    """
    # Normalize the hash
    expected_hash = expected_hash.lower()
    
    # Check if we already have this file in cache
    extension = Path(original_name).suffix
    cache_filename = f"{expected_hash}{extension}"
    cache_path = cache_dir / cache_filename
    hash_map_updated = False
    
    if cache_path.exists():
        logger.debug(f"Using cached file for {original_name} ({expected_hash})")
        data = cache_path.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest().lower()
        
        if actual_hash == expected_hash:
            # Update the hash map if this is a new name for this hash
            if expected_hash not in hash_to_names:
                hash_to_names[expected_hash] = [original_name]
                hash_map_updated = True
            elif original_name not in hash_to_names[expected_hash]:
                hash_to_names[expected_hash].append(original_name)
                hash_map_updated = True
            
            return data, cache_path, hash_map_updated
        else:
            logger.warning(f"Hash mismatch for cached file {cache_path}. Expected {expected_hash}, got {actual_hash}")
            # Continue to download as the cached file is invalid
    
    # Download the file and calculate hash as we go
    data_bytes, actual_hash = _stream_download(url, original_name, max_retries, base_wait_time)
    
    # Verify hash
    if actual_hash != expected_hash:
        raise ValueError(f"Hash mismatch for {original_name}. Expected {expected_hash}, got {actual_hash}")
    
    # Save to cache
    with open(cache_path, 'wb') as f:
        f.write(data_bytes)
    
    # Update hash map
    if expected_hash not in hash_to_names:
        hash_to_names[expected_hash] = [original_name]
    elif original_name not in hash_to_names[expected_hash]:
        hash_to_names[expected_hash].append(original_name)
    hash_map_updated = True
    
    return data_bytes, cache_path, hash_map_updated


class DownloadManager:
    def __init__(self, cache_dir: Path = CACHE_DIR, max_retries: int = 3, base_wait_time: float = 2.0):
        self.cache_dir = Path(cache_dir) / "downloads"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hash_map_file = self.cache_dir / HASH_MAP_FILENAME
        self.lock_file = Path(str(self.hash_map_file) + ".lock")
        
        # Set up file locking if available
        self.lock = None
        if HAS_FILELOCK:
            self._cleanup_stale_lock()
            self.lock = FileLock(self.lock_file, timeout=LOCK_TIMEOUT)
            
        # Load hash map (with lock if available)
        if HAS_FILELOCK and self.lock:
            try:
                with self.lock:
                    self.hash_to_names = _load_hash_map(self.hash_map_file)
            except Timeout:
                logger.error(f"Could not acquire lock after {LOCK_TIMEOUT} seconds")
                self.hash_to_names = _load_hash_map(self.hash_map_file)
        else:
            self.hash_to_names = _load_hash_map(self.hash_map_file)
            
        self.hash_map_updated = False
        self.total_download_size = 0
        self.max_retries = max_retries
        self.base_wait_time = base_wait_time
    
    def _cleanup_stale_lock(self) -> None:
        """Check if lock file exists and is stale, remove if necessary."""
        if not self.lock_file.exists():
            return

        try:
            # Get the modification time of the lock file
            mtime = os.path.getmtime(self.lock_file)
            
            # If the lock is older than TTL, remove it
            if time.time() - mtime > LOCK_TTL:
                logger.warning(f"Removing stale lock file: {self.lock_file}")
                os.unlink(self.lock_file)
        except OSError as e:
            logger.warning(f"Error checking lock file: {e}, removing it")
            try:
                os.unlink(self.lock_file)
            except OSError as e:
                logger.error(f"Failed to remove stale lock file: {e}")
    
        
    def download(self, url: str, expected_hash: str, original_name: str) -> Tuple[bytes, Path]:
        data, path, updated = _download_file(
            url, expected_hash, original_name, 
            self.cache_dir, self.hash_to_names,
            self.max_retries, self.base_wait_time
        )
        self.hash_map_updated = self.hash_map_updated or updated
        self.total_download_size += len(data)
        return data, path
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.hash_map_updated:
            if HAS_FILELOCK and self.lock:
                try:
                    with self.lock:
                        # Reload the latest version before updating
                        current_map = _load_hash_map(self.hash_map_file)
                        
                        # Merge our changes
                        for hash_val, names in self.hash_to_names.items():
                            if hash_val in current_map:
                                current_map[hash_val] = list(set(current_map[hash_val] + names))
                            else:
                                current_map[hash_val] = names
                        
                        # Save the updated map
                        _save_hash_map_atomic(self.hash_map_file, current_map)
                except Timeout:
                    logger.error("Could not acquire lock to save hash map updates")
                    _save_hash_map(self.hash_map_file, self.hash_to_names)
            else:
                _save_hash_map(self.hash_map_file, self.hash_to_names)
                
        logger.info(f"Total downloaded: {self.total_download_size / (1024*1024):.2f} MB")
    
    def __del__(self):
        """Ensure resources are properly cleaned up."""
        if HAS_FILELOCK and hasattr(self, 'lock') and self.lock:
            try:
                if self.lock.is_locked:
                    self.lock.release()
            except Exception as e:
                logger.warning(f"Error releasing lock in __del__: {e}")


def download_file(url: str, expected_hash: str, original_name: str, 
                 cache_dir: Path = CACHE_DIR, max_retries: int = 3, base_wait_time: float = 2.0) -> Tuple[bytes, Path]:
    """
    Download a single file with caching and hash verification.
    
    Args:
        url: URL to download from
        expected_hash: Expected SHA256 hash of the file
        original_name: Original filename
        cache_dir: Directory to store cached downloads
        
    Returns:
        Tuple of (file_data, cache_path)
    """
    with DownloadManager(cache_dir, max_retries, base_wait_time) as downloader:
        return downloader.download(url, expected_hash, original_name)


def download_files(files_to_download: Dict[str, Dict[str, str]], 
                  cache_dir: Path = CACHE_DIR, max_retries: int = 3, base_wait_time: float = 2.0) -> Dict[str, Path]:
    """
    Download multiple files with caching and hash verification.
    
    Args:
        files_to_download: Dictionary mapping file IDs to dicts with 'url', 'hash', and 'name' keys
        cache_dir: Directory to store cached downloads
        
    Returns:
        Dictionary mapping file IDs to their local file paths
    """
    downloaded_files = {}
    
    with DownloadManager(cache_dir, max_retries, base_wait_time) as downloader:
        for file_id, file_info in files_to_download.items():
            try:
                _, file_path = downloader.download(
                    file_info['url'], 
                    file_info['hash'], 
                    file_info['name']
                )
                downloaded_files[file_id] = file_path
            except Exception as e:
                logger.error(f"Failed to download {file_info['name']}: {e}")
                raise
    
    return downloaded_files
