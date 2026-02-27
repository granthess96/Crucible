"""
kiln/fetcher.py

Source fetcher — manages a local bare clone cache and exports source trees
into forge instance directories.

Design:
  - One bare clone per component in .kiln/git-cache/<name>.git
  - Bare clones persist across builds — fetch updates them, never re-clone from scratch
  - ref in build.py is resolved to a SHA once, written to kiln.lock
  - Subsequent fetches use the locked SHA — tags are not trusted to be immutable
  - Source is exported (not checked out) into the forge instance src/ dir
    so the build directory has no .git metadata and no accidental git operations

Ref handling:
  tag    → resolve once, lock, never re-resolve
  SHA    → verify exists, write directly to lock
  branch → resolve on every fetch (dev workflow), warn loudly
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import git                        # gitpython
from git.exc import GitCommandError, InvalidGitRepositoryError

from kiln.dag import KilnLock

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
# Ref classification
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
    # Also check refs/remotes/origin/<ref>
    try:
        repo.commit(f"origin/{ref}")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class Fetcher:
    """
    Manages bare clone cache and source export for kiln builds.

    git_cache_dir: typically <build_root>/.kiln/git-cache/
    lock:          KilnLock instance (shared with resolver)
    """

    def __init__(self, git_cache_dir: Path, lock: KilnLock):
        self._cache = git_cache_dir
        self._lock  = lock
        self._cache.mkdir(parents=True, exist_ok=True)

    # --- Public API (one method per kiln fetch concern) ---

    def fetch(self, component_name: str, source: dict) -> str:
        """
        Ensure source is fetched and SHA is locked.
        Returns the resolved commit SHA.

        This is the implementation of `kiln fetch`.
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

    def export(self, component_name: str, dest: Path) -> None:
        """
        Export the locked source tree into dest/.
        dest must exist and should be empty.

        Uses git archive — dest has no .git metadata.
        """
        sha = self._lock.get_commit(component_name)
        if sha is None:
            raise FetchError(
                component_name,
                "no locked SHA — run `kiln fetch` before `kiln configure`"
            )

        bare_path = self._bare_path(component_name)
        if not bare_path.exists():
            raise FetchError(
                component_name,
                "bare clone missing — run `kiln fetch` first"
            )

        repo = git.Repo(bare_path)
        self._verify_sha_exists(component_name, repo, sha)

        log.debug(f"{component_name}: exporting {sha[:12]} → {dest}")

        # git archive exports a clean tree with no .git directory
        # This is intentional — builds must not be able to run git commands
        # against the source tree and accidentally pick up uncommitted state
        archive_stream = repo.archive(
            dest,
            treeish=sha,
            format="tar",
        )

        # git.Repo.archive writes directly to a path if given a Path —
        # but to extract we need to untar. Use prefix="" for no subdirectory.
        # Re-implement with subprocess for clarity and control.
        import subprocess, tempfile

        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            subprocess.run(
                ["git", "archive", "--format=tar", f"--output={tmp_path}", sha],
                cwd=bare_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["tar", "x", "-f", str(tmp_path), "-C", str(dest)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            raise FetchError(
                component_name,
                f"source export failed: {exc.stderr.decode().strip()}"
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        log.debug(f"{component_name}: export complete")

    def verify_locked(self, component_name: str, source: dict) -> bool:
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

    # --- Internal ---

    def _bare_path(self, component_name: str) -> Path:
        return self._cache / f"{component_name}.git"

    def _ensure_bare_clone(self, component_name: str, url: str) -> git.Repo:
        """
        Return a bare clone repo, creating or updating as needed.
        Always fetches to ensure we have the latest refs.
        Uses subprocess git directly for fetch — more reliable than gitpython
        for bare clone refspec handling.
        """
        import subprocess
        bare_path = self._bare_path(component_name)

        if bare_path.exists():
            try:
                repo = git.Repo(bare_path)
                log.info(f"{component_name}: fetching updates from {url}")
                # Use subprocess git directly — bare clones from gitpython
                # may not have the default refspec set, causing fetch to fail
                result = subprocess.run(
                    ["git", "fetch", "--prune", "--tags", "origin"],
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

        # Fresh bare clone — use subprocess for consistency
        log.info(f"{component_name}: cloning {url}")
        try:
            result = subprocess.run(
                ["git", "clone", "--bare", "--filter=blob:none", url, str(bare_path)],
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
            raise FetchError(
                component_name,
                f"git clone failed: {exc}"
            ) from exc

        return repo

    def _resolve_and_lock(
        self,
        component_name: str,
        repo:           git.Repo,
        ref:            str,
    ) -> str:
        """
        Resolve ref to a SHA. If already locked, verify and return locked SHA.
        Warns if ref is a branch (moving target).
        """
        locked_sha = self._lock.get_commit(component_name)

        if locked_sha:
            # Already locked — verify it still exists, return it
            self._verify_sha_exists(component_name, repo, locked_sha)
            log.debug(f"{component_name}: using locked SHA {locked_sha[:12]}")
            return locked_sha

        # Not yet locked — resolve the ref
        if _looks_like_sha(ref):
            sha = self._resolve_sha(component_name, repo, ref)
        else:
            # Check if it's a branch — warn if so
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
        """Resolve a tag or branch name to a commit SHA."""
        try:
            commit = repo.commit(ref)
            return commit.hexsha
        except Exception:
            pass
        # Try with origin/ prefix for remote branches
        try:
            commit = repo.commit(f"origin/{ref}")
            return commit.hexsha
        except Exception:
            pass
        raise FetchError(
            component_name,
            f"ref '{ref}' not found in {repo.remotes.origin.url}"
        )

    def _resolve_sha(self, component_name: str, repo: git.Repo, sha: str) -> str:
        """Verify a SHA exists and return the full 40-char version."""
        try:
            commit = repo.commit(sha)
            return commit.hexsha    # always returns full SHA
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
        """Raise FetchError if SHA is not present in the bare clone."""
        try:
            repo.commit(sha)
        except Exception:
            raise FetchError(
                component_name,
                f"locked SHA '{sha[:12]}' not found in bare clone — "
                f"run `kiln fetch` to update"
            )