import pytest
from portablemsvc.manifest import get_vs_manifest
from portablemsvc.parse_manifest import parse_vs_manifest


def test_parse_vs_manifest_basic():
    """Test that parse_vs_manifest runs to completion with default arguments."""
    try:
        # First get the manifest (now returns tuple of manifest and source info)
        manifest, _ = get_vs_manifest()

        # Then parse it with some basic parameters
        result = parse_vs_manifest(manifest, host="x64", targets=["x64"])

        # Check that we got a valid result
        assert result is not None
        assert isinstance(result, dict)
        assert "msvc_versions" in result
        assert "sdk_versions" in result
        
        # Updated key names for selected versions
        assert "selected_msvc" in result
        assert "toolset_version" in result["selected_msvc"]
        assert "package_version" in result["selected_msvc"]
        assert "package_id" in result["selected_msvc"]
        
        assert "selected_sdk" in result
        assert "build_number" in result["selected_sdk"]
        assert "version" in result["selected_sdk"]
        assert "package_id" in result["selected_sdk"]
        
        assert "msvc_packages" in result
        assert "sdk_packages" in result
    except Exception as e:
        pytest.fail(f"parse_vs_manifest raised an exception: {e}")
