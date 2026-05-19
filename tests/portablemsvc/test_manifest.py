import pytest

from portablemsvc.manifest import get_vs_manifest


def test_get_vs_manifest_basic():
    """Test that get_vs_manifest runs to completion with default arguments."""
    try:
        manifest, source_info = get_vs_manifest()
        assert manifest is not None
        assert isinstance(manifest, dict)
        assert source_info is not None
        assert isinstance(source_info, dict)
        assert "channel_manifest_url" in source_info
        assert "vs_manifest_url" in source_info
    except Exception as e:
        pytest.fail(f"get_vs_manifest raised an exception: {e}")
