from pathlib import Path
from typing import Dict, Optional
from winregenv import RegistryRoot, RegistryValueNotFoundError, RegistryKeyNotFoundError, RegistryError
from winregenv import REG_SZ, REG_DWORD, REG_EXPAND_SZ, expand_environment_strings, broadcast_setting_change

# new imports for JSON state + locking
import json
from filelock import FileLock
from .config import CONFIG_DIR
# for our backup routine
import datetime
import logging

logger = logging.getLogger(__name__)
from filelock import FileLock
from .config import CONFIG_DIR

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

def get_env_var(name: str) -> Optional[str]:
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
        raise RuntimeError(f"Failed to set registry value: {e}")

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
        raise RuntimeError(f"Failed to set registry value: {e}")

def append_to_path(value: str, var_name: str = "Path") -> None:
    """Append a new directory to PATH."""
    current_path = get_path(var_name)
    if not current_path:
        new_path = value
    else:
        if value not in current_path.split(';'):
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

def get_all_env_vars() -> Dict[str, str]:
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
        (
            i
            for i, e in enumerate(expanded)
            if (Path(e) / marker).exists()
        ),
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
_LOCK_FILE  = _STATE_FILE.with_suffix(".lock")
_LOCK_TIMEOUT = 60  # seconds

def _load_state() -> Dict[str, str]:
    if _STATE_FILE.exists():
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    return {"registered": {}}

def _save_state(state: Dict[str, str]) -> None:
    # atomic write
    tmp = _STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(_STATE_FILE)


def register_toolchain(install_id: str, install_root: Path) -> None:
    """
    Apply the install_root/env.json spec to HKCU\\Environment and
    record <install_id> → install_root in a locked JSON file.
    """
    # 0) back up the user's existing PATH before we mutate it
    _backup_path("Path")

    # 1) ensure config dir exists
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # load the env.json that was written at install time
    spec = json.loads((install_root / "env.json").read_text(encoding="utf-8"))

    # 1) apply each variable exactly as specced
    for var, entries in spec.items():
        if isinstance(entries, list):
            # merge new list entries into front of the existing PATH-style var
            try:
                raw = hkcu.get_registry_value("Environment", var).data or ""
            except RegistryValueNotFoundError:
                raw = ""
            parts = [p for p in raw.split(";") if p and p not in entries]
            new_val = ";".join(entries + parts)
            hkcu.put_registry_value("Environment", var,
                                    new_val,
                                    value_type=REG_EXPAND_SZ)
        else:
            # scalar var → overwrite entirely
            new_val = str(entries)
            hkcu.put_registry_value("Environment", var,
                                    new_val,
                                    value_type=REG_SZ)

    # notify all processes once
    broadcast_setting_change("Environment")

    # 2) record the fact that install_id is now registered
    lock = FileLock(str(_LOCK_FILE), timeout=_LOCK_TIMEOUT)
    with lock:
        state = _load_state()
        state.setdefault("registered", {})[install_id] = str(Path(install_root).resolve())
        # mark this one as the “current” registration
        state["current"] = install_id
        _save_state(state)


def deregister_toolchain(install_id: str) -> None:
    """
    Undo the env.json changes for a previously-registered install_id.
    Only the entries recorded in that install's env.json will be removed.
    """
    lock = FileLock(str(_LOCK_FILE), timeout=_LOCK_TIMEOUT)
    with lock:
        state = _load_state()
        install_root = state.get("registered", {}).pop(install_id, None)
        # if it was the “current” one, clear that too
        if state.get("current") == install_id:
            state.pop("current", None)
        _save_state(state)

    # nothing to do if it was never registered
    if not install_root:
        return

    # read back the same spec
    spec = json.loads((Path(install_root) / "env.json").read_text(encoding="utf-8"))

    # remove exactly those entries
    for var, entries in spec.items():
        try:
            raw = hkcu.get_registry_value("Environment", var).data or ""
        except RegistryValueNotFoundError:
            continue
        parts = [p for p in raw.split(";") if p and p not in entries]
        new_val = ";".join(parts)
        if parts:
            # update with remaining entries
            hkcu.put_registry_value("Environment", var, new_val, value_type=REG_EXPAND_SZ)
        else:
            # nothing left → delete the registry value entirely
            try:
                hkcu.delete_registry_value("Environment", var)
            except (RegistryValueNotFoundError, RegistryError):
                pass

    broadcast_setting_change("Environment")
