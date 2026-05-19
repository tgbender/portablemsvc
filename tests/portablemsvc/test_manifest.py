import pytest

from portablemsvc.manifest import get_vs_manifest


def test_get_vs_manifest_basic(tmp_path):
    """Test that get_vs_manifest runs to completion with default arguments."""
    try:
        manifest, source_info = get_vs_manifest(cache_dir=tmp_path)
        assert manifest is not None
        assert isinstance(manifest, dict)
        assert source_info is not None
        assert isinstance(source_info, dict)
        assert "channel_manifest_url" in source_info
        assert "vs_manifest_url" in source_info
        assert "vs_manifest_downloaded_hash" in source_info
        assert "vs_manifest_declared_hash" in source_info

        content_cache = tmp_path / f"vs_manifest_{source_info['vs_manifest_downloaded_hash']}.json"
        assert content_cache.exists()
    except Exception as e:
        pytest.fail(f"get_vs_manifest raised an exception: {e}")


def test_get_vs_manifest_reuses_content_addressed_cache(tmp_path):
    manifest, source_info = get_vs_manifest(cache_dir=tmp_path)
    manifest_again, source_info_again = get_vs_manifest(cache_dir=tmp_path)

    assert manifest_again == manifest
    assert (
        source_info_again["vs_manifest_downloaded_hash"]
        == source_info["vs_manifest_downloaded_hash"]
    )
