"""
kiln/cache.py

Two-tier artifact cache for kiln build artifacts.

Tier 1: Local disk cache  (~/.kiln/cache/ by default)
  - Full read/write for any user
  - Sharded by first 2 chars of manifest hash (git object store layout)
  - clearable at any time with no side effects except longer build times

Tier 2: Global cache  (configured URL — https://, s3://, or local path)
  - Read for all users
  - Write only via --publish (CI credential required)
  - Fetch-through: global hit → populate local → unpack from local

Resolution order:
  local hit  → use directly
  global hit → fetch to local → use from local
  both miss  → build required

Each cached component consists of three files:
  <shard>/<rest>/runtime.tar.zst      runtime package
  <shard>/<rest>/buildtime.tar.zst    buildtime package
  <shard>/<rest>/manifest.txt         canonical manifest (for inspection/audit)
"""

from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CacheError(Exception):
    """Raised on cache operation failure."""
    def __init__(self, key: str, reason: str):
        self.key    = key
        self.reason = reason
        super().__init__(f"cache[{key[:12]}]: {reason}")


class CachePermissionError(CacheError):
    """Raised when a write to the global cache is attempted without credentials."""
    pass


# ---------------------------------------------------------------------------
# Artifact — what lives at one cache key
# ---------------------------------------------------------------------------

class Artifact:
    """
    The three files that live at one cache key.
    Paths are absolute — caller unpacks as needed.
    """
    def __init__(self, base: Path):
        self.base          = base
        self.runtime       = base / "runtime.tar.zst"
        self.buildtime     = base / "buildtime.tar.zst"
        self.manifest_txt  = base / "manifest.txt"

    def is_complete(self) -> bool:
        """All three files must exist for the artifact to be valid."""
        return (
            self.runtime.exists()
            and self.buildtime.exists()
            and self.manifest_txt.exists()
        )

    def __repr__(self) -> str:
        ok = "complete" if self.is_complete() else "incomplete"
        return f"<Artifact {self.base.parent.name}{self.base.name} {ok}>"


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------

class CacheBackend(ABC):
    """
    Abstract backend — implement for local disk, S3, HTTP, etc.
    All methods raise CacheError on failure.
    Stat failure is a hard error (network down = build futile).
    """

    @abstractmethod
    def stat(self, key: str) -> bool:
        """Return True if artifact exists and is complete."""
        ...

    @abstractmethod
    def fetch(self, key: str, dest: Path) -> None:
        """
        Copy artifact files into dest/.
        dest will be created if it doesn't exist.
        """
        ...

    @abstractmethod
    def store(self, key: str, src: Path) -> None:
        """
        Store artifact from src/ under key.
        src must contain runtime.tar.zst, buildtime.tar.zst, manifest.txt
        """
        ...

    @abstractmethod
    def remove(self, key: str) -> None:
        """Delete artifact. No-op if not present."""
        ...

    def list_keys(self) -> list[str]:
        """Return all stored keys. Optional — used by gc and clear_cache."""
        return []


# ---------------------------------------------------------------------------
# Local disk backend
# ---------------------------------------------------------------------------

