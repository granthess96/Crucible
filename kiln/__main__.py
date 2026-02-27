"""
kiln/__main__.py

CLI entry point for kiln.

Usage (from any directory inside a build tree):
    kiln <verb> [verb ...] [options]

Verbs (run in the order given, stop on first failure):
    deps        resolve DAG, stat cache/registry, report hits/misses
    fetch       git fetch source into bare clone cache
    configure   run build system configure step
    build       compile
    test        run test suite
    install     DESTDIR install into empty directory
    package     split install tree → runtime + buildtime tarballs, store in cache
    clean       wipe build directory, leave source
    purge       wipe everything including source and build state

    clear_cache remove all local cache entries

Options:
    --verbose   single worker, stream build output to terminal
    --no-tty    plain line-per-completion output (auto if not a terminal)
    --publish   push artifacts to global cache after package (CI only)
    --target    component name to build (default: inferred from cwd)
    --weight    override max_weight for this run

Examples:
    # From a component directory — builds that component and its deps
    cd components/rocm-hip
    kiln deps
    kiln deps fetch configure build test install package

    # Chain verbs
    kiln deps configure build

    # CI cache warming
    kiln deps --publish

    # Verbose debug session
    kiln fetch configure build --verbose
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure the package is importable when run as python -m kiln or ./kiln
_here = Path(__file__).parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from kiln.config import load_config, ConfigError
from kiln.dag import (
    Resolver, ResolvedDAG, BuildSchedule, ResolveError,
    KilnLock, CacheBackend, RegistryBackend,
)
from kiln.cache import TieredCache, cache_from_config, CacheMiss, CacheError
from kiln.output import Reporter, Status, OutputMode, detect_output_mode


# ---------------------------------------------------------------------------
# Valid verbs and their order
# ---------------------------------------------------------------------------

ALL_VERBS = [
    "deps",
    "fetch",
    "configure",
    "build",
    "test",
    "install",
    "package",
    "clean",
    "purge",
    "clear_cache",
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "kiln",
        description = "Meta-build tool for forge-based component builds.",
        add_help    = True,
    )
    parser.add_argument(
        "verbs",
        nargs   = "+",
        metavar = "verb",
        choices = ALL_VERBS,
        help    = f"one or more of: {', '.join(ALL_VERBS)}",
    )
    parser.add_argument(
        "--verbose",
        action  = "store_true",
        help    = "stream build output to terminal (implies single worker)",
    )
    parser.add_argument(
        "--no-tty",
        action  = "store_true",
        dest    = "no_tty",
        help    = "plain line-per-completion output (auto-detected if not a terminal)",
    )
    parser.add_argument(
        "--publish",
        action  = "store_true",
        help    = "push artifacts to global cache after package (CI credentials required)",
    )
    parser.add_argument(
        "--target",
        metavar = "COMPONENT",
        default = None,
        help    = "component to build (default: inferred from current directory)",
    )
    parser.add_argument(
        "--weight",
        metavar = "N",
        type    = int,
        default = None,
        help    = "override max_weight for this run",
    )
    return parser


# ---------------------------------------------------------------------------
# Target inference — infer component name from cwd
# ---------------------------------------------------------------------------

def infer_target(config, cwd: Path) -> str | None:
    """
    If cwd is components/<name>/ return <name>.
    If cwd is the build root, return None (caller must require --target).
    """
    try:
        rel = cwd.resolve().relative_to(config.components_dir.resolve())
        parts = rel.parts
        if parts:
            return parts[0]
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# Cache backend adapters — bridge dag.py protocol to cache.py
# ---------------------------------------------------------------------------

class _CacheStatAdapter(CacheBackend):
    """Wraps TieredCache for use as dag.py CacheBackend (stat only at resolve time)."""
    def __init__(self, tiered: TieredCache):
        self._t = tiered
    def stat(self, key: str) -> bool:
        return self._t.stat(key)


class _RegistryStatAdapter(RegistryBackend):
    """Stub registry backend — registry support to be implemented."""
    def stat(self, key: str) -> bool:
        return False   # no registry backend yet — all assembly deps are misses


# ---------------------------------------------------------------------------
# Verb implementations
# ---------------------------------------------------------------------------

def verb_deps(
    target:  str,
    config,
    cache:   TieredCache,
    reporter: Reporter,
    publish: bool,
) -> bool:
    """
    Resolve the DAG, stat cache/registry, print hit/miss report.
    With --publish: build any missing deps and push to global cache.
    Returns True on success.
    """
    lock     = KilnLock(config.lock_file)
    resolver = Resolver(
        components_root = config.components_dir,
        cache           = _CacheStatAdapter(cache),
        registry        = _RegistryStatAdapter(),
        lock            = lock,
        forge_base_hash = config.forge.base_image or "sha256:unconfigured",
        toolchain_hash  = config.forge.toolchain  or "sha256:unconfigured",
        max_weight      = config.scheduler.max_weight,
    )

    result = resolver.resolve(target)

    if isinstance(result, ResolveError):
        print(f"\nERROR: {result.message}", file=sys.stderr)
        if result.involved:
            print(f"       involved: {', '.join(result.involved)}", file=sys.stderr)
        return False

    if isinstance(result, ResolvedDAG):
        reporter.set_components(result.components)
        print(f"\nAll {len(result.components)} dependencies satisfied in cache.")
        return True

    # BuildSchedule — some misses
    reporter.set_components(result.dag.components)

    hits   = len(result.dag.components) - len(result.ordered_misses)
    misses = len(result.ordered_misses)
    print(f"\n{hits} cached, {misses} missing:")
    for node in result.ordered_misses:
        print(f"  MISS  {node.name:<24}  {node.version}")

    if not publish:
        # deps without --publish just reports
        return misses == 0

    # --publish: build each miss in order and push to global cache
    print(f"\n--publish: building {misses} missing components...\n")
    for node in result.ordered_misses:
        reporter.update(node.name, Status.FETCH)
        # TODO: invoke full build pipeline per node
        # For now: placeholder that marks the shape of what goes here
        print(f"  TODO: build + publish {node.name}")
        reporter.update(node.name, Status.OK)

    return True


def verb_fetch(target: str, config, reporter: Reporter) -> bool:
    """Fetch source into bare clone cache, lock SHA."""
    from kiln.registry import ComponentRegistry
    from kiln.fetcher import Fetcher, FetchError
    from kiln.dag import KilnLock

    reg     = ComponentRegistry(config.components_dir)
    lock    = KilnLock(config.lock_file)
    fetcher = Fetcher(config.git_cache_dir, lock)

    if target not in reg:
        print(f"ERROR: component '{target}' not found", file=sys.stderr)
        return False

    instance = reg.instantiate(target)
    if not hasattr(instance, 'source') or not instance.source:
        print(f"ERROR: {target} has no source defined (AssemblyDef?)", file=sys.stderr)
        return False

    reporter.update(target, Status.FETCH)
    try:
        sha = fetcher.fetch(target, instance.source)
        print(f"  {target}: {sha[:12]}")

        # Write resolved SHA to .kiln/source_commit for use by package verb
        state_dir = config.build_root / ".kiln" / "state" / target
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "source_commit").write_text(sha, encoding="utf-8")

        reporter.update(target, Status.OK)
        return True
    except FetchError as exc:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: {exc}", file=sys.stderr)
        return False


def verb_clear_cache(config, cache: TieredCache) -> bool:
    """Remove all local cache entries."""
    size_before = cache.local_size_bytes()
    count = cache.clear_local()
    size_mb = size_before / (1024 * 1024)
    print(f"Cleared {count} artifacts ({size_mb:.1f} MB) from local cache.")
    print(f"Cache: {config.local_cache_dir}")
    return True


def verb_not_implemented(verb: str, target: str) -> bool:
    """Placeholder for verbs not yet implemented."""
    print(f"  [{verb}] {target} — not yet implemented")
    return True


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

def dispatch(
    verb:     str,
    target:   str,
    config,
    cache:    TieredCache,
    reporter: Reporter,
    publish:  bool,
) -> bool:
    """Run one verb. Returns True on success, False on failure."""
    if verb == "deps":
        return verb_deps(target, config, cache, reporter, publish)
    elif verb == "fetch":
        return verb_fetch(target, config, reporter)
    elif verb == "clear_cache":
        return verb_clear_cache(config, cache)
    elif verb in ("configure", "build", "test", "install", "package", "clean", "purge"):
        return verb_not_implemented(verb, target)
    else:
        print(f"ERROR: unknown verb '{verb}'", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args   = parser.parse_args(argv)

    # --- Load config ---
    try:
        config = load_config()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # --- Apply overrides ---
    if args.weight is not None:
        config.scheduler.max_weight = args.weight

    # --- Infer target ---
    target = args.target or infer_target(config, Path.cwd())
    if target is None:
        print(
            "ERROR: could not infer target component from current directory.\n"
            "       Run from components/<name>/ or use --target <name>",
            file=sys.stderr,
        )
        return 1

    # --- Build cache ---
    try:
        cache = cache_from_config(config)
    except Exception as exc:
        print(f"ERROR: cache initialisation failed: {exc}", file=sys.stderr)
        return 1

    # --- Output mode ---
    mode = detect_output_mode(
        verbose = args.verbose,
        no_tty  = args.no_tty,
    )
    reporter = Reporter(
        mode       = mode,
        audit_dir  = config.build_root / ".kiln" / "audit",
        max_weight = config.scheduler.max_weight,
    )

    # --- Run verbs in order ---
    for verb in args.verbs:
        ok = dispatch(
            verb     = verb,
            target   = target,
            config   = config,
            cache    = cache,
            reporter = reporter,
            publish  = args.publish,
        )
        if not ok:
            print(f"\nFailed at verb: {verb}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())