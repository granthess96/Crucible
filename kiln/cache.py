"""
kiln/cache.py
Two-tier artifact cache for kiln build artifacts.

Tier 1: Local disk cache  (~/.kiln/cache/ by default)
  - Full read/write for any user
  - Sharded by first 2 chars of manifest hash (git object store layout)
  - Clearable at any time with no side effects except longer build times

Tier 2: Coffer remote cache  (SSH-based, via cachectl on server)
  - Read for all users (fetch-through to local)
  - Write only via --publish flag
  - Fetch-through: remote hit → promote to local → use from local
  - Local hit triggers background LRU touch on remote

Resolution order:
  local hit  → use directly + background LRU touch on remote
  local miss + remote hit → fetch to local → use from local
  both miss  → build required

Each cached component consists of three files:
  <shard>/<rest>/<name>.runtime.tar.zst
  <shard>/<rest>/<name>.buildtime.tar.zst
  <shard>/<rest>/<name>.manifest.txt
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
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

class CacheMiss(Exception):
    """Artifact not found in any cache tier — a build is required."""
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"cache miss: {key[:12]}")

class CofferUnavailable(CacheError):
    """Raised when the Coffer server is unreachable."""
    pass

# ---------------------------------------------------------------------------
# Artifact — what lives at one cache key
# ---------------------------------------------------------------------------

class Artifact:
    """
    The three files that live at one cache key.
    Named by component for human-readable debugging:
      <name>.runtime.tar.zst
      <name>.buildtime.tar.zst
      <name>.manifest.txt
    """
    def __init__(self, base: Path, name: str):
        self.base         = base
        self.name         = name
        self.runtime      = base / f"{name}.runtime.tar.zst"
        self.buildtime    = base / f"{name}.buildtime.tar.zst"
        self.manifest_txt = base / f"{name}.manifest.txt"

    def is_complete(self) -> bool:
        """All three files must exist for the artifact to be valid."""
        return (
            self.runtime.exists()
            and self.buildtime.exists()
            and self.manifest_txt.exists()
        )

    @classmethod
    def find(cls, base: Path) -> "Artifact | None":
        """
        Find an artifact in base/ by scanning for *.manifest.txt.
        Returns None if not found or ambiguous.
        Used when the component name is not known (e.g. cache inspection).
        """
        if not base.exists():
            return None
        manifests = list(base.glob("*.manifest.txt"))
        if len(manifests) != 1:
            return None
        name = manifests[0].name.removesuffix(".manifest.txt")
        return cls(base, name)

    def __repr__(self) -> str:
        ok = "complete" if self.is_complete() else "incomplete"
        return f"<Artifact {self.name} {self.base.parent.name}{self.base.name[-8:]} {ok}>"

# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------

class CacheBackend(ABC):
    """
    Abstract backend — implement for local disk, Coffer SSH, etc.
    All methods raise CacheError on failure.
    """
    @abstractmethod
    def stat(self, key: str, name: str) -> bool:
        """Return True if artifact exists and is complete."""
        ...

    @abstractmethod
    def fetch(self, key: str, name: str, dest: Path) -> None:
        """
        Copy artifact files into dest/.
        dest will be created if it doesn't exist.
        Raises CacheMiss if not present.
        """
        ...

    @abstractmethod
    def store(self, key: str, name: str, src: Path) -> None:
        """
        Store artifact from src/ under key.
        src must contain <name>.runtime.tar.zst, <name>.buildtime.tar.zst,
        <name>.manifest.txt
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
            <name>.runtime.tar.zst
            <name>.buildtime.tar.zst
            <name>.manifest.txt
    """
    def __init__(self, root: Path):
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        log.debug(f"LocalDiskCache: {self._root}")

    def _artifact_path(self, key: str) -> Path:
        return self._root / key[:2] / key[2:]

    def stat(self, key: str, name: str) -> bool:
        try:
            return Artifact(self._artifact_path(key), name).is_complete()
        except Exception as exc:
            raise CacheError(key, f"stat failed: {exc}") from exc

    def fetch(self, key: str, name: str, dest: Path) -> None:
        src      = self._artifact_path(key)
        artifact = Artifact(src, name)
        if not artifact.is_complete():
            raise CacheMiss(key)
        dest.mkdir(parents=True, exist_ok=True)
        for f in (artifact.runtime, artifact.buildtime, artifact.manifest_txt):
            shutil.copy2(f, dest / f.name)
        log.debug(f"local fetch {key[:12]} → {dest}")

    def store(self, key: str, name: str, src: Path) -> None:
        artifact = Artifact(src, name)
        if not artifact.is_complete():
            raise CacheError(key, f"source artifact incomplete — missing files in {src}")
        dest = self._artifact_path(key)
        dest.mkdir(parents=True, exist_ok=True)
        for f in (artifact.runtime, artifact.buildtime, artifact.manifest_txt):
            shutil.copy2(f, dest / f.name)
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
# Coffer SSH backend
# ---------------------------------------------------------------------------

class CofferBackend(CacheBackend):
    """
    Remote artifact cache backend using Coffer (cachectl) over SSH + SCP.

    Protocol:
      stat:    ssh <host> cachectl test <hash>        exit 0=hit, 2=miss
      fetch:   ssh <host> cachectl fetch <hash>       → prints server path
               scp <host>:<path>/* <local_dest>/
      store:   ssh <host> cachectl get-bucket         → prints staging path
               scp <local_src>/* <host>:<staging>/
               ssh <host> cachectl publish <staging> <hash>
      lru:     ssh <host> cachectl test <hash>        (fire-and-forget)

    Raises CofferUnavailable on SSH connection failure.
    Raises CacheMiss on stat/fetch miss.
    
    cachectl path on server: /home/<user>/bin/cachectl
    where <user> is parsed from coffer_host (user@hostname).
    """

    def __init__(self, host: str, port: int = 22,
                 cachectl_path: str | None = None,                 
                 ssh_timeout: int = 10):
        self._host            = host          # user@hostname
        self._port            = port
        self._timeout         = ssh_timeout

        # Derive cachectl path from username if not explicit
        if cachectl_path:
            self._cachectl = cachectl_path
        else:
            user = host.split("@")[0] if "@" in host else "cache"
            self._cachectl = f"/home/{user}/bin/cachectl"

        log.debug(f"CofferBackend: {self._host}:{self._port} cachectl={self._cachectl}")

    def _ssh(self, *remote_args: str,
             capture: bool = True,
             check: bool = True) -> subprocess.CompletedProcess:
        """
        Run a remote cachectl command via SSH.
        Raises CofferUnavailable on connection failure.
        """
        cmd = [
            "ssh",
            "-p", str(self._port),
            "-o", "BatchMode=yes",                  # never prompt for password
            "-o", f"ConnectTimeout={self._timeout}",
            "-o", "StrictHostKeyChecking=accept-new",
            self._host,
            self._cachectl, *remote_args,
        ]
        log.debug(f"coffer ssh: {' '.join(remote_args)}")
        try:
            return subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                check=False,       # we inspect returncode ourselves
            )
        except FileNotFoundError:
            raise CofferUnavailable("", "ssh not found in PATH")
        except OSError as exc:
            raise CofferUnavailable("", f"SSH failed: {exc}")

    def _scp_get(self, remote_path: str, local_dest: Path) -> None:
        """SCP files from remote_path/* into local_dest/."""
        local_dest.mkdir(parents=True, exist_ok=True)
        cmd = [
            "scp", "-P", str(self._port),
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self._timeout}",
            f"{self._host}:{remote_path}/*",
            str(local_dest) + "/",
        ]
        log.debug(f"coffer scp get: {remote_path}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:
            raise CofferUnavailable("", f"SCP failed: {exc}")
        if result.returncode != 0:
            raise CacheError("", f"SCP fetch failed: {result.stderr.strip()}")

    def _scp_put(self, local_src: Path, remote_path: str) -> None:
        """SCP all files from local_src/ into remote_path/."""
        files = [str(f) for f in local_src.iterdir() if f.is_file()]
        if not files:
            raise CacheError("", f"No files to upload from {local_src}")
        cmd = [
            "scp", "-P", str(self._port),
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self._timeout}",
            *files,
            f"{self._host}:{remote_path}/",
        ]
        log.debug(f"coffer scp put: {len(files)} files → {remote_path}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:
            raise CofferUnavailable("", f"SCP failed: {exc}")
        if result.returncode != 0:
            raise CacheError("", f"SCP upload failed: {result.stderr.strip()}")

    def _is_connection_error(self, result: subprocess.CompletedProcess) -> bool:
        """Distinguish SSH connection failure from a clean cachectl response."""
        # SSH exits 255 on connection errors; cachectl uses 0, 1, 2
        return result.returncode == 255

    def stat(self, key: str, name: str) -> bool:
        """
        Return True if artifact exists on Coffer server.
        Raises CofferUnavailable on connection failure.
        """
        result = self._ssh("test", key)
        if self._is_connection_error(result):
            raise CofferUnavailable(key, f"SSH connection failed: {result.stderr.strip()}")
        if result.returncode == 0:
            log.debug(f"coffer stat hit {key[:12]}")
            return True
        if result.returncode == 2:
            log.debug(f"coffer stat miss {key[:12]}")
            return False
        raise CacheError(key, f"cachectl test error (rc={result.returncode}): {result.stderr.strip()}")

    def lru_touch(self, key: str) -> None:
        """
        Fire-and-forget background LRU touch on the server.
        Called after a local cache hit to keep the remote entry warm.
        Never raises — failures are logged and silently dropped.
        """
        def _touch():
            try:
                result = self._ssh("test", key)
                if self._is_connection_error(result):
                    log.debug(f"coffer lru touch skipped (unreachable): {key[:12]}")
                else:
                    log.debug(f"coffer lru touch {key[:12]}")
            except Exception as exc:
                log.debug(f"coffer lru touch failed (ignored): {exc}")

        t = threading.Thread(target=_touch, daemon=True, name=f"coffer-lru-{key[:8]}")
        t.start()

    def fetch(self, key: str, name: str, dest: Path) -> None:
        """
        Fetch artifact from Coffer into dest/.
        Raises CofferUnavailable on connection failure.
        Raises CacheMiss if not present.
        """
        result = self._ssh("fetch", key)
        if self._is_connection_error(result):
            raise CofferUnavailable(key, f"SSH connection failed: {result.stderr.strip()}")
        if result.returncode == 2:
            raise CacheMiss(key)
        if result.returncode != 0:
            raise CacheError(key, f"cachectl fetch error: {result.stderr.strip()}")

        remote_path = result.stdout.strip()
        if not remote_path:
            raise CacheError(key, "cachectl fetch returned empty path")

        self._scp_get(remote_path, dest)
        log.info(f"coffer fetch {key[:12]} → {dest}")

    def store(self, key: str, name: str, src: Path) -> None:
        """
        Publish artifact from src/ to Coffer.
        Raises CachePermissionError if not authorized.
        Raises CofferUnavailable on connection failure.
        """

        artifact = Artifact(src, name)
        if not artifact.is_complete():
            raise CacheError(key, f"source artifact incomplete in {src}")

        # Allocate staging bucket
        result = self._ssh("get-bucket")
        if self._is_connection_error(result):
            raise CofferUnavailable(key, f"SSH connection failed: {result.stderr.strip()}")
        if result.returncode != 0:
            raise CacheError(key, f"cachectl get-bucket failed: {result.stderr.strip()}")

        staging_path = result.stdout.strip()
        if not staging_path:
            raise CacheError(key, "cachectl get-bucket returned empty path")

        # Upload artifacts into staging bucket
        self._scp_put(src, staging_path)

        # Atomic publish
        result = self._ssh("publish", staging_path, key)
        if self._is_connection_error(result):
            raise CofferUnavailable(key, f"SSH connection failed during publish: {result.stderr.strip()}")
        if result.returncode != 0:
            raise CacheError(key, f"cachectl publish failed: {result.stderr.strip()}")

        log.info(f"coffer publish {key[:12]} complete")

    def remove(self, key: str) -> None:
        """Not supported on remote Coffer — GC is server-side only."""
        raise CachePermissionError(key, "remote Coffer entries are managed by server-side GC")

    def list_keys(self) -> list[str]:
        """Not supported — Coffer does not expose key enumeration."""
        return []

# ---------------------------------------------------------------------------
# Two-tier cache — the main interface used by the rest of kiln
# ---------------------------------------------------------------------------

class TieredCache:
    """
    Two-tier cache: local disk with fetch-through from Coffer remote.

    Read path:
      local hit  → use directly + background LRU touch on Coffer
      local miss + Coffer hit → fetch-through, promote to local, use local
      local miss + Coffer unreachable → CofferUnavailable (hard fail)
      both miss  → CacheMiss

    Write path:
      store_local  → local only (normal build output)
      publish      → local + Coffer (requires --publish / CI credentials)
    """
    def __init__(self, local: LocalDiskCache,
                 coffer: CofferBackend | None = None):
        self._local  = local
        self._coffer = coffer

    def stat(self, key: str, name: str) -> bool:
        """
        True if artifact exists in local or Coffer cache.
        Local hit: True immediately (no remote call on the critical path).
        Local miss: probe Coffer; CofferUnavailable propagates to caller.
        """
        if self._local.stat(key, name):
            return True
        if self._coffer is not None:
            return self._coffer.stat(key, name)
        return False

    def fetch(self, key: str, name: str, dest: Path) -> None:
        """
        Fetch artifact to dest/.
        Local hit: copy directly + fire background LRU touch on Coffer.
        Local miss: fetch from Coffer, promote to local, then copy to dest.
        Raises CacheMiss, CofferUnavailable, or CacheError.
        """
        if self._local.stat(key, name):
            log.debug(f"cache: local hit {key[:12]}")
            self._local.fetch(key, name, dest)
            # Background LRU touch — never blocks the build
            if self._coffer is not None:
                self._coffer.lru_touch(key)
            return

        if self._coffer is not None:
            # CofferUnavailable and CacheMiss propagate to caller
            log.info(f"cache: local miss {key[:12]}, trying Coffer")
            import tempfile
            with tempfile.TemporaryDirectory(prefix="kiln-coffer-") as tmp:
                tmp_path = Path(tmp)
                self._coffer.fetch(key, name, tmp_path)   # raises on miss/error
                self._local.store(key, name, tmp_path)     # promote to local
            self._local.fetch(key, name, dest)
            log.info(f"cache: Coffer fetch-through {key[:12]} complete")
            return

        raise CacheMiss(key)

    def store_local(self, key: str, name: str, src: Path) -> None:
        """Store artifact to local cache only (normal build output)."""
        self._local.store(key, name, src)
        log.info(f"cache: stored local {key[:12]}")

    def publish(self, key: str, name: str, src: Path) -> None:
        """
        Store artifact to local cache and push to Coffer.
        Used by --publish (CI or explicit developer publish).
        """
        self._local.store(key, name, src)
        if self._coffer is None:
            raise CacheError(key, "no Coffer remote configured — set coffer_host in forge.toml")
        self._coffer.store(key, name, src)
        log.info(f"cache: published {key[:12]} to Coffer")

    def clear_local(self) -> int:
        """
        Remove all local cache entries.
        Returns count of removed artifacts.
        Always safe — cache is reconstructible from Coffer or by rebuilding.
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
# Factory — build TieredCache from CrucibleConfig
# ---------------------------------------------------------------------------

def cache_from_config(config) -> TieredCache:
    """
    Build a TieredCache from a CrucibleConfig instance.

    Coffer is enabled when coffer_host is set in [cache].
    """
    import os

    local = LocalDiskCache(config.local_cache_dir)

    coffer: CofferBackend | None = None
    if config.cache.coffer_host:        
        coffer = CofferBackend(
            host            = config.cache.coffer_host,
            port            = config.cache.coffer_port,
            cachectl_path   = config.cache.coffer_cachectl or None,
            ssh_timeout     = config.cache.coffer_ssh_timeout,
        )
        log.debug(f"Coffer remote: {config.cache.coffer_host} ")
                  
    return TieredCache(local=local, coffer=coffer)