class LocalDiskCache(CacheBackend):
    """
    Local filesystem cache, sharded by first 2 chars of key.

    Layout:
      <root>/
        <key[:2]>/
          <key[2:]>/
            runtime.tar.zst
            buildtime.tar.zst
            manifest.txt
    """

    def __init__(self, root: Path):
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        log.debug(f"LocalDiskCache: {self._root}")

    def _artifact_path(self, key: str) -> Path:
        return self._root / key[:2] / key[2:]

    def stat(self, key: str) -> bool:
        try:
            return Artifact(self._artifact_path(key)).is_complete()
        except Exception as exc:
            raise CacheError(key, f"stat failed: {exc}") from exc

    def fetch(self, key: str, dest: Path) -> None:
        src = self._artifact_path(key)
        if not Artifact(src).is_complete():
            raise CacheError(key, "artifact not found or incomplete in local cache")
        dest.mkdir(parents=True, exist_ok=True)
        for filename in ("runtime.tar.zst", "buildtime.tar.zst", "manifest.txt"):
            shutil.copy2(src / filename, dest / filename)
        log.debug(f"local fetch {key[:12]} → {dest}")

    def store(self, key: str, src: Path) -> None:
        artifact = Artifact(src)
        if not artifact.is_complete():
            raise CacheError(key, f"source artifact incomplete — missing files in {src}")
        dest = self._artifact_path(key)
        dest.mkdir(parents=True, exist_ok=True)
        for filename in ("runtime.tar.zst", "buildtime.tar.zst", "manifest.txt"):
            shutil.copy2(src / filename, dest / filename)
        log.debug(f"local store {key[:12]} ← {src}")

    def remove(self, key: str) -> None:
        path = self._artifact_path(key)
        if path.exists():
            shutil.rmtree(path)
            log.debug(f"local remove {key[:12]}")
        # Clean up empty shard directory
        shard = path.parent
        try:
            shard.rmdir()   # only succeeds if empty
        except OSError:
            pass

    def list_keys(self) -> list[str]:
        keys = []
        for shard in sorted(self._root.iterdir()):
            if not shard.is_dir() or len(shard.name) != 2:
                continue
            for entry in sorted(shard.iterdir()):
                if entry.is_dir():
                    keys.append(shard.name + entry.name)
        return keys

    def size_bytes(self) -> int:
        """Total size of all cached artifacts."""
        total = 0
        for key in self.list_keys():
            path = self._artifact_path(key)
            for f in path.iterdir():
                total += f.stat().st_size
        return total


# ---------------------------------------------------------------------------
# Local path global backend (for testing / simple shared NFS setups)
# ---------------------------------------------------------------------------

class LocalPathGlobalCache(CacheBackend):
    """
    Global cache backed by a local or NFS path.
    Same layout as LocalDiskCache.
    Used for testing and simple shared-filesystem setups.
    Write requires publish_allowed=True.
    """

    def __init__(self, root: Path, publish_allowed: bool = False):
        self._root            = root.expanduser().resolve()
        self._publish_allowed = publish_allowed
        self._root.mkdir(parents=True, exist_ok=True)

    def _artifact_path(self, key: str) -> Path:
        return self._root / key[:2] / key[2:]

    def stat(self, key: str) -> bool:
        try:
            return Artifact(self._artifact_path(key)).is_complete()
        except Exception as exc:
            raise CacheError(key, f"global stat failed: {exc}") from exc

    def fetch(self, key: str, dest: Path) -> None:
        src = self._artifact_path(key)
        if not Artifact(src).is_complete():
            raise CacheError(key, "artifact not found in global cache")
        dest.mkdir(parents=True, exist_ok=True)
        for filename in ("runtime.tar.zst", "buildtime.tar.zst", "manifest.txt"):
            shutil.copy2(src / filename, dest / filename)

    def store(self, key: str, src: Path) -> None:
        if not self._publish_allowed:
            raise CachePermissionError(
                key,
                "global cache is read-only — use --publish with CI credentials to write"
            )
        artifact = Artifact(src)
        if not artifact.is_complete():
            raise CacheError(key, f"source artifact incomplete in {src}")
        dest = self._artifact_path(key)
        dest.mkdir(parents=True, exist_ok=True)
        for filename in ("runtime.tar.zst", "buildtime.tar.zst", "manifest.txt"):
            shutil.copy2(src / filename, dest / filename)

    def remove(self, key: str) -> None:
        if not self._publish_allowed:
            raise CachePermissionError(key, "global cache is read-only")
        path = self._artifact_path(key)
        if path.exists():
            shutil.rmtree(path)

    def list_keys(self) -> list[str]:
        keys = []
        for shard in sorted(self._root.iterdir()):
            if not shard.is_dir() or len(shard.name) != 2:
                continue
            for entry in sorted(shard.iterdir()):
                if entry.is_dir():
                    keys.append(shard.name + entry.name)
        return keys


