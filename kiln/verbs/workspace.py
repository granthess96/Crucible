"""
kiln/verbs/workspace.py
Workspace management verbs: clean, purge, clear_cache.
clean       -- wipe __build__/ and __install__/, leave source and sysroot
purge       -- wipe everything including source and build state
clear_cache -- remove all local cache entries
"""
from __future__ import annotations
import shutil
import sys
from kiln.output import Reporter, Status
from kiln.cache import TieredCache


def verb_clean(target: str, config, reporter: Reporter) -> bool:
    """Wipe __build__/ and __install__/ -- keep source and sysroot."""
    component_dir = config.components_dir / target
    for d in ("__build__", "__install__"):
        path = component_dir / d
        if path.exists():
            shutil.rmtree(path)
            path.mkdir()
            print(f"  {target}: cleared {d}/")

    reporter.update(target, Status.OK)
    return True


def verb_purge(target: str, config, reporter: Reporter) -> bool:
    """Wipe everything -- source, sysroot, build, install."""
    component_dir = config.components_dir / target
    for d in ("__source__", "__sysroot__", "__build__", "__install__"):
        path = component_dir / d
        if path.exists():
            shutil.rmtree(path)
            print(f"  {target}: cleared {d}/")

    reporter.update(target, Status.OK)
    return True


def verb_clear_cache(config, cache: TieredCache) -> bool:
    """Remove all local cache entries."""
    size_before = cache.local_size_bytes()
    count       = cache.clear_local()
    size_mb     = size_before / (1024 * 1024)
    print(f"Cleared {count} artifacts ({size_mb:.1f} MB) from local cache.")
    print(f"Cache: {config.local_cache_dir}")
    return True