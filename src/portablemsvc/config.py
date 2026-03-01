# CONFIG.py setup.
import os
from pathlib import Path
from platformdirs import (
    user_config_dir,
    user_data_dir,
    user_cache_dir,
    user_runtime_dir,
)

# Directory configuration with environment variable overrides
# Fall back to platformdirs if env vars are not set
CONFIG_DIR = Path(
    os.environ.get("PORTABLEMSVC_CONFIG")
    or user_config_dir("msvc", "portable", ensure_exists=True)
)  # store installer settings here
DATA_DIR = Path(
    os.environ.get("PORTABLEMSVC_DATA")
    or user_data_dir("msvc", "portable", ensure_exists=True)
)  # store the msvc compiler here
CACHE_DIR = Path(
    os.environ.get("PORTABLEMSVC_CACHE")
    or user_cache_dir("msvc", "portable", ensure_exists=True)
)  # cache things here
TEMP_DIR = Path(
    os.environ.get("PORTABLEMSVC_TEMP")
    or user_runtime_dir("msvc", "portable", ensure_exists=True)
)  # put temp things here

DEFAULT_HOST = "x64"
ALL_HOSTS = "x64 x86 arm64".split()

DEFAULT_TARGET = "x64"
ALL_TARGETS = "x64 x86 arm arm64".split()

MANIFEST_URL = "https://aka.ms/vs/17/release/channel"
MANIFEST_PREVIEW_URL = "https://aka.ms/vs/17/pre/channel"
RELEASE_CHANNEL_MANIFEST_NAME = "Microsoft.VisualStudio.Manifests.VisualStudio"
PREVIEW_CHANNEL_MANIFEST_NAME = "Microsoft.VisualStudio.Manifests.VisualStudio"

MANIFEST_CACHE_TTL = 3600
MANIFEST_REQUEST_TIMEOUT = 30

# Package ID patterns
MSVC_PACKAGE_PREFIX = "microsoft.vc."
MSVC_HOST_TARGET_SUFFIX = ".tools.hostx64.targetx64.base"
WIN10_SDK_PREFIX = "microsoft.visualstudio.component.windows10sdk."
WIN11_SDK_PREFIX = "microsoft.visualstudio.component.windows11sdk."


def first(items, cond=lambda x: True):
    """Find the first item that matches the condition."""
    return next((item for item in items if cond(item)), None)


# Version type aliases for clarity and type safety
# These help prevent mixing up different version formats
MsvcManifestVersion = str  # Short form from manifest: "14.44"
MsvcFullVersion = str  # Full build version: "14.44.17.14"
SdkManifestVersion = str  # Short form from manifest: "26100"
SdkFullVersion = str  # Full SDK version: "10.0.26100.0"
