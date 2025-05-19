
import pytest
from pathlib import Path
from portablemsvc.controller import install_msvc

@pytest.mark.integration
def test_full_msvc_zip_extract(tmp_path):
    # Run the full install pipeline (download → extract → layout)
    result = install_msvc(
        output_dir=tmp_path,
        host="x64",
        targets=["x64"],
        channel="release",
        accept_license=True,
        cache=False
    )

    # confirm the version keys were returned
    assert "msvc_version" in result and "sdk_version" in result

    # Verify that the compiler landed in VC/Tools/MSVC/.../bin/Hostx64/x64/cl.exe
    msvc_root = next((tmp_path / "VC" / "Tools" / "MSVC").iterdir())
    cl_path = msvc_root / "bin" / "Hostx64" / "x64" / "cl.exe"
    assert cl_path.exists(), f"Expected cl.exe at {cl_path}"
