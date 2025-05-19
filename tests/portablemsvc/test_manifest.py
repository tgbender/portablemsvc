import pytest
from portablemsvc.manifest import get_vs_manifest

def test_get_vs_manifest_basic():
    """Test that get_vs_manifest runs to completion with default arguments."""
    try:
        manifest = get_vs_manifest()
        assert manifest is not None
        assert isinstance(manifest, dict)
    except Exception as e:
        pytest.fail(f"get_vs_manifest raised an exception: {e}")
