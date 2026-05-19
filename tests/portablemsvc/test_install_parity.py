import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _hash_tree(root: Path) -> dict[str, str]:
    generated_metadata = {
        "activate.cmd",
        "activate.ps1",
        "activate.xsh",
        "env.json",
        "portablemsvc.lock",
    }
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.relative_to(root).as_posix() not in generated_metadata
    }


@pytest.mark.slow_install
def test_pymsi_install_matches_msiexec_install_byte_for_byte(
    portablemsvc_exe: Path,
    tmp_path: Path,
):
    def run_install(extractor: str) -> dict[str, str]:
        root = tmp_path / extractor
        output_dir = root / "toolchain"
        if output_dir.exists():
            shutil.rmtree(output_dir)

        env = os.environ.copy()
        env.update(
            {
                "PORTABLEMSVC_CONFIG": str(root / "config"),
                "PORTABLEMSVC_DATA": str(root / "data"),
                "PORTABLEMSVC_TEMP": str(root / "temp"),
                "PORTABLEMSVC_MSI_EXTRACTOR": extractor,
            }
        )
        for key in ("PORTABLEMSVC_CONFIG", "PORTABLEMSVC_DATA", "PORTABLEMSVC_TEMP"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [
                str(portablemsvc_exe),
                "install",
                "--accept-license",
                "--target",
                "x64",
                "--output",
                str(output_dir),
            ],
            env=env,
            check=True,
        )

        return _hash_tree(output_dir)

    pymsi_tree = run_install("pymsi")
    msiexec_tree = run_install("msiexec")

    assert pymsi_tree == msiexec_tree
