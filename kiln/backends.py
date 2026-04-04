"""
kiln/backends.py
Cache and registry backend adapters used by the DAG resolver,
plus a shared resolver factory to eliminate duplicated setup.
"""
from __future__ import annotations
import sys
from kiln.dag import (
    Resolver, CacheBackend, RegistryBackend,
    KilnLock, ResolveError, ResolvedDAG,
)
from kiln.cache import (
    TieredCache, Artifact, CofferUnavailable,
)
# ---------------------------------------------------------------------------
# Backend adapters
# ---------------------------------------------------------------------------
class _CacheStatAdapter(CacheBackend):
    """
    Adapter used by the DAG resolver -- checks cache existence by key only,
    without needing the component name. Uses Artifact.find() to scan by glob.
    Checks local first, then Coffer if configured. A CofferUnavailable during
    deps resolution is treated as a miss with a warning -- deps is informational
    and a network blip should not prevent the report from completing.
    """
    def __init__(self, tiered: TieredCache):
        self._t = tiered

    def stat(self, key: str) -> bool:
        # Local check -- scan for any *.manifest.txt in the shard directory
        local = self._t._local
        if hasattr(local, '_artifact_path'):
            artifact = Artifact.find(local._artifact_path(key))
            if artifact is not None and artifact.is_complete():
                return True
        # Coffer check -- network call, failure is a warning not an error here
        if self._t._coffer is not None:
            try:
                return self._t._coffer.stat(key, "")
            except CofferUnavailable as exc:
                print(
                    f"  WARNING: Coffer unreachable during deps stat: {exc.reason}",
                    file=sys.stderr,
                )
                return False
        return False


class _RegistryStatAdapter(RegistryBackend):
    def stat(self, key: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Shared resolver factory
# ---------------------------------------------------------------------------
def make_resolver(config, cache: TieredCache) -> Resolver:
    """
    Build a Resolver from config and cache.
    Centralises the repeated four-argument setup that was duplicated across
    verb_deps, _populate_sysroot, and verb_package
    """
    lock = KilnLock(config.lock_file)
    return Resolver(
        components_root = config.components_dir,
        cache           = _CacheStatAdapter(cache),
        registry        = _RegistryStatAdapter(),
        lock            = lock,
        forge_base_hash = config.forge.base_image or "sha256:unconfigured",
        max_weight      = config.scheduler.max_weight,
        bootstrap_stage = config.build.bootstrap_stage,
    )