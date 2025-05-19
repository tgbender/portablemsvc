#CONFIG.py setup.
from platformdirs import user_config_dir,user_data_dir,user_cache_dir,user_runtime_dir

CONFIG_DIR = user_config_dir('msvc','portable',ensure_exists=True) #store installer settings here
DATA_DIR = user_data_dir('msvc','portable',ensure_exists=True) #store the msvc compiler here
CACHE_DIR = user_cache_dir('msvc','portable',ensure_exists=True) #cache things here
TEMP_DIR = user_runtime_dir('msvc','portable',ensure_exists=True) #put temp things here

DEFAULT_HOST = "x64"
ALL_HOSTS    = "x64 x86 arm64".split()

DEFAULT_TARGET = "x64"
ALL_TARGETS    = "x64 x86 arm arm64".split()

MANIFEST_URL = "https://aka.ms/vs/17/release/channel"
MANIFEST_PREVIEW_URL = "https://aka.ms/vs/17/pre/channel"
RELEASE_CHANNEL_MANIFEST_NAME = "Microsoft.VisualStudio.Manifests.VisualStudio"
PREVIEW_CHANNEL_MANIFEST_NAME = "Microsoft.VisualStudio.Manifests.VisualStudio"

MANIFEST_CACHE_TTL=3600
MANIFEST_REQUEST_TIMEOUT=30

# Package ID patterns
MSVC_PACKAGE_PREFIX = "microsoft.vc."
MSVC_HOST_TARGET_SUFFIX = ".tools.hostx64.targetx64.base"
WIN10_SDK_PREFIX = "microsoft.visualstudio.component.windows10sdk."
WIN11_SDK_PREFIX = "microsoft.visualstudio.component.windows11sdk."