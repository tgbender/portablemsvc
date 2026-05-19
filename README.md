# portablemsvc

**PortableMSVC** is a command-line utility for downloading, extracting, and managing a fully portable Microsoft C/C++ toolchain (MSVC + Windows SDK) on Windows, without requiring a full Visual Studio install.

## Features

- Fetch the latest (or specified) MSVC toolset and Windows SDK from the official Visual Studio release channel
- Download and extract ZIPs, VSIX, MSI, and embedded CABs with pure-Python MSI extraction by default
- Preserve `msiexec` extraction as an explicit fallback path
- Prune unneeded files (debug symbols, telemetry, etc.) to minimize disk usage
- Generate `env.json`, `activate.cmd`, `activate.ps1`, and `activate.xsh` for easy environment setup
- Support for xonsh, PowerShell, and Command Prompt activation
- Register/unregister toolchains in **HKCU\Environment**, with automatic PATH backup
- Maintain multiple portable installs side-by-side via a simple JSON database
- Plumbum-based CLI with subcommands for listing, installing, and managing toolchains

## Requirements

- **Windows 10+**
- **Python 3.10+**
- `msiexec.exe` on PATH only when using `PORTABLEMSVC_MSI_EXTRACTOR=msiexec` or `fallback`

## Installation

### Using UV (https://github.com/astral-sh/uv) _Recommended_

```bat
uv tool install portablemsvc
```

The UV tool bin directory may need to be added to PATH.

### Without installing

```bat
uvx portablemsvc --help
uvx portablemsvc search
```

### Using pip

```bat
python -m pip install portablemsvc
```

### Alternative: Clone and install locally

```bat
git clone https://github.com/tgbender/portablemsvc.git
cd portablemsvc
pip install .
```

This provides the `portablemsvc` console script on your PATH.

## Usage

Run `portablemsvc --help` to view global options and subcommands.

## Microsoft License Terms

PortableMSVC is not affiliated with Microsoft. It downloads MSVC and Windows SDK
packages from Microsoft's official Visual Studio release channel, and those
packages remain subject to Microsoft's license terms.

Before installing a toolchain, review the applicable Microsoft terms for your
use case:

