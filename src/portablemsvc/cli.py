import logging
import os
import sys
from pathlib import Path

import typer

from .config import ALL_HOSTS, ALL_TARGETS, DEFAULT_HOST, DEFAULT_TARGET
from .controller import get_available_versions, install_msvc
from .install_status import get_installed_versions
from .manifest import get_license_url, get_vs_manifest
from .parse_manifest import parse_vs_manifest

# setup a sane default logger
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger(__name__)

app = typer.Typer(
    name="portablemsvc",
    help="portable-msvc: manage, list and install MSVC toolchains.",
)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging"),
) -> None:
    """portable-msvc: manage, list and install MSVC toolchains."""
    if not sys.platform.startswith("win32"):
        typer.echo("Error: portablemsvc only works on Windows", err=True)
        raise typer.Exit(1)
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


@app.command("list")
def list_installed(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List toolchains recorded in the status database."""
    if json_output:
        import json
        import logging

        # Suppress filelock logging to keep stdout clean for JSON parsing
        logging.getLogger("filelock").setLevel(logging.WARNING)
        installs = get_installed_versions()
        typer.echo(json.dumps(installs, indent=2))
        return

    installs = get_installed_versions()

    if not installs:
        typer.echo("No toolchains recorded.")
        return

    for install_id, rec in installs.items():
        typer.echo(f"ID:           {install_id}")
        typer.echo(f"  Path:       {rec.get('path', 'N/A')}")
        typer.echo(f"  MSVC Toolset: {rec.get('msvc_toolset_version', 'N/A')}")
        typer.echo(f"  MSVC Package: {rec.get('msvc_package_version', 'N/A')}")
        typer.echo(f"  MSVC VCTools: {rec.get('msvc_vctools_version', 'N/A')}")
        typer.echo(f"  SDK Build:    {rec.get('sdk_build_number', 'N/A')}")
        typer.echo(f"  SDK Version:  {rec.get('sdk_version', 'N/A')}")
        typer.echo(f"  Host:       {rec.get('host', 'N/A')}")
        targets = rec.get("targets", [])
        typer.echo(f"  Targets:    {', '.join(targets) if targets else 'N/A'}")
        typer.echo(f"  Installed:  {rec.get('installed_at', 'N/A')}")


@app.command("search")
def search(
    channel: str = typer.Option(
        "release", "--channel", help="Which channel to query (release|preview)"
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable manifest cache"),
    full: bool = typer.Option(
        False, "--full", help="Show full MSVC x.y.z.w build versions"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search available MSVC and Windows SDK versions."""
    cache = not no_cache

    if full:
        # re-parse to get raw full build strings
        vs_manifest, _ = get_vs_manifest(channel=channel, cache=cache)
        parsed = parse_vs_manifest(
            vs_manifest,
            host=DEFAULT_HOST,
            targets=[DEFAULT_TARGET],
        )
        full_versions = sorted(
            ".".join(pid.split(".")[2:6]) for pid in parsed["msvc_versions"].values()
        )
        sdk_versions = sorted(parsed["sdk_versions"].keys())

        if json_output:
            import json

            typer.echo(
                json.dumps(
                    {
                        "msvc": full_versions,
                        "sdk": sdk_versions,
                    },
                    indent=2,
                )
            )
            return

        typer.echo(f"MSVC full versions: {' '.join(full_versions)}")
        typer.echo(f"SDK versions:  {' '.join(sdk_versions)}")
        return

    # default (major.minor) listing
    versions = get_available_versions(channel=channel, cache=cache)
    msvc_versions = sorted(versions["msvc"])
    sdk_versions = sorted(versions["sdk"])

    if json_output:
        import json

        typer.echo(json.dumps(versions, indent=2))
        return

    typer.echo(f"MSVC versions: {' '.join(msvc_versions)}")
    typer.echo(f"SDK versions:  {' '.join(sdk_versions)}")


@app.command("install")
def install(
    msvc_version: str | None = typer.Option(
        None, "--msvc-version", help="Force specific MSVC version"
    ),
    sdk_version: str | None = typer.Option(
        None, "--sdk-version", help="Force specific Windows SDK version"
    ),
    channel: str = typer.Option(
        "release", "--channel", help="Which channel to install (release|preview)"
    ),
    accept_license: bool = typer.Option(
        False, "--accept-license", help="Automatically accept license"
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable downloads cache"),
    host: str = typer.Option(
        DEFAULT_HOST, "--host", help=f"Host arch ({','.join(ALL_HOSTS)})"
    ),
    target: list[str] = typer.Option(
        [], "--target", help=f"Target archs ({','.join(ALL_TARGETS)})"
    ),
    output: str | None = typer.Option(
        None, "--output", help="Custom installation output directory"
    ),
) -> None:
    """Install MSVC & Windows SDK into a portable layout."""
    # compute flags
    cache = not no_cache

    # validate host & normalize targets (default = host, support "all")
    if host not in ALL_HOSTS:
        typer.echo(f"Error: Unknown host architecture: {host}", err=True)
        raise typer.Exit(1)
    raw_targets: list[str] = target if target else [host]
    # if user asked for "all" (case-insensitive), expand to every target
    targets: list[str]
    if any(rt.lower() == "all" for rt in raw_targets):
        targets = list(ALL_TARGETS)
    else:
        targets = []
        for rt in raw_targets:
            t = rt.lower()
            if t not in ALL_TARGETS:
                typer.echo(f"Error: Unknown target architecture: {rt}", err=True)
                raise typer.Exit(1)
            targets.append(t)

    # ——— LICENSE ACCEPTANCE ———
    lic_url = get_license_url(channel=channel, cache=cache)
    typer.echo(f"License text available at:\n  {lic_url}\n")
    accepted = accept_license
    if not accepted:
        ans = typer.prompt("Do you accept the license terms? [y/N]", default="N")
        accepted = ans.strip().lower() in ("y", "yes")
    if not accepted:
        typer.echo("Error: License not accepted. Aborting.", err=True)
        raise typer.Exit(1)

    # ——— DELEGATE TO CONTROLLER ———
    install_msvc(
        output_dir=Path(output) if output else None,
        host=host,
        targets=targets,
        msvc_version=msvc_version,
        sdk_version=sdk_version,
        channel=channel,
        cache=cache,
        accept_license=accepted,
    )


@app.command("register")
def register(
    install_id: str | None = typer.Option(
        None,
        "--id",
        help="ID of the installation to register (omit to pick highest MSVC version)",
    ),
) -> None:
    """Register a toolchain into HKCU\\Environment."""
    from .registry_helpers import register_toolchain

    installs = get_installed_versions()
    if not installs:
        typer.echo(
            "Error: No installations are recorded; nothing to register.", err=True
        )
        raise typer.Exit(1)

    selected_id = install_id
    if not selected_id:
        # Pick the installation with the highest MSVC version (newest from MS)
        def version_key(item: tuple[str, dict]) -> tuple[int, ...]:
            _, rec = item
            ver = rec.get("msvc_toolset_version", "")
            return tuple(int(p) for p in ver.split(".") if p.isdigit())

        selected_id, _ = max(installs.items(), key=version_key)

    rec: dict | None = installs.get(selected_id)
    if not rec:
        typer.echo(f"Error: No installation with ID '{selected_id}'", err=True)
        raise typer.Exit(1)
    # the status DB records the root path under "path"
    install_root = rec.get("path")
    if not install_root:
        typer.echo(f"Error: No install path recorded for ID '{selected_id}'", err=True)
        raise typer.Exit(1)
    register_toolchain(selected_id, Path(install_root))
    typer.echo(f"Registered toolchain {selected_id} into HKCU\\Environment.")


@app.command("unregister")
def unregister(
    install_id: str | None = typer.Option(
        None,
        "--id",
        help="ID of the installation to unregister (omit for current)",
    ),
) -> None:
    """Unregister a toolchain from HKCU\\Environment."""
    from .registry_helpers import (
        _LOCK_FILE,
        FileLock,
        _load_state,
        unregister_toolchain,
    )

    iid = install_id
    if not iid:
        # pick up the "current" install_id from the same JSON state
        lock = FileLock(str(_LOCK_FILE), timeout=60)
        with lock:
            state = _load_state()
        iid = state.get("current")
        if not iid:
            typer.echo(
                "Error: No current registration found; please specify --id", err=True
            )
            raise typer.Exit(1)

    unregister_toolchain(iid)
    typer.echo(f"Unregistered toolchain {iid} from HKCU\\Environment.")


@app.command("install-from-lockfile")
def install_from_lockfile(
    lockfile: str = typer.Argument(..., help="Path to portablemsvc.lock file"),
    accept_license: bool = typer.Option(
        False, "--accept-license", help="Automatically accept license"
    ),
    output: str | None = typer.Option(
        None, "--output", help="Custom installation output directory"
    ),
) -> None:
    """Install MSVC from a lockfile for reproducible builds."""
    from .controller import install_from_lockfile as install_from_lockfile_impl

    lic_url = "https://visualstudio.microsoft.com/license-terms/vs/"
    typer.echo(f"License text available at:\n  {lic_url}\n")
    accepted = accept_license
    if not accepted:
        ans = typer.prompt("Do you accept the license terms? [y/N]", default="N")
        accepted = ans.strip().lower() in ("y", "yes")
    if not accepted:
        typer.echo("Error: License not accepted. Aborting.", err=True)
        raise typer.Exit(1)

    result = install_from_lockfile_impl(
        lockfile_path=Path(lockfile),
        output_dir=Path(output) if output else None,
        accept_license=accepted,
    )
    typer.echo(f"Installed to: {result['path']}")
    typer.echo(f"Install ID: {result['install_id']}")


@app.command("get-path")
def get_path(
    install_id: str | None = typer.Option(
        None, "--id", help="Installation ID (omit for latest)"
    ),
    lockfile: str | None = typer.Option(
        None, "--lockfile", help="Path to portablemsvc.lock to find matching install"
    ),
) -> None:
    """Output the installation root path for use in build scripts."""
    import logging

    from .install_status import get_installed_versions
    from .lockfile import Lockfile

    # Suppress filelock logging to keep stdout clean
    logging.getLogger("filelock").setLevel(logging.WARNING)

    if lockfile:
        # Read lockfile to find matching installed version
        lf = Lockfile.load(Path(lockfile))
        lf_data = lf.to_dict()
        resolved = lf_data.get("resolved", {})
        msvc_ver = resolved.get("msvc", {}).get("package_version")
        sdk_ver = resolved.get("sdk", {}).get("build_number")

        installs = get_installed_versions()
        for _iid, install_rec in installs.items():
            if (
                install_rec.get("msvc_package_version") == msvc_ver
                and install_rec.get("sdk_build_number") == sdk_ver
            ):
                typer.echo(install_rec["path"])
                return

        typer.echo(
            f"Error: No install found for lockfile (MSVC {msvc_ver}, SDK {sdk_ver})",
            err=True,
        )
        raise typer.Exit(1)

    # Otherwise look up by ID or latest
    installs = get_installed_versions()
    if not installs:
        typer.echo("Error: No installations found", err=True)
        raise typer.Exit(1)

    selected_id: str
    if install_id:
        selected_id = install_id
    else:
        # Pick the installation with the highest MSVC version (newest)
        def version_key(item: tuple[str, dict]) -> tuple[int, ...]:
            _, install_rec = item
            ver = install_rec.get("msvc_toolset_version", "")
            return tuple(int(p) for p in ver.split(".") if p.isdigit())

        selected_id, _ = max(installs.items(), key=version_key)

    rec: dict | None = installs.get(selected_id)
    if not rec:
        typer.echo(f"Error: No installation with ID '{selected_id}'", err=True)
        raise typer.Exit(1)

    install_root = rec.get("path")
    if not install_root:
        typer.echo(f"Error: No install path recorded for ID '{selected_id}'", err=True)
        raise typer.Exit(1)

    # Output just the path for scripting
    typer.echo(install_root)


@app.command("get-activate")
def get_activate(
    install_id: str | None = typer.Option(
        None, "--id", help="Installation ID (omit for latest)"
    ),
    lockfile: str | None = typer.Option(
        None, "--lockfile", help="Path to portablemsvc.lock to find matching install"
    ),
    shell: str = typer.Option(
        "auto", "--shell", help="Shell type (auto|cmd|powershell|ps|xonsh)"
    ),
) -> None:
    """Output the activation command for the specified toolchain."""
    import logging

    from .install_status import get_installed_versions
    from .lockfile import Lockfile

    # Suppress filelock logging to keep stdout clean
    logging.getLogger("filelock").setLevel(logging.WARNING)

    def _resolve_install() -> tuple[str, dict]:
        """Resolve to (install_id, install_rec) tuple."""
        if lockfile:
            lf = Lockfile.load(Path(lockfile))
            lf_data = lf.to_dict()
            resolved = lf_data.get("resolved", {})
            msvc_ver = resolved.get("msvc", {}).get("package_version")
            sdk_ver = resolved.get("sdk", {}).get("build_number")

            installs = get_installed_versions()
            for iid, rec in installs.items():
                if (
                    rec.get("msvc_package_version") == msvc_ver
                    and rec.get("sdk_build_number") == sdk_ver
                ):
                    return iid, rec

            typer.echo(
                f"Error: No install found for lockfile (MSVC {msvc_ver}, SDK {sdk_ver})",
                err=True,
            )
            raise typer.Exit(1)

        installs = get_installed_versions()
        if not installs:
            typer.echo("Error: No installations found", err=True)
            raise typer.Exit(1)

        if install_id:
            candidate = installs.get(install_id)
            if candidate is None:
                typer.echo(f"Error: No installation with ID '{install_id}'", err=True)
                raise typer.Exit(1)
            return install_id, candidate

        # Pick the installation with the highest MSVC version (newest)
        def version_key(item: tuple[str, dict]) -> tuple[int, ...]:
            _, r = item
            ver = r.get("msvc_toolset_version", "")
            return tuple(int(p) for p in ver.split(".") if p.isdigit())

        sid, srec = max(installs.items(), key=version_key)
        return sid, srec

    def _detect_shell() -> str:
        """Auto-detect the current shell."""
        # PowerShell detection
        if os.getenv("PSVERSIONTABLE") or os.getenv("PSMODULEPATH"):
            return "powershell"
        # Check parent process name
        try:
            import psutil

            parent = psutil.Process().parent()
            if parent:
                parent_name = parent.name().lower()
                if "pwsh" in parent_name or "powershell" in parent_name:
                    return "powershell"
                if "xonsh" in parent_name:
                    return "xonsh"
        except (ImportError, Exception):
            pass
        # Default to cmd on Windows
        return "cmd"

    def _get_activate_command(install_root: Path, shell_type: str) -> str:
        """Generate the activation command for the given shell."""
        if shell_type in ("powershell", "ps"):
            return f'& "{install_root}\\activate.ps1"'
        elif shell_type == "xonsh":
            # Just the path - xonsh uses: source $(cmd).strip()
            return f"{install_root}\\activate.xsh"
        else:  # cmd
            return f'"{install_root}\\activate.cmd"'

    # Resolve install
    _, rec = _resolve_install()
    install_root = rec.get("path")
    if not install_root:
        typer.echo("Error: No install path recorded", err=True)
        raise typer.Exit(1)

    # Determine shell
    selected_shell = shell.lower()
    if selected_shell == "auto":
        selected_shell = _detect_shell()

    # Output the activation command
    cmd = _get_activate_command(Path(install_root), selected_shell)
    typer.echo(cmd)


if __name__ == "__main__":
    app()
