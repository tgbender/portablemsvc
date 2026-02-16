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

    def set_env_spec(self, spec: Dict[str, Any]) -> None:
        """Record the environment specification."""
        self.data["env_spec"] = spec

    def set_install_id(self, install_id: str) -> None:
        """Record the installation ID."""
        self.data["install_id"] = install_id

    def to_dict(self) -> Dict[str, Any]:
        """Return the lockfile as a dictionary."""
        return self.data

    def write(self, path: Path) -> None:
        """Write the lockfile to disk."""
        path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Lockfile":
        """Load a lockfile from disk."""
        instance = cls.__new__(cls)
        instance.data = json.loads(path.read_text(encoding="utf-8"))
        return instance
