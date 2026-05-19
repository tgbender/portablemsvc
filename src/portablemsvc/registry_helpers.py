# for our backup routine
import datetime

# new imports for JSON state + locking
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock
from winregenv import (
    REG_EXPAND_SZ,
    REG_SZ,
    RegistryError,
    RegistryKeyNotFoundError,
    RegistryRoot,
    RegistryValueNotFoundError,
    broadcast_setting_change,
    expand_environment_strings,
)

from .config import CONFIG_DIR

logger = logging.getLogger(__name__)

# Initialize the registry root for HKEY_CURRENT_USER
hkcu = RegistryRoot("HKCU")


def _backup_path(var_name: str = "Path") -> None:
    """
    Read HKCU\\Environment\\<var_name> and dump it to ~/path_backup/
    as <var_name>_YYYYMMDD_HHMMSS.txt so you can restore if needed.
    """
    try:
        raw = hkcu.get_registry_value("Environment", var_name).data or ""
    except RegistryValueNotFoundError:
        raw = ""
    backup_dir = Path.home() / "path_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = backup_dir / f"{var_name}_{ts}.txt"
    out_file.write_text(raw, encoding="utf-8")
    logger.info(f"Backed up {var_name} to {out_file}")


def _backup_all_env_vars(install_id: str, spec: dict[str, Any]) -> Path:
    """
    Backup all environment variables that will be modified by registration.
    Stores a single JSON file with timestamp and install_id for easy recovery.

    Returns the path to the backup file.
    """
    backup_dir = Path.home() / "path_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Collect current values for all vars we're about to modify
    backup_data: dict[str, Any] = {
        "install_id": install_id,
        "timestamp": ts,
        "vars": {},
    }

    for var in spec:
        try:
            raw = hkcu.get_registry_value("Environment", var).data
            backup_data["vars"][var] = raw
        except RegistryValueNotFoundError:
            backup_data["vars"][var] = None  # Mark as not existing

    out_file = backup_dir / f"portablemsvc_backup_{install_id}_{ts}.json"
    out_file.write_text(json.dumps(backup_data, indent=2), encoding="utf-8")
    logger.info(f"Backed up environment variables to {out_file}")
    return out_file
    logger.info(f"Backed up environment variables to {out_file}")
    return out_file


def get_env_var(name: str) -> str | None:
    """Get an environment variable's value."""
    try:
        return hkcu.get_registry_value("Environment", name).data
    except RegistryValueNotFoundError:
        return None


def set_env_var(name: str, value: str) -> None:
    """Set an environment variable."""
    try:
        hkcu.put_registry_value("Environment", name, value, value_type=REG_SZ)
    except RegistryError as e:
        raise RuntimeError(f"Failed to set registry value: {e}") from e


def get_path(var_name: str = "Path") -> str:
    """Get the current PATH value."""
    try:
        val = hkcu.get_registry_value("Environment", var_name)
        return val.data or ""
    except RegistryValueNotFoundError:
        return ""


def set_path(new_path: str, var_name: str = "Path") -> None:
    """Set a new PATH value."""
    try:
        hkcu.put_registry_value("Environment", var_name, new_path, value_type=REG_SZ)
    except RegistryError as e:
        raise RuntimeError(f"Failed to set registry value: {e}") from e


def append_to_path(value: str, var_name: str = "Path") -> None:
    """Append a new directory to PATH."""
    current_path = get_path(var_name)
    if not current_path:
        new_path = value
    else:
        if value not in current_path.split(";"):
            new_path = f"{current_path};{value}"
        else:
            new_path = current_path
    set_path(new_path, var_name)


def replace_in_path(find: str, replace: str) -> bool:
    """Replace text in PATH."""
    current_path = get_path()
    if find not in current_path:
        return False
    new_path = current_path.replace(find, replace)
    set_path(new_path)
    return True


def get_all_env_vars() -> dict[str, str]:
    """Get all environment variables from HKCU."""
    try:
        values = hkcu.list_registry_values("Environment")
        return {v.name: v.data for v in values}
    except RegistryKeyNotFoundError:
        return {}


def upsert_path_entry(new_dir: str, marker: str) -> None:
    """
    Insert or update a directory in the user's PATH.
    If an existing entry contains marker_exe, replace that entry; otherwise append.
    """
    raw = get_path()
    entries = raw.split(";") if raw else []
    # Expand each entry to resolve any environment variables
    expanded = [expand_environment_strings(e) for e in entries]
    # Find index where marker exists
    idx = next(
        (i for i, e in enumerate(expanded) if (Path(e) / marker).exists()),
        None,
    )
    if idx is not None:
        entries[idx] = new_dir
    else:
        entries.append(new_dir)
    # Write the updated PATH back to the registry
    set_path(";".join(entries))


# ----------------------------------------------------------------------
# JSON-backed registration state (so we know exactly what to remove later)
# ----------------------------------------------------------------------
_STATE_FILE = Path(CONFIG_DIR) / "registry_state.json"
_LOCK_FILE = _STATE_FILE.with_suffix(".lock")
_LOCK_TIMEOUT = 60  # seconds
_METADATA_VARS = {"TOOL_VERSIONS"}  # Not environment variables, just debug info.


@dataclass
class _RegistryUpdate:
    value: str | None
    value_type: int | None


def _split_path_value(value: str) -> list[str]:
    return [p for p in value.split(";") if p]


def _env_vars_for_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return {var: entries for var, entries in spec.items() if var not in _METADATA_VARS}


