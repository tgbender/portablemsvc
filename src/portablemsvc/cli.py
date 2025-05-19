from plumbum.cli import Application, SwitchAttr, Flag
import logging, sys
from pathlib import Path

from .config      import DEFAULT_HOST, ALL_HOSTS, DEFAULT_TARGET, ALL_TARGETS
from .controller  import get_available_versions, install_msvc
from .manifest    import get_license_url, get_vs_manifest
from .parse_manifest import parse_vs_manifest
from .install_status   import get_installed_versions

# setup a sane default logger
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


class PortableMSVCApp(Application):
    """portable-msvc: manage, list and install MSVC toolchains."""
    PROG_NAME = "portablemsvc"
    VERSION   = "0.1.0"

    # global flags
    verbose = Flag("-v", "--verbose", help="Enable debug logging")



@PortableMSVCApp.subcommand("list")
class ListInstalled(Application):
    """List toolchains recorded in the status database."""
    PROG_NAME = "list"

    def main(self):
        installs = get_installed_versions()
        if not installs:
            print("No toolchains recorded.")
            return

        for install_id, rec in installs.items():
            print(f"ID:           {install_id}")
            print(f"  Path:       {rec.get('path', 'N/A')}")
            print(f"  MSVC (manifest): {rec.get('msvc_version', 'N/A')}")
            if rec.get("msvc_internal_version") is not None:
                print(f"  MSVC (internal): {rec['msvc_internal_version']}")
            print(f"  SDK:        {rec.get('sdk_version', 'N/A')}")
            print(f"  Host:       {rec.get('host', 'N/A')}")
            targets = rec.get('targets', [])
            print(f"  Targets:    {', '.join(targets) if targets else 'N/A'}")
            print(f"  Installed:  {rec.get('installed_at', 'N/A')}")


@PortableMSVCApp.subcommand("show-versions")
class ShowVersions(Application):
    """Show available MSVC and Windows SDK versions."""
    PROG_NAME = "show-versions"

    channel  = SwitchAttr("--channel", str, default="release",
                         help="Which channel to query (release|preview)")
    no_cache = Flag("--no-cache", help="Disable manifest cache")
    full     = Flag("--full",     help="Show full MSVC x.y.z.w build versions")

    def main(self):
        cache = not self.no_cache
        if self.full:
            # re-parse to get raw full build strings
            vs_manifest = get_vs_manifest(channel=self.channel, cache=cache)
            parsed      = parse_vs_manifest(
                vs_manifest,
                host=DEFAULT_HOST,
                targets=[DEFAULT_TARGET],
            )
            full_versions = sorted(
                ".".join(pid.split(".")[2:6])
                for pid in parsed["msvc_versions"].values()
            )
            print("MSVC full versions:", " ".join(full_versions))
            # Also show SDK versions in --full mode
            sdk_versions = sorted(parsed["sdk_versions"].keys())
            print("SDK versions: ",      " ".join(sdk_versions))
            return

        # default (major.minor) listing
        versions = get_available_versions(channel=self.channel, cache=cache)
        msvc_versions = sorted(versions["msvc"])
        sdk_versions  = sorted(versions["sdk"])
        print("MSVC versions:", " ".join(msvc_versions))
        print("SDK versions: ", " ".join(sdk_versions))


@PortableMSVCApp.subcommand("install")
class Install(Application):
    """Install MSVC & Windows SDK into a portable layout."""
    PROG_NAME = "install"

    # selection
    msvc_version   = SwitchAttr("--msvc-version", str, help="Force specific MSVC version")
    sdk_version    = SwitchAttr("--sdk-version",  str, help="Force specific Windows SDK version")
    channel        = SwitchAttr("--channel",      str, default="release",
                                help="Which channel to install (release|preview)")
    accept_license = Flag("--accept-license",    help="Automatically accept license")

    # cache only
    no_cache = Flag("--no-cache", help="Disable downloads cache")

    # architecture & output
    host   = SwitchAttr("--host",   str, default=DEFAULT_HOST,
                        help=f"Host arch ({','.join(ALL_HOSTS)})")
    target = SwitchAttr("--target", str, list=True,
                        help=f"Target archs ({','.join(ALL_TARGETS)})")
    output = SwitchAttr("--output", str,
                        help="Custom installation output directory")

    def main(self):
        # compute flags
        cache = not self.no_cache

        # validate host & normalize targets (default = host, support "all")
        if self.host not in ALL_HOSTS:
            self.fatal(f"Unknown host architecture: {self.host}")
        raw_targets = self.target or [self.host]
        # if user asked for "all" (case‐insensitive), expand to every target
        if any(rt.lower() == "all" for rt in raw_targets):
            targets = ALL_TARGETS.copy()
        else:
            targets = []
            for rt in raw_targets:
                t = rt.lower()
                if t not in ALL_TARGETS:
                    self.fatal(f"Unknown target architecture: {rt}")
                targets.append(t)

        # ——— LICENSE ACCEPTANCE ———
        lic_url = get_license_url(channel=self.channel, cache=cache)
        print(f"License text available at:\n  {lic_url}\n")
        accepted = self.accept_license
        if not accepted:
            ans = input("Do you accept the license terms? [y/N] ")
            accepted = ans.strip().lower() in ("y", "yes")
        if not accepted:
            self.fatal("License not accepted. Aborting.")

        # ——— DELEGATE TO CONTROLLER ———
        install_msvc(
            output_dir=Path(self.output) if self.output else None,
            host=self.host,
            targets=targets,
            msvc_version=self.msvc_version,
            sdk_version=self.sdk_version,
            channel=self.channel,
            cache=cache,
            accept_license=accepted,
        )



@PortableMSVCApp.subcommand("register")
class RegisterEnv(Application):
    install_id = SwitchAttr("--id", str,
                           help="ID of the installation to register (omit to pick highest MSVC version)")
    def main(self):
        from .registry_helpers import register_toolchain
        from .install_status   import get_installed_versions
        from pathlib           import Path

        installs = get_installed_versions()
        if not installs:
            self.fatal("No installations are recorded; nothing to register.")

        install_id = self.install_id
        if not install_id:
            # Pick the installation with the highest MSVC version (newest from MS)
            def version_key(item):
                _, rec = item
                ver = rec.get("msvc_version", "")
                # "14.44.17.14" → (14, 44, 17, 14)
                return tuple(int(p) for p in ver.split(".") if p.isdigit())
            install_id, _ = max(installs.items(), key=version_key)

        rec = installs.get(install_id)
        if not rec:
            self.fatal(f"No installation with ID '{install_id}'")
        # the status DB records the root path under "path"
        install_root = rec.get("path")
        if not install_root:
            self.fatal(f"No install path recorded for ID '{install_id}'")
        register_toolchain(install_id, Path(install_root))
        print(f"Registered toolchain {install_id} into HKCU\\Environment.")

@PortableMSVCApp.subcommand("deregister")
class DeregisterEnv(Application):
    install_id = SwitchAttr("--id", str, mandatory=False,
                           help="ID of the installation to deregister (omit for current)")
    def main(self):
        from .registry_helpers import deregister_toolchain, _load_state, _LOCK_FILE, FileLock

        iid = self.install_id
        if not iid:
            # pick up the “current” install_id from the same JSON state
            lock = FileLock(str(_LOCK_FILE), timeout=60)
            with lock:
                state = _load_state()
            iid = state.get("current")
            if not iid:
                self.fatal("No current registration found; please specify --id")

        deregister_toolchain(iid)
        print(f"Deregistered toolchain {iid} from HKCU\\Environment.")

if __name__ == "__main__":
    PortableMSVCApp.run()

