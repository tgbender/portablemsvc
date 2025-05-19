# portablemsvc

**PortableMSVC** is a command-line utility for downloading, extracting, and managing a fully portable Microsoft C/C++ toolchain (MSVC + Windows SDK) on Windows—without requiring a full Visual Studio install.

## Features

- Fetch the latest (or specified) MSVC toolset and Windows SDK from the official Visual Studio release channel  
- Download and extract ZIPs, VSIX, MSI, and embedded CABs via `msiexec` without UI  
- Prune unneeded files (debug symbols, telemetry, etc.) to minimize disk usage  
- Generate `env.json`, `activate.cmd`, and `activate.ps1` for easy environment setup  
- Register/deregister toolchains in **HKCU\Environment**, with automatic PATH backup  
- Maintain multiple portable installs side-by-side via a simple JSON database  
- Plumbum-based CLI with subcommands for listing, installing, and managing toolchains  

## Requirements

- **Windows 10+**  
- **Python 3.12+**  
  - May work on lower versions but not tested
- `msiexec.exe` on PATH (standard on Windows)  
- Required Python packages (install via `pip install .` or `pip install -r requirements.txt`):  
  - `plumbum` (CLI framework)  
  - `winregenv` (registry manipulation)  
  - `filelock` (atomic file/registry locking)  

## Installation

### Using UV (https://github.com/astral-sh/uv) *Recommended*

```bat
uv tool install git+https://github.com/tgbender/portablemsvc@main
```

The UV tool bin directory may need to be added to path

### Alternative: Clone and install locally

```bat
git clone https://github.com/your-org/portablemsvc.git
cd portablemsvc
pip install .
```

This provides the `portablemsvc` console script on your PATH.

## Usage

Run `portablemsvc --help` to view global options and subcommands.

### Subcommands

- `show-versions`  
- `list`  
- `install`  
- `register`  
- `deregister`  

#### Show Available Versions

```bat
portablemsvc show-versions [--channel release|preview] [--no-cache] [--full]
```

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

#### Register / Deregister

- Register the toolchain into your user environment:

    ```bat
    portablemsvc register [--id <install_id>]
    ```

- Deregister (restore original PATH):

    ```bat
    portablemsvc deregister [--id <install_id>]
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

3. **Open a fresh** Command Prompt or PowerShell. Verify:

   ```bat
   where link.exe
   rustup show        # should show x86_64-pc-windows-msvc
   cargo build        # should invoke link.exe from your portable MSVC
   ```

4. **List** all installs:

   ```bat
   portablemsvc list
   ```

5. **Switch** to another install later:

   ```bat
   portablemsvc register --id <other_install_id>
   ```

6. **Cleanup**:

   ```bat
   portablemsvc deregister
   ```

## Contributing

Contributions and issues are welcome!  
- Run `flake8` and `pytest` to ensure style and tests pass  
- Keep PRs focused on a single feature or bugfix  
- Add tests for all new behavior  

## License

This project is MIT-licensed. See [LICENSE](LICENSE) for details.

## Disclaimer

The MSVC and Windows SDK toolchains downloaded by PortableMSVC remain subject to Microsoft's license terms and conditions.  
By using this tool to fetch, install, or manage those toolchains, you agree to comply with all applicable Microsoft licensing requirements.

## Acknowledgments

Huge thanks to [@mmozeiko](https://github.com/mmozeiko) for foundational work on portable MSVC tooling inspiration.

## TODO / Testing 🔍

- Verify that `portablemsvc install --target=x64,arm64,arm`
  - all specified host/target tool directories appear under `VC/Tools/MSVC/.../bin`
  - correct compiler/linker executables (`cl.exe`, `link.exe`) are present per target
- Add integration tests covering the `--target=all` shorthand
- Ensure generated `env.json` and activation scripts include all targets
- Confirm redistribution DLLs (`msdia140.dll`, debug CRTs) deploy properly per target
- Exercise cross‐compilation scenarios (e.g. Host=x64 → Target=arm)
- Automate CI runs on Windows 10 and 11 to catch platform‐specific issues
