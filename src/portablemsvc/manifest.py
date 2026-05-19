# manifest.py setup
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from .config import (
    CACHE_DIR,
    MANIFEST_CACHE_TTL,
    MANIFEST_PREVIEW_URL,
    MANIFEST_REQUEST_TIMEOUT,
    MANIFEST_URL,
    PREVIEW_CHANNEL_MANIFEST_NAME,
    RELEASE_CHANNEL_MANIFEST_NAME,
)

logger = logging.getLogger(__name__)

# Make the public interface exportable
__all__ = ["get_vs_manifest"]


def _download_channel_manifest(
    *,
    channel: str = "release",
    cache: bool = True,
    cache_dir: Path = CACHE_DIR,
    cache_ttl: int = MANIFEST_CACHE_TTL,
) -> tuple[dict[str, Any], str, str]:
    # Pick the right channel
    if channel == "preview":
        manifest_fetch_url = MANIFEST_PREVIEW_URL
        cache_path = Path(cache_dir) / "preview_channel_manifest.json"
        cache_meta_path = Path(cache_dir) / "preview_channel_manifest_meta.json"
    elif channel == "release":
        manifest_fetch_url = MANIFEST_URL
        cache_path = Path(cache_dir) / "release_channel_manifest.json"
        cache_meta_path = Path(cache_dir) / "release_channel_manifest_meta.json"
    else:
        raise ValueError(f"Unknown channel: {channel}")

    # Load a fresh-enough cached manifest when available.
    if cache and cache_path.exists() and cache_meta_path.exists():
        with open(cache_meta_path) as f:
            cache_meta = json.load(f)

        if time.time() - cache_meta["timestamp"] < cache_ttl:
            with open(cache_path) as f:
                manifest = json.load(f)
            # Return with source info for lockfile
            return manifest, cache_meta.get("url", ""), cache_meta.get("hash", "")

    # Grabs the manifest data
    try:
        logger.debug(f"Fetching manifest from {manifest_fetch_url}")
        manifest_response = requests.get(
            manifest_fetch_url, timeout=MANIFEST_REQUEST_TIMEOUT
        )
        manifest_response.raise_for_status()  # raise an error if the request didn't succeed

        manifest_json = json.loads(manifest_response.text)
        manifest_hash = hashlib.sha256(manifest_response.content).hexdigest()

        # Write the manifest to cache with metadata
        if cache:
            try:
                with open(cache_path, "w") as f:
                    json.dump(manifest_json, f)

                with open(cache_meta_path, "w") as f:
                    json.dump(
                        {
                            "timestamp": time.time(),
                            "hash": manifest_hash,
                            "url": manifest_fetch_url,
                        },
                        f,
                    )
                logger.debug("Manifest cached successfully")
            except Exception as e:
                logger.warning(f"Failed to cache manifest: {e}")

        return manifest_json, manifest_fetch_url, manifest_hash

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch manifest from {manifest_fetch_url}: {e}")

        # If we have a cache (even if expired), use it as fallback
        if cache_path.exists():
            logger.warning("Using expired cache as fallback")
            with open(cache_path) as f:
                manifest = json.load(f)
            # Try to get cached metadata
            try:
                with open(cache_meta_path) as meta_f:
                    cache_meta = json.load(meta_f)
                    return (
                        manifest,
                        cache_meta.get("url", ""),
                        cache_meta.get("hash", ""),
                    )
            except (FileNotFoundError, json.JSONDecodeError):
                return manifest, "", ""

        # If all else fails, raise a standard exception
        raise OSError(f"Failed to download manifest: {e}") from e


