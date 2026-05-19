"""Pytest configuration and fixtures."""

from pathlib import Path
from typing import Any

import pytest
from plumbum import local

# Session state for test installs - use dict instead of dynamic module attributes
install_state: dict[str, dict[str, Any] | None] = {
    "normal_test_install": None,
    "lockfile_test_install": None,
}


def pytest_addoption(parser):
    parser.addoption(
        "--run-installs",
        action="store_true",
        default=False,
        help="Run slow MSVC install tests (downloads ~10GB)",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-installs"):
        skip_install = pytest.mark.skip(reason="use --run-installs to run")
        for item in items:
            if "slow_install" in item.keywords or "network_heavy" in item.keywords:
                item.add_marker(skip_install)


@pytest.fixture(scope="session")
def project_root(pytestconfig) -> Path:
    """Return project root directory."""
    return Path(pytestconfig.rootpath)


@pytest.fixture(scope="session")
def portablemsvc_exe(project_root: Path) -> Path:
    """Find the portablemsvc CLI executable."""
    exe = project_root / ".venv" / "Scripts" / "portablemsvc.exe"
    if not exe.exists():
        pytest.skip(f"portablemsvc not found at {exe}")
    return exe


@pytest.fixture(scope="session")
def portablemsvc(portablemsvc_exe):
    """Base plumbum command."""
    return local[str(portablemsvc_exe)]


# ============================================================================
# INSTALL DIRECTORY FIXTURES (session-scoped temp dirs)
# ============================================================================


@pytest.fixture(scope="session")
def normal_install_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped temp directory for normal install."""
    # Use short prefix to avoid MAX_PATH issues with msiexec
    return tmp_path_factory.mktemp("ni")


@pytest.fixture(scope="session")
def lockfile_install_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped temp directory for lockfile install."""
    # Use short prefix to avoid MAX_PATH issues with msiexec
    return tmp_path_factory.mktemp("li")


# ============================================================================
# INSTALL FIXTURES (3 sources)
# ============================================================================


@pytest.fixture(scope="session")
def system_install():
    """Existing system install (latest). Default for most tests."""
    from portablemsvc.install_status import get_installed_versions

    installs = get_installed_versions()
    if not installs:
        pytest.skip("No system MSVC install found. Run 'portablemsvc install' first.")

    latest_id, latest_info = max(
        installs.items(),
        key=lambda x: x[1].get("installed_at", ""),
    )

    return {
        "install_id": latest_id,
        **latest_info,
        "install_path": Path(latest_info["path"]),
        "env": {},  # Uses default locations
    }


@pytest.fixture(scope="session")
def normal_test_install():
    """Session-scoped install from test_install_normal."""
    if install_state["normal_test_install"] is None:
        pytest.skip("Normal test install not created. Run test_install_normal first.")
    return install_state["normal_test_install"]


@pytest.fixture(scope="session")
def lockfile_test_install():
    """Session-scoped install from test_install_from_lockfile."""
    if install_state["lockfile_test_install"] is None:
        pytest.skip("Lockfile test install not created. Run test_install_from_lockfile first.")
    return install_state["lockfile_test_install"]


# ============================================================================
# TEMP LOCATION FIXTURES (isolated per test)
# ============================================================================


@pytest.fixture
def isolated_data_dirs(tmp_path: Path, monkeypatch):
    """
    Isolated data/config/temp dirs for a single test.
    Cache uses default (shared).
    """
    dirs = {
        "data": tmp_path / "data",
        "config": tmp_path / "config",
        "temp": tmp_path / "temp",
    }

    for key, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(f"PORTABLEMSVC_{key.upper()}", str(path))

    return {
        **dirs,
        "tmp": tmp_path,
        "env": {
            "PORTABLEMSVC_DATA": str(dirs["data"]),
            "PORTABLEMSVC_CONFIG": str(dirs["config"]),
            "PORTABLEMSVC_TEMP": str(dirs["temp"]),
        },
    }


@pytest.fixture
def portablemsvc_isolated(portablemsvc_exe, isolated_data_dirs):
    """Plumbum command with isolated data dirs."""
    return local[str(portablemsvc_exe)].with_env(**isolated_data_dirs["env"])


@pytest.fixture
def empty_data_dir(tmp_path: Path):
    """Empty data directory for 'nothing exists' tests."""
    empty = tmp_path / "empty"
    empty.mkdir()
    return empty