def _capture_previous_env(spec: dict[str, Any]) -> dict[str, str | None]:
    previous: dict[str, str | None] = {}
    for var in _env_vars_for_spec(spec):
        try:
            previous[var] = hkcu.get_registry_value("Environment", var).data
        except RegistryValueNotFoundError:
            previous[var] = None
    return previous


def _registration_update(current: str, entries: Any) -> _RegistryUpdate:
    if isinstance(entries, list):
        parts = [p for p in _split_path_value(current) if p not in entries]
        return _RegistryUpdate(";".join(entries + parts), REG_EXPAND_SZ)
    return _RegistryUpdate(str(entries), REG_SZ)


def _unregistration_update(
    current: str,
    entries: Any,
    previous: str | None = None,
) -> _RegistryUpdate:
    if isinstance(entries, list):
        parts = [p for p in _split_path_value(current) if p not in entries]
        if parts:
            return _RegistryUpdate(";".join(parts), REG_EXPAND_SZ)
        return _RegistryUpdate(None, None)

    if current != str(entries):
        return _RegistryUpdate(current, REG_SZ)
    if previous is None:
        return _RegistryUpdate(None, None)
    return _RegistryUpdate(previous, REG_SZ)


def _load_state() -> dict[str, Any]:
    if _STATE_FILE.exists():
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    return {"registered": {}}


def _save_state(state: dict[str, Any]) -> None:
    # atomic write
    tmp = _STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(_STATE_FILE)


def register_toolchain(install_id: str, install_root: Path) -> None:
    """
    Apply the install_root/env.json spec to HKCU\\Environment and
    record <install_id> → install_root in a locked JSON file.
    """
    # 1) ensure config dir exists
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # load the env.json that was written at install time
    spec = json.loads((install_root / "env.json").read_text(encoding="utf-8"))

    lock = FileLock(str(_LOCK_FILE), timeout=_LOCK_TIMEOUT)
    with lock:
        state = _load_state()
        registered = state.get("registered", {})
        current = state.get("current")
        if (current and current != install_id) or (
            registered and install_id not in registered
        ):
            raise RuntimeError(
                "A PortableMSVC toolchain is already registered; unregister it first."
            )

    # 0) back up the user's existing env vars before we mutate them
    _backup_path("Path")  # text backup, easy to copy
    _backup_all_env_vars(install_id, spec)  # JSON backup, complete record
    previous_env = _capture_previous_env(spec)

    # 1) apply each variable exactly as specced
    for var, entries in _env_vars_for_spec(spec).items():
        try:
            raw = hkcu.get_registry_value("Environment", var).data or ""
        except RegistryValueNotFoundError:
            raw = ""
        update = _registration_update(raw, entries)
        hkcu.put_registry_value(
            "Environment", var, update.value or "", value_type=update.value_type
        )

    # notify all processes once
    broadcast_setting_change("Environment")

    # 2) record the fact that install_id is now registered
    with lock:
        state = _load_state()
        state.setdefault("registered", {})[install_id] = {
            "path": str(Path(install_root).resolve()),
            "previous_env": previous_env,
        }
        # mark this one as the “current” registration
        state["current"] = install_id
        _save_state(state)


def unregister_toolchain(install_id: str) -> None:
    """
    Undo the env.json changes for a previously-registered install_id.
    Only the entries recorded in that install's env.json will be removed.
    """
    lock = FileLock(str(_LOCK_FILE), timeout=_LOCK_TIMEOUT)
    with lock:
        state = _load_state()
        record = state.get("registered", {}).pop(install_id, None)
        # if it was the “current” one, clear that too
        if state.get("current") == install_id:
            state.pop("current", None)
        _save_state(state)

    # nothing to do if it was never registered
    if not record:
        return
    if isinstance(record, dict):
        install_root = record.get("path")
        previous_env = record.get("previous_env", {})
    else:
        # Backward compatibility with older registry_state.json records.
        install_root = record
        previous_env = {}
    if not install_root:
        return

    # read back the same spec
    spec = json.loads((Path(install_root) / "env.json").read_text(encoding="utf-8"))

    # remove exactly those entries
    for var, entries in _env_vars_for_spec(spec).items():
        try:
            raw = hkcu.get_registry_value("Environment", var).data or ""
        except RegistryValueNotFoundError:
            continue
        update = _unregistration_update(raw, entries, previous_env.get(var))
        if update.value is not None:
            hkcu.put_registry_value(
                "Environment", var, update.value, value_type=update.value_type
            )
        else:
            with suppress(RegistryValueNotFoundError, RegistryError):
                hkcu.delete_registry_value("Environment", var)

    broadcast_setting_change("Environment")


def check_long_paths_enabled() -> bool:
    """Check if Windows long path support is enabled.

    Long paths (>260 chars) require the LongPathsEnabled registry value
    to be set to 1 in HKLM\\SYSTEM\\CurrentControlSet\\Control\\Filesystem.

    This is important for msiexec which can fail silently when paths
    exceed MAX_PATH (260 characters).

    Returns True if enabled or if registry cannot be read (assume modern Windows).
    """
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            return value == 1
    except (OSError, ImportError):
        # Assume enabled on modern Windows if we can't read
        return True


def warn_if_long_paths_disabled():
    """Log a warning if long paths are not enabled."""
    if not check_long_paths_enabled():
        logger.warning(
            "Windows long path support is not enabled. This may cause issues "
            "with MSI extraction if paths exceed 260 characters. "
            "Consider enabling LongPathsEnabled in registry: "
            "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\\LongPathsEnabled=1"
        )
