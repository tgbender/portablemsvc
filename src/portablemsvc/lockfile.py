"""Lockfile generation and management for reproducible MSVC installs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class Lockfile:
    """Tracks all artifacts needed for a reproducible MSVC installation."""

    def __init__(
        self,
        *,
        channel: str,
        host: str,
        targets: List[str],
        msvc_version: Optional[str] = None,
        sdk_version: Optional[str] = None,
    ):
        self.data: Dict[str, Any] = {
            "lockfile_version": "1.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "channel": channel,
            "host": host,
            "targets": targets,
            "requested": {
                "msvc_version": msvc_version,
                "sdk_version": sdk_version,
            },
            "resolved": {
                "msvc": None,
                "sdk": None,
            },
            "sources": {
                "channel_manifest": None,
                "vs_manifest": None,
            },
            "files": [],
            "extraction_sequence": [],
            "removed_files": [],
        }
        self._extraction_order = 0

    def set_source_manifests(
        self,
        *,
        channel_manifest_url: str,
        channel_manifest_hash: str,
        vs_manifest_url: str,
        vs_manifest_hash: str,
    ) -> None:
        """Record the source manifest URLs and hashes."""
        self.data["sources"]["channel_manifest"] = {
            "url": channel_manifest_url,
            "sha256": channel_manifest_hash,
        }
        self.data["sources"]["vs_manifest"] = {
            "url": vs_manifest_url,
            "sha256": vs_manifest_hash,
        }

    def set_resolved_versions(
        self,
        *,
        msvc_full_version: str,
        msvc_package_id: str,
        sdk_version: str,
        sdk_package_id: str,
    ) -> None:
        """Record the resolved MSVC and SDK versions."""
        self.data["resolved"]["msvc"] = {
            "full_version": msvc_full_version,
            "package_id": msvc_package_id,
        }
        self.data["resolved"]["sdk"] = {
            "version": sdk_version,
            "package_id": sdk_package_id,
        }

    def add_file(
        self,
        *,
        file_id: str,
        filename: str,
        url: str,
        sha256: str,
        file_type: str,  # "zip", "msi", "cab", "vsix"
        package_ref: str,
        parent: Optional[str] = None,  # For CABs, the parent MSI filename
    ) -> Dict[str, Any]:
        """Add a file entry and return the entry dict for later updates."""
        entry: Dict[str, Any] = {
            "id": file_id,
            "filename": filename,
            "url": url,
            "sha256": sha256,
            "type": file_type,
            "package_ref": package_ref,
            "parent": parent,
            "downloaded_path": None,
            "extracted_paths": [],
        }
        self.data["files"].append(entry)
        return entry

    def get_file_entry(self, filename: str) -> Optional[Dict[str, Any]]:
        """Find a file entry by filename."""
        for f in self.data["files"]:
            if f["filename"] == filename:
                return f
        return None

    def set_file_downloaded(self, filename: str, cache_path: Path) -> None:
        """Record that a file was downloaded to a specific cache path."""
        entry = self.get_file_entry(filename)
        if entry:
            entry["downloaded_path"] = str(cache_path)

    def add_file_extraction(self, filename: str, extracted_path: Path) -> None:
        """Record that a file extracted to specific paths with order."""
        entry = self.get_file_entry(filename)
        if entry:
            entry["extracted_paths"].append(str(extracted_path))
            # Track extraction sequence if not already recorded for this file
            if filename not in [s["filename"] for s in self.data["extraction_sequence"]]:
                self._extraction_order += 1
                self.data["extraction_sequence"].append({
                    "order": self._extraction_order,
                    "filename": filename,
                    "file_id": entry.get("id", filename),
                })

    def add_removed_file(self, path: Path) -> None:
        """Record a file or directory that was removed during cleanup."""
        self.data["removed_files"].append(str(path))

    def set_env_spec(self, spec: Dict[str, Any], install_root: Optional[Path] = None) -> None:
        """Record the environment specification with portable paths.

        Args:
            spec: The env spec dict (may contain absolute paths)
            install_root: The installation root directory (to make paths portable)
        """
        import copy

        portable_spec = copy.deepcopy(spec)

        if install_root is not None:
            # Get user profile path for substitution
            home = Path.home()
            home_str = str(home)
            root_str = str(install_root.resolve())

            def make_portable(path_str: str) -> str:
                """Convert path to portable format.

                Priority:
                1. If under install_root, make relative (for portability)
                2. If under home directory, use %USERPROFILE%
                3. Otherwise keep as-is (absolute path elsewhere)
                """
                if not isinstance(path_str, str):
                    return path_str
                # If under install_root, make relative (checked first since install_root is typically under home)
                if path_str.startswith(root_str):
                    rel = path_str[len(root_str):]
                    if rel.startswith("\\") or rel.startswith("/"):
                        rel = rel[1:]
                    return rel if rel else "."
                # If path starts with home directory, use %USERPROFILE%
                if path_str.startswith(home_str):
                    rel = path_str[len(home_str):]
                    if rel.startswith("\\") or rel.startswith("/"):
                        rel = rel[1:]
                    return f"%USERPROFILE%\\{rel}" if rel else "%USERPROFILE%"
                # Otherwise keep as-is (absolute path elsewhere)
                return path_str

            # Convert scalar path fields
            for key in ["CC", "CXX", "AR", "VCINSTALLDIR", "VCToolsInstallDir", "WindowsSDKDir"]:
                if key in portable_spec:
                    portable_spec[key] = make_portable(portable_spec[key])

            # Convert list path fields
            for key in ["PATH", "INCLUDE", "LIB", "LIBPATH"]:
                if key in portable_spec and isinstance(portable_spec[key], list):
                    portable_spec[key] = [make_portable(p) for p in portable_spec[key]]

        self.data["env_spec"] = portable_spec

    def set_install_id(self, install_id: str) -> None:
        """Record the installation ID."""
        self.data["install_id"] = install_id

    def to_dict(self) -> Dict[str, Any]:
        """Return the lockfile as a dictionary."""
        return self.data

    def get_absolute_env_spec(self, install_root: Path) -> Dict[str, Any]:
        """Generate absolute env_spec from portable paths.

        Expands %USERPROFILE% and relative paths to absolute.

        Args:
            install_root: The installation root directory

        Returns:
            env_spec dict with absolute paths
        """
        import copy

        portable_spec = self.data.get("env_spec", {})
        if not portable_spec:
            return {}

        abs_spec = copy.deepcopy(portable_spec)
        root = install_root.resolve()
        home = Path.home()

        def expand_path(path_str: str) -> str:
            """Expand %USERPROFILE% and relative paths."""
            if not isinstance(path_str, str):
                return path_str
            # Expand %USERPROFILE%
            if "%USERPROFILE%" in path_str:
                path_str = path_str.replace("%USERPROFILE%", str(home))
            # If relative, join with install_root
            if not Path(path_str).is_absolute():
                path_str = str(root / path_str)
            return path_str

        # Convert scalar path fields
        for key in ["CC", "CXX", "AR", "VCINSTALLDIR", "VCToolsInstallDir", "WindowsSDKDir"]:
            if key in abs_spec:
                abs_spec[key] = expand_path(abs_spec[key])

        # Convert list path fields
        for key in ["PATH", "INCLUDE", "LIB", "LIBPATH"]:
            if key in abs_spec and isinstance(abs_spec[key], list):
                abs_spec[key] = [expand_path(p) for p in abs_spec[key]]

        return abs_spec

    def write(self, path: Path) -> None:
        """Write the lockfile to disk."""
        path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Lockfile":
        """Load a lockfile from disk."""
        instance = cls.__new__(cls)
        instance.data = json.loads(path.read_text(encoding="utf-8"))
        return instance
