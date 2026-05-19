"""Lockfile generation and management for reproducible MSVC installs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Lockfile:
    """Tracks all artifacts needed for a reproducible MSVC installation."""

    def __init__(
        self,
        *,
        channel: str,
        host: str,
        targets: list[str],
        msvc_version: str | None = None,
        sdk_version: str | None = None,
    ):
        self.data: dict[str, Any] = {
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
        vs_manifest_declared_hash: str | None = None,
        vs_manifest_downloaded_hash: str | None = None,
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
        if vs_manifest_declared_hash:
            self.data["sources"]["vs_manifest"]["channel_declared_sha256"] = (
                vs_manifest_declared_hash
            )
        if vs_manifest_downloaded_hash:
            self.data["sources"]["vs_manifest"]["downloaded_sha256"] = vs_manifest_downloaded_hash

    def set_resolved_versions(
        self,
        *,
        msvc_toolset_version: str,
        msvc_package_version: str,
        msvc_package_id: str,
        sdk_build_number: str,
        sdk_version: str,
        sdk_package_id: str,
    ) -> None:
        """Record the resolved MSVC and SDK versions."""
        self.data["resolved"]["msvc"] = {
            "toolset_version": msvc_toolset_version,
            "package_version": msvc_package_version,
            "vctools_version": None,  # populated after extraction
            "package_id": msvc_package_id,
        }
        self.data["resolved"]["sdk"] = {
            "build_number": sdk_build_number,
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
        parent: str | None = None,  # For CABs, the parent MSI filename
    ) -> dict[str, Any]:
        """Add a file entry and return the entry dict for later updates."""
        entry: dict[str, Any] = {
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

    def get_file_entry(self, filename: str) -> dict[str, Any] | None:
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
                self.data["extraction_sequence"].append(
                    {
                        "order": self._extraction_order,
                        "filename": filename,
                        "file_id": entry.get("id", filename),
                    }
                )

    def add_removed_file(self, path: Path) -> None:
        """Record a file or directory that was removed during cleanup."""
        self.data["removed_files"].append(str(path))

    def set_env_spec(self, spec: dict[str, Any], install_root: Path | None = None) -> None:
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
                # Check install_root first since it is typically under home.
                if path_str.startswith(root_str):
                    rel = path_str[len(root_str) :]
                    if rel.startswith("\\") or rel.startswith("/"):
                        rel = rel[1:]
                    return rel if rel else "."
                # If path starts with home directory, use %USERPROFILE%
                if path_str.startswith(home_str):
                    rel = path_str[len(home_str) :]
                    if rel.startswith("\\") or rel.startswith("/"):
                        rel = rel[1:]
                    return f"%USERPROFILE%\\{rel}" if rel else "%USERPROFILE%"
                # Otherwise keep as-is (absolute path elsewhere)
                return path_str

            # Convert scalar path fields
            for key in [
                "CC",
                "CXX",
                "AR",
                "VCINSTALLDIR",
                "VCToolsInstallDir",
                "WindowsSDKDir",
            ]:
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

    def set_tool_versions(self, tool_versions: dict[str, str]) -> None:
        """Record the versions of installed tools (cl.exe, lib.exe, etc.)."""
        self.data["tool_versions"] = tool_versions

    def set_msvc_vctools_version(self, vctools_version: str) -> None:
        """Record the detected on-disk VCToolsVersion (detected after extraction)."""
        self.data["resolved"]["msvc"]["vctools_version"] = vctools_version

    def to_dict(self) -> dict[str, Any]:
        """Return the lockfile as a dictionary."""
        return self.data

    def get_absolute_env_spec(self, install_root: Path) -> dict[str, Any]:
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
        for key in [
            "CC",
            "CXX",
            "AR",
            "VCINSTALLDIR",
            "VCToolsInstallDir",
            "WindowsSDKDir",
        ]:
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
    def load(cls, path: Path) -> Lockfile:
        """Load a lockfile from disk."""
        instance = cls.__new__(cls)
        instance.data = json.loads(path.read_text(encoding="utf-8"))
        return instance
