"""
kiln/fetcher.py
Source fetcher — manages local source caches and exports source trees
into component build directories.

Two source types are supported:

  git     source = {'git': '<url>', 'ref': '<tag|sha|branch>'}
          - Bare clone cache in .kiln/git-cache/<name>.git
          - Ref resolved to SHA once, written to kiln.lock
          - Subsequent fetches use locked SHA — tags not trusted as immutable
          - Branches warn loudly (moving target)

  tarball source = {'url': '<url>'}
          - Tarball cached in .kiln/tarball-cache/<name>/<filename>
          - sha256 computed on first download, written to kiln.lock
          - Subsequent fetches verify sha256 matches lock — mismatch is hard error
          - URL stored in lock to detect build.py url changes
          - No extraction at fetch time — checkout verb handles extraction

Both fetchers write to kiln.lock and return a source identity string:
  git     → commit SHA  (40 hex chars)
  tarball → sha256 hex  (64 hex chars)

The identity string is written to .kiln/state/<name>/source_id by verb_fetch,
and read back by verb_checkout to locate the cached source.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.request
from pathlib import Path

import git
from git.exc import GitCommandError, InvalidGitRepositoryError

from kiln.dag import KilnLock, _source_type

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class FetchError(Exception):
    """Raised when source cannot be fetched or verified."""
    def __init__(self, component: str, reason: str):
        self.component = component
        self.reason    = reason
        super().__init__(f"{component}: {reason}")

# ---------------------------------------------------------------------------
# Ref classification helpers (git)
# ---------------------------------------------------------------------------

def _looks_like_sha(ref: str) -> bool:
    """True if ref looks like a full or abbreviated commit SHA."""
    if len(ref) < 7 or len(ref) > 40:
        return False
    try:
        int(ref, 16)
        return True
    except ValueError:
        return False


def _is_branch(repo: git.Repo, ref: str) -> bool:
    """True if ref names a remote branch."""
    try:
        repo.remotes.origin.refs[ref]
        return True
    except (IndexError, AttributeError):
        pass
    try:
        repo.commit(f"origin/{ref}")
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Git fetcher
# ---------------------------------------------------------------------------

class Fetcher:
    """
    Manages bare clone cache and source export for git-sourced components.
    git_cache_dir: typically <build_root>/.kiln/git-cache/
    lock:          KilnLock instance (shared with resolver)
    """

    def __init__(self, git_cache_dir: Path, lock: KilnLock):
        self._cache = git_cache_dir
        self._lock  = lock
        self._cache.mkdir(parents=True, exist_ok=True)

    def fetch(self, component_name: str, source: dict) -> str:
        """
        Ensure source is fetched and SHA is locked.
        Returns the resolved commit SHA.
        """
        url = source.get("git")
        ref = source.get("ref")
        if not url:
            raise FetchError(component_name, "source.git is required")
        if not ref:
            raise FetchError(component_name, "source.ref is required")

        bare_repo = self._ensure_bare_clone(component_name, url)
        sha       = self._resolve_and_lock(component_name, bare_repo, ref)
        return sha

    def verify_locked(self, component_name: str) -> bool:
        """
        Returns True if the locked SHA exists in the bare clone.
        Used by the resolver to confirm fetch state without re-fetching.
        """
        sha = self._lock.get_commit(component_name)
        if sha is None:
            return False
        bare_path = self._bare_path(component_name)
        if not bare_path.exists():
            return False
        try:
            repo = git.Repo(bare_path)
            repo.commit(sha)
            return True
        except Exception:
            return False

    def _bare_path(self, component_name: str) -> Path:
        return self._cache / f"{component_name}.git"

    def _ensure_bare_clone(self, component_name: str, url: str) -> git.Repo:
        import subprocess
        bare_path = self._bare_path(component_name)

        if bare_path.exists():
            try:
                repo = git.Repo(bare_path)
                log.info(f"{component_name}: fetching updates from {url}")
                result = subprocess.run(
                    ["git", "fetch", "--prune", "--tags",
                     "--filter=blob:none", "--depth=1", "origin"],
                    cwd=bare_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise GitCommandError("git fetch", result.returncode,
                                          result.stderr.strip())
                return repo
            except (InvalidGitRepositoryError, GitCommandError) as exc:
                log.warning(f"{component_name}: bare clone unusable, re-cloning: {exc}")
                shutil.rmtree(bare_path)

        log.info(f"{component_name}: cloning {url}")
        try:
            result = subprocess.run(
                ["git", "clone", "--bare", "--filter=blob:none", "--depth=1",
                 url, str(bare_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise FetchError(component_name,
                    f"git clone failed: {result.stderr.strip()}")
            repo = git.Repo(bare_path)
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(component_name, f"git clone failed: {exc}") from exc

        return repo

    def _resolve_and_lock(
        self,
        component_name: str,
        repo:           git.Repo,
        ref:            str,
    ) -> str:
        locked_sha = self._lock.get_commit(component_name)
        if locked_sha:
            self._verify_sha_exists(component_name, repo, locked_sha)
            log.debug(f"{component_name}: using locked SHA {locked_sha[:12]}")
            return locked_sha

        if _looks_like_sha(ref):
            sha = self._resolve_sha(component_name, repo, ref)
        else:
            if _is_branch(repo, ref):
                log.warning(
                    f"{component_name}: ref '{ref}' is a branch (moving target). "
                    f"Consider pinning to a tag or SHA for reproducible builds."
                )
            sha = self._resolve_ref(component_name, repo, ref)

        log.info(f"{component_name}: locked {ref} → {sha}")
        self._lock.set_commit(component_name, sha)
        self._lock.write()
        return sha

    def _resolve_ref(self, component_name: str, repo: git.Repo, ref: str) -> str:
        try:
            return repo.commit(ref).hexsha
        except Exception:
            pass
        try:
            return repo.commit(f"origin/{ref}").hexsha
        except Exception:
            pass
        raise FetchError(
            component_name,
            f"ref '{ref}' not found in {repo.remotes.origin.url}"
        )

    def _resolve_sha(self, component_name: str, repo: git.Repo, sha: str) -> str:
        try:
            return repo.commit(sha).hexsha
        except Exception:
            raise FetchError(
                component_name,
                f"SHA '{sha}' not found in {repo.remotes.origin.url}"
            )

    def _verify_sha_exists(
        self,
        component_name: str,
        repo:           git.Repo,
        sha:            str,
    ) -> None:
        try:
            repo.commit(sha)
        except Exception:
            raise FetchError(
                component_name,
                f"locked SHA '{sha[:12]}' not found in bare clone — "
                f"run `kiln fetch` to update"
            )

# ---------------------------------------------------------------------------
# Tarball fetcher
# ---------------------------------------------------------------------------

class TarballFetcher:
    """
    Manages tarball download cache for url-sourced components.
    tarball_cache_dir: typically <build_root>/.kiln/tarball-cache/
    lock:              KilnLock instance (shared with resolver and git Fetcher)

    Cache layout:
      <tarball_cache_dir>/
        <component_name>/
          <filename>          (e.g. coreutils-9.5.tar.xz)

    Only one tarball is kept per component — re-fetching replaces it.
    The lock records the sha256 and url so we can detect staleness.
    """

    def __init__(self, tarball_cache_dir: Path, lock: KilnLock):
        self._cache = tarball_cache_dir
        self._lock  = lock
        self._cache.mkdir(parents=True, exist_ok=True)

    def fetch(self, component_name: str, source: dict) -> str:
        """
        Ensure tarball is downloaded and sha256 is locked.
        Returns the sha256 hex string.

        First fetch:
          - Download tarball, compute sha256
          - Write sha256 + url to kiln.lock
          - Cache tarball

        Subsequent fetches (lock already has sha256):
          - If cached tarball exists and sha256 matches → skip download
          - If cached tarball missing → re-download, verify sha256 matches lock
          - If sha256 mismatch → hard error (upstream content changed)

        URL change detection:
          - If url in build.py differs from url in lock → warn, re-download,
            verify new sha256 matches locked sha256 (url redirect is ok,
            content change is not)
        """
        url = source.get("url")
        if not url:
            raise FetchError(component_name, "source.url is required for tarball fetch")

        filename    = _filename_from_url(url)
        cache_dir   = self._cache / component_name
        cache_dir.mkdir(exist_ok=True)
        cached_path = cache_dir / filename

        locked_sha256 = self._lock.get_sha256(component_name)
        locked_url    = self._lock.get_url(component_name)

        # Detect URL change in build.py
        if locked_url and locked_url != url:
            log.warning(
                f"{component_name}: URL in build.py differs from locked URL.\n"
                f"  locked:  {locked_url}\n"
                f"  current: {url}\n"
                f"  Re-downloading to verify sha256 is unchanged."
            )
            # Remove cached file to force re-download
            if cached_path.exists():
                cached_path.unlink()
            # Update the locked url — if sha256 still matches, all is well
            self._lock.set_url(component_name, url)

        # Fast path — cached and locked, verify without re-downloading
        if locked_sha256 and cached_path.exists():
            actual_sha256 = _sha256_file(cached_path)
            if actual_sha256 == locked_sha256:
                log.debug(f"{component_name}: tarball cache hit {locked_sha256[:16]}")
                return locked_sha256
            else:
                log.warning(
                    f"{component_name}: cached tarball sha256 mismatch — re-downloading.\n"
                    f"  expected: {locked_sha256}\n"
                    f"  actual:   {actual_sha256}"
                )
                cached_path.unlink()

        # Download
        log.info(f"{component_name}: downloading {url}")
        _download(url, cached_path)
        actual_sha256 = _sha256_file(cached_path)

        if locked_sha256:
            # Lock already set — verify downloaded bytes match
            if actual_sha256 != locked_sha256:
                cached_path.unlink()
                raise FetchError(
                    component_name,
                    f"tarball sha256 mismatch — upstream content may have changed!\n"
                    f"  locked:   {locked_sha256}\n"
                    f"  actual:   {actual_sha256}\n"
                    f"  url:      {url}\n"
                    f"  If this is intentional, remove the {component_name}.sha256 "
                    f"entry from kiln.lock and re-run kiln fetch."
                )
            log.info(f"{component_name}: sha256 verified {actual_sha256[:16]}")
        else:
            # First fetch — establish the lock
            log.info(f"{component_name}: locked sha256 {actual_sha256[:16]} for {url}")
            self._lock.set_sha256(component_name, actual_sha256)
            self._lock.set_url(component_name, url)
            self._lock.write()

        return actual_sha256

    def cached_path(self, component_name: str, source: dict) -> Path | None:
        """
        Return the path to the cached tarball if it exists and sha256 matches lock.
        Returns None if not cached or verification fails.
        Used by verb_checkout to locate the tarball for extraction.
        """
        url = source.get("url")
        if not url:
            return None

        locked_sha256 = self._lock.get_sha256(component_name)
        if not locked_sha256:
            return None

        filename    = _filename_from_url(url)
        cached_path = self._cache / component_name / filename

        if not cached_path.exists():
            return None

        if _sha256_file(cached_path) != locked_sha256:
            return None

        return cached_path

# ---------------------------------------------------------------------------
# Tarball helpers
# ---------------------------------------------------------------------------

def _filename_from_url(url: str) -> str:
    """Extract filename from URL, stripping query strings."""
    return url.split("?")[0].rstrip("/").split("/")[-1]


def _sha256_file(path: Path) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    """
    Download url to dest. Shows progress to stderr for large files.
    Uses urllib — no external dependencies.
    """
    import sys

    try:
        with urllib.request.urlopen(url) as response:
            total = response.headers.get("Content-Length")
            total_bytes = int(total) if total else None
            downloaded  = 0
            chunk_size  = 1 << 20   # 1 MiB

            with dest.open("wb") as out:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes and sys.stderr.isatty():
                        pct = downloaded * 100 // total_bytes
                        mb  = downloaded / (1 << 20)
                        print(
                            f"\r  downloading {dest.name}: {mb:.1f} MiB ({pct}%)",
                            end="",
                            file=sys.stderr,
                        )

            if total_bytes and sys.stderr.isatty():
                print(file=sys.stderr)   # newline after progress

    except Exception as exc:
        if dest.exists():
            dest.unlink()
        raise FetchError("", f"download failed: {url}: {exc}") from exc