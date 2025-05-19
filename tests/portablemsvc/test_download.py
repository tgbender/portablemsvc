import pytest
import os
from pathlib import Path
import tempfile
import hashlib
import requests

from portablemsvc.download import download_file, download_files
from portablemsvc.config import CACHE_DIR

# Using a small file from python.org
TEST_URL = "https://www.python.org/static/favicon.ico"


def get_file_hash(url):
    """Helper to get the hash of a file from a URL for testing purposes"""
    response = requests.get(url)
    response.raise_for_status()
    return hashlib.sha256(response.content).hexdigest()


@pytest.fixture
def temp_cache_dir():
    """Create a temporary directory for cache testing"""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


def test_download_file_basic():
    """Test that download_file works with a simple file"""
    try:
        # Get the actual hash first
        expected_hash = get_file_hash(TEST_URL)

        # Now download the file
        data, path = download_file(
            url=TEST_URL,
            expected_hash=expected_hash,
            original_name="favicon.ico"
        )

        # Verify the download worked
        assert data is not None
        assert len(data) > 0
        assert path.exists()
        assert path.is_file()

        # Verify the hash matches
        actual_hash = hashlib.sha256(data).hexdigest()
        assert actual_hash == expected_hash
    except Exception as e:
        pytest.fail(f"download_file raised an exception: {e}")


def test_download_file_caching(temp_cache_dir):
    """Test that caching works correctly"""
    # Get the actual hash first
    expected_hash = get_file_hash(TEST_URL)

    # First download should create the cache
    data1, path1 = download_file(
        url=TEST_URL,
        expected_hash=expected_hash,
        original_name="favicon.ico",
        cache_dir=temp_cache_dir
    )

    # Second download should use the cache
    data2, path2 = download_file(
        url=TEST_URL,
        expected_hash=expected_hash,
        original_name="favicon.ico",
        cache_dir=temp_cache_dir
    )

    # Paths should be the same
    assert path1 == path2
    # Data should be the same
    assert data1 == data2


def test_download_files_batch():
    """Test downloading multiple files at once"""
    # Get the actual hash first
    expected_hash = get_file_hash(TEST_URL)

    files_to_download = {
        "file1": {
            "url": TEST_URL,
            "hash": expected_hash,
            "name": "favicon1.ico"
        },
        "file2": {
            "url": TEST_URL,
            "hash": expected_hash,
            "name": "favicon2.ico"
        }
    }

    try:
        # Download the files
        paths = download_files(files_to_download)

        # Check we got both files
        assert len(paths) == 2
        assert "file1" in paths
        assert "file2" in paths
        assert paths["file1"].exists()
        assert paths["file2"].exists()
    except Exception as e:
        pytest.fail(f"download_files raised an exception: {e}")