def _parse_channel_manifest(
    channel_manifest: dict, channel: str = "release"
) -> tuple[str, str]:
    if channel == "preview":
        item_name = PREVIEW_CHANNEL_MANIFEST_NAME
    elif channel == "release":
        item_name = RELEASE_CHANNEL_MANIFEST_NAME
    else:
        raise ValueError(f"Unknown channel: {channel}")

    try:
        # Find the item with the matching id
        vs = None
        for item in channel_manifest["channelItems"]:
            if item["id"] == item_name:
                vs = item
                break

        if vs is None:
            raise ValueError(
                f"Could not find item with id '{item_name}' in channel manifest"
            )

        vs_manifest_url = vs["payloads"][0]["url"]
        vs_manifest_hash = vs["payloads"][0].get("sha256", "")
        return vs_manifest_url, vs_manifest_hash

    except (KeyError, IndexError) as e:
        logger.error(f"Failed to parse channel manifest: {e}")
        raise ValueError(f"Invalid channel manifest structure: {e}") from e


def _download_vs_manifest(
    vs_manifest_url: str,
    *,
    expected_hash: str = "",
    cache: bool = True,
    cache_dir: Path = CACHE_DIR,
    cache_ttl: int = MANIFEST_CACHE_TTL,
) -> tuple[dict[str, Any], str, str]:
    """
    Download the Visual Studio manifest from the provided URL.

    Args:
        vs_manifest_url: URL to download the VS manifest from
        cache: Whether to use/update the cache
        cache_dir: Directory to store cached manifests
        cache_ttl: Time-to-live for cached manifests in seconds

    Returns:
        The VS manifest as a dictionary
    """
    # Generate cache paths based on the URL hash to avoid conflicts
    url_hash = hashlib.sha256(vs_manifest_url.encode()).hexdigest()[:16]
    cache_path = Path(cache_dir) / f"vs_manifest_{url_hash}.json"
    cache_meta_path = Path(cache_dir) / f"vs_manifest_{url_hash}_meta.json"

    # Check if the cached manifest file exists and isn't older than the TTL
    if cache and cache_path.exists() and cache_meta_path.exists():
        with open(cache_meta_path) as f:
            cache_meta = json.load(f)

        cached_channel_hash = cache_meta.get("channel_sha256", "").lower()
        expected = expected_hash.lower()
        if (
            expected
            and cached_channel_hash
            and cached_channel_hash != expected
        ):
            logger.warning("Cached VS manifest belongs to a different channel hash")
        elif time.time() - cache_meta["timestamp"] < cache_ttl:
            logger.debug(f"Using cached VS manifest from {cache_path}")
            with open(cache_path) as f:
                return json.load(f), vs_manifest_url, cache_meta.get("hash", "")

    # Download the VS manifest
    try:
        logger.debug(f"Fetching VS manifest from {vs_manifest_url}")
        manifest_response = requests.get(
            vs_manifest_url, timeout=MANIFEST_REQUEST_TIMEOUT
        )
        manifest_response.raise_for_status()  # raise an error if the request didn't succeed

        vs_manifest_json = json.loads(manifest_response.text)
        manifest_hash = hashlib.sha256(manifest_response.content).hexdigest()
        if expected_hash and manifest_hash.lower() != expected_hash.lower():
            logger.warning(
                "VS manifest hash mismatch. "
                f"Expected {expected_hash.lower()}, got {manifest_hash.lower()}"
            )

        # Write the manifest to cache with metadata
        if cache:
            try:
                with open(cache_path, "w") as f:
                    json.dump(vs_manifest_json, f)

                with open(cache_meta_path, "w") as f:
                    json.dump(
                        {
                            "timestamp": time.time(),
                            "hash": manifest_hash,
                            "channel_sha256": expected_hash,
                            "url": vs_manifest_url,
                        },
                        f,
                    )
                logger.debug("VS manifest cached successfully")
            except Exception as e:
                logger.warning(f"Failed to cache VS manifest: {e}")

        return vs_manifest_json, vs_manifest_url, manifest_hash

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch VS manifest from {vs_manifest_url}: {e}")

        # If we have a cache (even if expired), use it as fallback
        if cache and cache_path.exists():
            logger.warning("Using expired VS manifest cache as fallback")
            with open(cache_path) as f:
                manifest = json.load(f)
            # Try to get cached metadata
            try:
                with open(cache_meta_path) as meta_f:
                    cache_meta = json.load(meta_f)
                    cached_channel_hash = cache_meta.get("channel_sha256", "").lower()
                    if (
                        expected_hash
                        and cached_channel_hash
                        and cached_channel_hash != expected_hash.lower()
                    ):
                        raise OSError(
                            "Cached VS manifest belongs to a different channel hash"
                        ) from e
                    return manifest, vs_manifest_url, cache_meta.get("hash", "")
            except (FileNotFoundError, json.JSONDecodeError):
                return manifest, vs_manifest_url, ""

        # If all else fails, raise a standard exception
        raise OSError(f"Failed to download VS manifest: {e}") from e