- [Visual Studio license terms directory](https://visualstudio.microsoft.com/license-terms/)
- [Visual Studio licensing guidance](https://www.microsoft.com/licensing/guidance/Visual-Studio)
- [Visual Studio redistribution terms](https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution)

Passing `--accept-license` means you have reviewed and accept the applicable
Microsoft terms for the packages PortableMSVC downloads and installs. Do not
redistribute downloaded packages, cache contents, or extracted toolchains unless
Microsoft's terms allow it.

### Subcommands

- `search` - Search available MSVC and SDK versions
- `list` - List installed toolchains
- `install` - Install a portable toolchain
- `register` - Register toolchain into HKCU\Environment
- `unregister` - Unregister toolchain from HKCU\Environment
- `install-from-lockfile` - Reproducible install from a lockfile
- `get-path` - Get install path for build scripts

#### Search Available Versions

```bat
portablemsvc search [--channel release|preview] [--no-cache] [--full]
```

Search for available MSVC and Windows SDK versions before installing.

#### Install a Portable Toolchain

```bat
portablemsvc install
  [--host x64|x86|arm|arm64]
  [--target x64|x86|arm|arm64|all]
  [--msvc-version <major.minor>]
  [--sdk-version <build>]
  [--channel release|preview]
  [--accept-license]
  [--no-cache]
  [--output <custom_dir>]
```

By default, installs the latest x64 MSVC + SDK under:
`%LOCALAPPDATA%\portable\msvc\msvc-<full_version>_sdk-<build>`

**Environment Variable Overrides:**

| Variable                     | Purpose                                                                  |
| ---------------------------- | ------------------------------------------------------------------------ |
| `PORTABLEMSVC_CACHE`         | Override download cache directory                                        |
| `PORTABLEMSVC_DATA`          | Override install directory                                               |
| `PORTABLEMSVC_CONFIG`        | Override config directory                                                |
| `PORTABLEMSVC_TEMP`          | Override temp directory                                                  |
| `PORTABLEMSVC_MSI_EXTRACTOR` | Select MSI extractor: `auto`/`pymsi` (default), `msiexec`, or `fallback` |

**Example:**

```bat
set PORTABLEMSVC_CACHE=D:\cache\portablemsvc
portablemsvc install
```

#### List Installed Toolchains

```bat
portablemsvc list
```

Displays for each install:

- **ID**
- **Path**
- **MSVC (manifest)** version
- **MSVC (internal)** build folder version
- **SDK** version
- **Host & Targets**
- **Installed at** timestamp

#### Register / Unregister

- Register the toolchain into your user environment:

  ```bat
  portablemsvc register [--id <install_id>]
  ```

- Unregister (restore original PATH):

  ```bat
  portablemsvc unregister [--id <install_id>]
  ```

## Example Workflow

1. **Install** the latest x64 toolchain
   (you will be prompted to review and accept the Microsoft license terms):

   ```bat
   portablemsvc install
   ```

2. **Register** it into your environment:

   ```bat
   portablemsvc register
   ```

3. **Activate** the environment (choose one):

   **Command Prompt:**

   ```bat
   activate.cmd
   ```

   **PowerShell:**

   ```powershell
   .\activate.ps1
   ```

   **xonsh:**

   ```xonsh
   source activate.xsh
   ```

4. **Verify:**

   ```bat
   where link.exe
   rustup show        # should show x86_64-pc-windows-msvc
   cargo build        # should invoke link.exe from your portable MSVC
   ```

5. **List** all installs:

   ```bat
   portablemsvc list
   ```

6. **Switch** to another install later:

   ```bat
   portablemsvc register --id <other_install_id>
   ```

7. **Cleanup**:

   ```bat
   portablemsvc unregister
   ```

## Build Script Integration

The `get-path` command outputs the installation root for use in build scripts:

```bash
# Get path for latest install
MSVC_ROOT=$(portablemsvc get-path)

# Get path by lockfile (matches MSVC/SDK versions)
MSVC_ROOT=$(portablemsvc get-path --lockfile ./portablemsvc.lock)

# Get path by install ID
MSVC_ROOT=$(portablemsvc get-path --id <install_id>)

# Use in build
source "$MSVC_ROOT/activate.cmd"
nmake /f Makefile
```

The `env.json` file contains all environment variables needed for building:

- `CC`, `CXX`, `AR` - Compiler paths
- `PATH`, `INCLUDE`, `LIB` - Search paths
- `TOOL_VERSIONS` - PE file versions of tools

## CI/CD Usage

For reproducible builds in CI, use a lockfile:

```bat
# Install and generate lockfile (commit this to your repo)
portablemsvc install --accept-license --output .\msvc

# In CI, install from the lockfile for bit-for-bit reproducibility
portablemsvc install-from-lockfile portablemsvc.lock --accept-license
```

**GitHub Actions Example:**

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- uses: astral-sh/setup-uv@v5
- run: uv tool install portablemsvc
- run: portablemsvc install-from-lockfile portablemsvc.lock --accept-license
  env:
    PORTABLEMSVC_CACHE: D:\cache\portablemsvc
# Get the path and use it
- run: |
    MSVC_PATH=$(portablemsvc get-path --lockfile portablemsvc.lock)
    "$MSVC_PATH/activate.cmd" && cargo build --release
  shell: bash
```

## Contributing

Contributions and issues are welcome!

- Run `mise run lint` to check code style and types
- Run `mise run test` to run the test suite
- Run `mise run test-most` before changing installer behavior
- Keep PRs focused on a single feature or bugfix
- Add tests for all new behavior

## Publishing

Releases are published from the manual GitHub Actions `release` workflow on the `main` branch.
The publish job uses PyPI trusted publishing through the `pypi` environment, which requires reviewer approval and a 60 second wait timer before upload.

## License

This project is MIT-licensed. See [LICENSE](LICENSE) for details.

## Disclaimer

PortableMSVC is provided as-is. You are responsible for complying with the
licenses for any Microsoft packages you download, install, use, or redistribute.

## Acknowledgments

Huge thanks to [@mmozeiko](https://github.com/mmozeiko) for foundational work on portable MSVC tooling inspiration.

## Testing 🔍

Run the test suite:

```bash
# Fast tests (no downloads)
mise run test

# Most tests including slow_installs but not integration (~20GB downloads)
mise run test-most

# Full tests including integration (~20GB downloads)
mise run test-all
```

Test coverage includes:

- C/C++ compilation with Windows SDK headers
- Static library creation with `lib.exe`
- Tool version capture (PE file metadata)
- Environment variable verification
- Lockfile-based reproducible installs