# ---------------------------------------------------------------------------
# Two-tier cache — the main interface used by the rest of kiln
# ---------------------------------------------------------------------------

class TieredCache:
    """
    Two-tier cache: local disk with fetch-through from global.

    All callers use this class — they never interact with backends directly.
    The tiering is fully encapsulated here.

    fetch-through behaviour:
      local hit  → copy directly to dest
      global hit → copy to local first, then copy to dest
      both miss  → raise CacheMiss
    """

    def __init__(self, local: CacheBackend, global_: CacheBackend | None = None):
        self._local   = local
        self._global  = global_

    def stat(self, key: str) -> bool:
        """
        True if artifact exists in local or global cache.
        Raises CacheError if either backend is unreachable.
        """
        if self._local.stat(key):
            return True
        if self._global is not None:
            return self._global.stat(key)
        return False

    def fetch(self, key: str, dest: Path) -> None:
        """
        Fetch artifact to dest/.
        Global hits are promoted to local cache first.
        Raises CacheMiss if not found in either tier.
        """
        # Local hit — fast path
        if self._local.stat(key):
            log.debug(f"cache: local hit {key[:12]}")
            self._local.fetch(key, dest)
            return

        # Global hit — fetch-through to local first
        if self._global is not None and self._global.stat(key):
            log.info(f"cache: global hit {key[:12]}, promoting to local")
            # Fetch into a temp location under local cache root, then store
            import tempfile
            with tempfile.TemporaryDirectory(
                dir=self._local._root if hasattr(self._local, '_root') else None
            ) as tmp:
                tmp_path = Path(tmp)
                self._global.fetch(key, tmp_path)
                self._local.store(key, tmp_path)
            # Now serve from local
            self._local.fetch(key, dest)
            return

        raise CacheMiss(key)

    def store_local(self, key: str, src: Path) -> None:
        """Store artifact to local cache only (normal build output)."""
        self._local.store(key, src)
        log.info(f"cache: stored local {key[:12]}")

    def publish(self, key: str, src: Path) -> None:
        """
        Store artifact to both local and global cache.
        Requires global backend to have publish_allowed=True.
        Used by --publish (CI only).
        """
        self._local.store(key, src)
        if self._global is None:
            raise CacheError(key, "no global cache configured — cannot publish")
        self._global.store(key, src)
        log.info(f"cache: published {key[:12]} to global")

    def clear_local(self) -> int:
        """
        Remove all local cache entries.
        Returns count of removed artifacts.
        Always safe — cache is reconstructible.
        """
        keys = self._local.list_keys()
        for key in keys:
            self._local.remove(key)
        log.info(f"cache: cleared {len(keys)} local artifacts")
        return len(keys)

    def local_size_bytes(self) -> int:
        if hasattr(self._local, 'size_bytes'):
            return self._local.size_bytes()
        return 0


# ---------------------------------------------------------------------------
# CacheMiss — distinct from CacheError
# ---------------------------------------------------------------------------

class CacheMiss(Exception):
    """Artifact not found in any cache tier — a build is required."""
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"cache miss: {key[:12]}")


# ---------------------------------------------------------------------------
# Factory — build TieredCache from KilnConfig
# ---------------------------------------------------------------------------


def cache_from_config(config) -> TieredCache:
    """
    Build a TieredCache from a KilnConfig instance.
    Handles the publish_allowed logic based on environment/credentials.
    """
    import os

    local = LocalDiskCache(config.local_cache_dir)

    global_cache = None
    if config.cache.global_url:
        url = config.cache.global_url
        publish_allowed = bool(os.environ.get("KILN_PUBLISH_TOKEN"))

        if url.startswith("/") or url.startswith("~"):
            # Local path global cache (testing / NFS)
            global_cache = LocalPathGlobalCache(
                Path(url).expanduser(),
                publish_allowed=publish_allowed,
            )
        else:
            # Future: S3Backend, HTTPBackend etc.
            log.warning(f"global cache URL '{url}' — no backend implemented yet, skipping")

    return TieredCache(local=local, global_=global_cache)