def get_vs_manifest(
    *,
    channel: str = "release",
    cache: bool = True,
    cache_dir: Path = CACHE_DIR,
    cache_ttl: int = MANIFEST_CACHE_TTL,
) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Get the Visual Studio manifest for the specified channel.

    This is the main public interface for accessing Visual Studio manifests.

    Args:
        channel (str): The channel to get the manifest for. Either 'release' or 'preview'.
        cache (bool): Whether to use and update the local cache.
        cache_dir (str): Directory to store cached manifests.
        cache_ttl (int): Time-to-live for cached manifests in seconds.

    Returns:
        dict: The Visual Studio manifest as a dictionary.

    Raises:
        ValueError: If the channel is unknown or the manifest structure is invalid.
        IOError: If there's a network error and no valid cache exists.
    """
    # Step 0: Validate inputs
    if channel not in ["release", "preview"]:
        raise ValueError(f"Unknown channel: {channel}")
    if not isinstance(cache, bool):
        raise TypeError("cache parameter must be a boolean")
    if cache_ttl <= 0:
        raise ValueError("cache_ttl must be a positive integer")
    if cache:
        if not cache_dir:
            raise ValueError("cache_dir must be specified if cache is enabled")
        try:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ValueError(f"Failed to create cache directory: {e}") from e

    # Step 1: Download the channel manifest
    channel_manifest, channel_url, channel_hash = _download_channel_manifest(
        channel=channel, cache=cache, cache_dir=cache_dir, cache_ttl=cache_ttl
    )

    # Step 2: Parse the channel manifest to get the VS manifest URL
    vs_manifest_url, vs_manifest_hash = _parse_channel_manifest(
        channel_manifest, channel=channel
    )

    # Step 3: Download the VS manifest
    vs_manifest, final_url, final_hash = _download_vs_manifest(
        vs_manifest_url,
        expected_hash=vs_manifest_hash,
        cache=cache,
        cache_dir=cache_dir,
        cache_ttl=cache_ttl,
    )

    return vs_manifest, {
        "channel_manifest_url": channel_url,
        "channel_manifest_hash": channel_hash,
        "vs_manifest_url": vs_manifest_url,
        "vs_manifest_hash": vs_manifest_hash or final_hash,
        "channel_payload_url": final_url,
    }


def get_license_url(
    *,
    channel: str = "release",
    cache: bool = True,
    cache_dir: Path = CACHE_DIR,
    cache_ttl: int = MANIFEST_CACHE_TTL,
) -> str:
    """
    Return the URL of the BuildTools license for the given channel.
    """
    chan, _, _ = _download_channel_manifest(
        channel=channel, cache=cache, cache_dir=cache_dir, cache_ttl=cache_ttl
    )
    for item in chan.get("channelItems", []):
        if item.get("id") == "Microsoft.VisualStudio.Product.BuildTools":
            for res in item.get("localizedResources", []):
                if res.get("language", "").lower() == "en-us":
                    return res["license"]
    raise ValueError("Could not find BuildTools license in channel manifest")
