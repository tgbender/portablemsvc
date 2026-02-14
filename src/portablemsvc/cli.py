import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from .config import DEFAULT_HOST, ALL_HOSTS, DEFAULT_TARGET, ALL_TARGETS
from .controller import get_available_versions, install_msvc
from .manifest import get_license_url, get_vs_manifest
from .parse_manifest import parse_vs_manifest
from .install_status import get_installed_versions

# setup a sane default logger
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
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
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


@app.command("list")
def list_installed() -> None:
    """List toolchains recorded in the status database."""
    installs = get_installed_versions()
    if not installs:
        typer.echo("No toolchains recorded.")
        return

    for install_id, rec in installs.items():
        typer.echo(f"ID:           {install_id}")
        typer.echo(f"  Path:       {rec.get('path', 'N/A')}")
        typer.echo(f"  MSVC (manifest): {rec.get('msvc_version', 'N/A')}")
        if rec.get("msvc_internal_version") is not None:
            typer.echo(f"  MSVC (internal): {rec['msvc_internal_version']}")
        typer.echo(f"  SDK:        {rec.get('sdk_version', 'N/A')}")
        typer.echo(f"  Host:       {rec.get('host', 'N/A')}")
        targets = rec.get("targets", [])
        typer.echo(f"  Targets:    {', '.join(targets) if targets else 'N/A'}")
        typer.echo(f"  Installed:  {rec.get('installed_at', 'N/A')}")


@app.command("show-versions")
def show_versions(
    channel: str = typer.Option("release", "--channel", help="Which channel to query (release|preview)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable manifest cache"),
    full: bool = typer.Option(False, "--full", help="Show full MSVC x.y.z.w build versions"),
) -> None:
    """Show available MSVC and Windows SDK versions."""
    cache = not no_cache
    if full:
        # re-parse to get raw full build strings
        vs_manifest = get_vs_manifest(channel=channel, cache=cache)
        parsed = parse_vs_manifest(
            vs_manifest,
            host=DEFAULT_HOST,
            targets=[DEFAULT_TARGET],
        )
        full_versions = sorted(
            ".".join(pid.split(".")[2:6])
            for pid in parsed["msvc_versions"].values()
        )
        typer.echo(f"MSVC full versions: {' '.join(full_versions)}")
        # Also show SDK versions in --full mode
        sdk_versions = sorted(parsed["sdk_versions"].keys())
        typer.echo(f"SDK versions:  {' '.join(sdk_versions)}")
        return

    # default (major.minor) listing
    versions = get_available_versions(channel=channel, cache=cache)
    msvc_versions = sorted(versions["msvc"])
    sdk_versions = sorted(versions["sdk"])
    typer.echo(f"MSVC versions: {' '.join(msvc_versions)}")
    typer.echo(f"SDK versions:  {' '.join(sdk_versions)}")


@app.command("install")
def install(
    msvc_version: Optional[str] = typer.Option(None, "--msvc-version", help="Force specific MSVC version"),
    sdk_version: Optional[str] = typer.Option(None, "--sdk-version", help="Force specific Windows SDK version"),
    channel: str = typer.Option("release", "--channel", help="Which channel to install (release|preview)"),
    accept_license: bool = typer.Option(False, "--accept-license", help="Automatically accept license"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable downloads cache"),
    host: str = typer.Option(DEFAULT_HOST, "--host", help=f"Host arch ({','.join(ALL_HOSTS)})"),
    target: list[str] = typer.Option([], "--target", help=f"Target archs ({','.join(ALL_TARGETS)})"),
    output: Optional[str] = typer.Option(None, "--output", help="Custom installation output directory"),
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
    install_id: Optional[str] = typer.Option(
        None,
        "--id",
        help="ID of the installation to register (omit to pick highest MSVC version)",
    ),
) -> None:
    """Register a toolchain into HKCU\\Environment."""
    from .registry_helpers import register_toolchain

    installs = get_installed_versions()
    if not installs:
        typer.echo("Error: No installations are recorded; nothing to register.", err=True)
        raise typer.Exit(1)

    selected_id = install_id
    if not selected_id:
        # Pick the installation with the highest MSVC version (newest from MS)
        def version_key(item: tuple[str, dict]) -> tuple[int, ...]:
            _, rec = item
            ver = rec.get("msvc_version", "")
            # "14.44.17.14" → (14, 44, 17, 14)
            return tuple(int(p) for p in ver.split(".") if p.isdigit())

        selected_id, _ = max(installs.items(), key=version_key)

    rec = installs.get(selected_id)
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


@app.command("deregister")
def deregister(
    install_id: Optional[str] = typer.Option(
        None,
        "--id",
        help="ID of the installation to deregister (omit for current)",
    ),
) -> None:
    """Deregister a toolchain from HKCU\\Environment."""
    from .registry_helpers import (
        deregister_toolchain,
        _load_state,
        _LOCK_FILE,
        FileLock,
    )

    iid = install_id
    if not iid:
        # pick up the "current" install_id from the same JSON state
        lock = FileLock(str(_LOCK_FILE), timeout=60)
        with lock:
            state = _load_state()
        iid = state.get("current")
        if not iid:
            typer.echo("Error: No current registration found; please specify --id", err=True)
            raise typer.Exit(1)

    deregister_toolchain(iid)
    typer.echo(f"Deregistered toolchain {iid} from HKCU\\Environment.")


if __name__ == "__main__":
    app()
