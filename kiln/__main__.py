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
    package     split install tree -> runtime + buildtime tarballs, store in cache
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
    cd components/rocm-hip
    kiln deps
    kiln deps fetch configure build test install package
    kiln deps --publish
    kiln fetch configure build --verbose
"""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import argparse
from kiln.config import load_config, ConfigError
from kiln.dag import (
    Resolver, ResolvedDAG, BuildSchedule, ResolveError,
    KilnLock, CacheBackend, RegistryBackend,
)
from kiln.cache import TieredCache, cache_from_config, CacheMiss, CacheError
from kiln.output import Reporter, Status, OutputMode, detect_output_mode


# ---------------------------------------------------------------------------
# Valid verbs
# ---------------------------------------------------------------------------

ALL_VERBS = [
    "deps", "fetch", "configure", "build", "test",
    "install", "package", "clean", "purge", "clear_cache",
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "kiln",
        description = "Meta-build tool for forge-based component builds.",
    )
    parser.add_argument(
        "verbs",
        nargs   = "+",
        metavar = "verb",
        choices = ALL_VERBS,
        help    = f"one or more of: {', '.join(ALL_VERBS)}",
    )
    parser.add_argument("--verbose", action="store_true",
        help="stream build output to terminal (implies single worker)")
    parser.add_argument("--no-tty", action="store_true", dest="no_tty",
        help="plain line-per-completion output")
    parser.add_argument("--publish", action="store_true",
        help="push artifacts to global cache (CI credentials required)")
    parser.add_argument("--target", metavar="COMPONENT", default=None,
        help="component to build (default: inferred from cwd)")
    parser.add_argument("--weight", metavar="N", type=int, default=None,
        help="override max_weight for this run")
    return parser


# ---------------------------------------------------------------------------
# Target inference
# ---------------------------------------------------------------------------

def infer_target(config, cwd: Path) -> str | None:
    """
    Walk up from cwd looking for a component root within components/.

    Handles being anywhere inside a component tree:
      components/curl/                        -> curl
      components/curl/__source__/             -> curl
      components/curl/__source__/lib/vauth/   -> curl

    This lets a developer run `kiln build` from anywhere inside the source
    tree without cd-ing back to the component root first.
    """
    components = config.components_dir.resolve()
    current    = cwd.resolve()

    for directory in [current, *current.parents]:
        try:
            rel = directory.relative_to(components)
        except ValueError:
            break   # walked above components/ — stop searching

        if rel.parts:
            component_dir = components / rel.parts[0]
            if (component_dir / "build.py").exists():
                return rel.parts[0]

    return None


# ---------------------------------------------------------------------------
# Cache backend adapters
# ---------------------------------------------------------------------------

class _CacheStatAdapter(CacheBackend):
    def __init__(self, tiered: TieredCache):
        self._t = tiered
    def stat(self, key: str) -> bool:
        return self._t.stat(key)


class _RegistryStatAdapter(RegistryBackend):
    def stat(self, key: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Output helper
# ---------------------------------------------------------------------------

_RESET  = "\033[0m"
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_DIM    = "\033[2m"

def _tag(status: Status) -> str:
    """Simple status tag for deps output."""
    labels = {
        Status.CACHED:  "CACHED ",
        Status.OK:      "  OK   ",
        Status.ERROR:   " ERROR ",
        Status.PENDING: "PENDING",
        Status.SKIPPED: "SKIPPED",
    }
    colours = {
        Status.CACHED:  _DIM,
        Status.OK:      _GREEN,
        Status.ERROR:   _RED,
        Status.PENDING: _DIM,
        Status.SKIPPED: _DIM,
    }
    text  = labels.get(status, status.name[:7].center(7))
    if sys.stdout.isatty():
        clr = colours.get(status, "")
        return f"[{clr}{text}{_RESET}]"
    return f"[{text}]"


# ---------------------------------------------------------------------------
# Verb implementations
# ---------------------------------------------------------------------------

def verb_deps(target: str, config, cache: TieredCache,
              reporter: Reporter, publish: bool) -> bool:
    """Resolve DAG, stat cache/registry, report hits/misses."""
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
        print()
        for node in result.components:
            print(f"  {_tag(Status.CACHED)}  {node.name:<24}  {node.version:<12}  "
                  f"weight:{node.build_weight}  {node.manifest_hash[:16]}")
        print(f"\nAll {len(result.components)} dependencies satisfied.")
        return True

    # BuildSchedule — some misses
    hits   = len(result.dag.components) - len(result.ordered_misses)
    misses = len(result.ordered_misses)

    print()
    for node in result.dag.components:
        status = Status.CACHED if node.cache_hit else Status.PENDING
        print(f"  {_tag(status)}  {node.name:<24}  {node.version:<12}  "
              f"weight:{node.build_weight}  {node.manifest_hash[:16]}")

    print(f"\n{hits} cached, {misses} missing.")

    if not publish:
        return misses == 0

    # --publish: build each miss and push to global cache
    print(f"\n--publish: building {misses} missing components...\n")
    for node in result.ordered_misses:
        reporter.update(node.name, Status.FETCH)
        # TODO: invoke full build pipeline per node
        print(f"  TODO: build + publish {node.name}")
        reporter.update(node.name, Status.OK)

    return True


def verb_fetch(target: str, config, reporter: Reporter) -> bool:
    """Fetch source into bare clone cache and lock SHA."""
    from kiln.registry import ComponentRegistry, RegistryError
    from kiln.fetcher import Fetcher, FetchError

    try:
        reg = ComponentRegistry(config.components_dir)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return False

    lock    = KilnLock(config.lock_file)
    fetcher = Fetcher(config.git_cache_dir, lock)

    if target not in reg:
        print(f"ERROR: component '{target}' not found in components/", file=sys.stderr)
        return False

    if not reg.is_build_def(target):
        print(f"ERROR: {target} is an AssemblyDef — no source to fetch", file=sys.stderr)
        return False

    instance = reg.instantiate(target)
    if not getattr(instance, 'source', None):
        print(f"ERROR: {target}.source is empty — add git url and ref to build.py",
              file=sys.stderr)
        return False

    reporter.update(target, Status.FETCH)
    try:
        sha = fetcher.fetch(target, instance.source)

        # Persist resolved SHA for use by configure/build/package verbs
        state_dir = config.build_root / ".kiln" / "state" / target
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "source_commit").write_text(sha, encoding="utf-8")

        print(f"  {target}: locked at {sha[:16]}")
        reporter.update(target, Status.OK)
        return True

    except FetchError as exc:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: {exc}", file=sys.stderr)
        return False
    except Exception as exc:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: unexpected error fetching {target}: {exc}", file=sys.stderr)
        return False


def verb_clear_cache(config, cache: TieredCache) -> bool:
    """Remove all local cache entries."""
    size_before = cache.local_size_bytes()
    count       = cache.clear_local()
    size_mb     = size_before / (1024 * 1024)
    print(f"Cleared {count} artifacts ({size_mb:.1f} MB) from local cache.")
    print(f"Cache: {config.local_cache_dir}")
    return True


def verb_not_implemented(verb: str, target: str) -> bool:
    print(f"  [{verb}] {target} — not yet implemented")
    return True


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(verb: str, target: str, config, cache: TieredCache,
             reporter: Reporter, publish: bool) -> bool:
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

    try:
        config = load_config()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.weight is not None:
        config.scheduler.max_weight = args.weight

    target = args.target or infer_target(config, Path.cwd())
    if target is None:
        print(
            "ERROR: could not infer target from current directory.\n"
            "       Run from components/<name>/ or use --target <name>",
            file=sys.stderr,
        )
        return 1

    try:
        cache = cache_from_config(config)
    except Exception as exc:
        print(f"ERROR: cache initialisation failed: {exc}", file=sys.stderr)
        return 1

    mode = detect_output_mode(verbose=args.verbose, no_tty=args.no_tty)
    reporter = Reporter(
        mode       = mode,
        audit_dir  = config.build_root / ".kiln" / "audit",
        max_weight = config.scheduler.max_weight,
    )

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