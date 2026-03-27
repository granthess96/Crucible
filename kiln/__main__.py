"""
kiln/__main__.py
CLI entry point for kiln.
Usage (from any directory inside a build tree):
    kiln <verb> [verb ...] [options]
Verbs (run in the order given, stop on first failure):
    deps        resolve DAG, stat cache/registry, build missing deps
    fetch       git fetch source into bare clone cache
    checkout    export source tree, apply patches, prepare build dirs
    configure   run build system configure step
    build       compile
    test        run test suite
    install     DESTDIR install into empty directory
    package     split install tree -> runtime + buildtime tarballs, store in cache
    assemble    assemble AssemblyDef component (ImageDef -> squashfs, etc.)
    clean       wipe build directory, leave source
    purge       wipe everything including source and build state
    clear_cache remove all local cache entries
    resolve     gather artifact hashes for a set of components (for cast)
Options:
    --verbose       single worker, stream build output to terminal
    --no-tty        plain line-per-completion output (auto if not a terminal)
    --push          push artifacts to Coffer remote cache after package
    --target        component name to build (default: inferred from cwd)
    --weight        override max_weight for this run
    --from-stdin    (resolve) read component list as JSON array from stdin
Examples:
    cd components/zlib
    kiln deps
    kiln fetch checkout configure build test install package
    kiln fetch checkout configure build test install package --push
    kiln fetch configure build --verbose
    cd components/base-image
    kiln deps assemble

    # resolve -- for cast image projection
    kiln resolve bash coreutils systemd
    echo '["bash", "coreutils"]' | kiln resolve --from-stdin
"""
from __future__ import annotations
import datetime
import os
import sys
from pathlib import Path
_here = Path(__file__).parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import argparse
from crucible.config import load_config, ConfigError, CrucibleConfig
from kiln.dag import (
    Resolver, ResolvedDAG, BuildSchedule, ResolveError,
    KilnLock, CacheBackend, RegistryBackend,
)
from kiln.cache import (
    TieredCache, cache_from_config, CacheMiss, CacheError,
    CofferUnavailable, Artifact,
)
from kiln.output import Reporter, Status, OutputMode, detect_output_mode
from kiln.backends import make_resolver

# ---------------------------------------------------------------------------
# Valid verbs
# ---------------------------------------------------------------------------
ALL_VERBS = [
    "deps", "fetch", "checkout", "configure", "build", "test",
    "install", "package", "assemble", "clean", "purge", "clear_cache",
    "resolve",
]

# Verbs that operate on an explicit component list rather than an inferred
# single target.  These are dispatched before target inference runs.
_MULTI_TARGET_VERBS = {"resolve"}

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
    parser.add_argument("--push", action="store_true",
        help="push packaged artifact to Coffer remote cache after package")
    parser.add_argument("--target", metavar="COMPONENT", default=None,
        help="component to build (default: inferred from cwd)")
    parser.add_argument("--weight", metavar="N", type=int, default=None,
        help="override max_weight for this run")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
        help="resolve and display dependency DAG, then exit without building")
    # resolve-specific
    parser.add_argument(
        "--from-stdin", action="store_true", dest="from_stdin",
        help="(resolve) read component list as JSON array from stdin",
    )
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
    """
    components = config.components_dir.resolve()
    current    = cwd.resolve()
    for directory in [current, *current.parents]:
        try:
            rel = directory.relative_to(components)
        except ValueError:
            break
        if rel.parts:
            component_dir = components / rel.parts[0]
            if (component_dir / "build.py").exists():
                return rel.parts[0]
    return None

# ---------------------------------------------------------------------------
# deps verb -- lives here because it drives the full build pipeline
# ---------------------------------------------------------------------------
def verb_deps(target: str, config, cache: TieredCache,
              reporter: Reporter, push: bool, dry_run: bool) -> bool:
    """
    Resolve DAG, stat cache/registry, report hits/misses.
    If any deps are missing, build them in topo order before returning.
    The target itself is excluded -- only its dependencies are built here.
    --push  push each built dep to Coffer after packaging
    """
    from kiln.dag import BuildSchedule
    from kiln.verbs.source import verb_fetch, verb_checkout
    from kiln.verbs.build import verb_configure, verb_build, verb_test, verb_install
    from kiln.verbs.packaging import verb_package
    resolver = make_resolver(config, cache)
    result   = resolver.resolve(target)
    if isinstance(result, ResolveError):
        print(f"\nERROR: {result.message}", file=sys.stderr)
        if result.involved:
            print(f"       involved: {', '.join(result.involved)}",
                  file=sys.stderr)
        return False
    if isinstance(result, ResolvedDAG):
        print()
        for node in result.components:
            print(f"  [{Status.CACHED.name:^9}]  {node.name:<24}  {node.version:<12}  "
                  f"weight:{node.build_weight}  {node.manifest_hash[:16]}")
        print(f"\nAll {len(result.components)} dependencies satisfied.")
        return True
    # BuildSchedule -- some misses
    dep_misses = [n for n in result.ordered_misses if n.name != target]
    hits       = len(result.dag.components) - len(result.ordered_misses)
    print()
    for node in result.dag.components:
        status = Status.CACHED if node.cache_hit else Status.PENDING
        print(f"  [{status.name:^9}]  {node.name:<24}  {node.version:<12}  "
              f"weight:{node.build_weight}  {node.manifest_hash[:16]}")
    print(f"\n{hits} cached, {len(dep_misses)} dep(s) to build.")
    if dry_run:
        return True
    if not dep_misses:
        return True
    # --- Build each missing dep in topo order ---
    BUILD_VERBS = [
        ("fetch",     lambda t, cfg, c, r: verb_fetch(t, cfg, r)),
        ("checkout",  lambda t, cfg, c, r: verb_checkout(t, cfg, c, r)),
        ("configure", lambda t, cfg, c, r: verb_configure(t, cfg, r)),
        ("build",     lambda t, cfg, c, r: verb_build(t, cfg, r)),
        ("test",      lambda t, cfg, c, r: verb_test(t, cfg, r)),
        ("install",   lambda t, cfg, c, r: verb_install(t, cfg, r)),
        ("package",   lambda t, cfg, c, r: verb_package(t, cfg, c, r, push)),
    ]
    for node in dep_misses:
        dep = node.name
        print(f"\n--- building dep: {dep} ---")
        for verb_name, caller in BUILD_VERBS:
            ok = caller(dep, config, cache, reporter)
            if not ok:
                print(
                    f"\nERROR: dep '{dep}' failed at verb '{verb_name}'.\n"
                    f"       Fix the error above, then re-run 'kiln deps'.",
                    file=sys.stderr,
                )
                return False
        print(f"--- dep done:     {dep} ---")
    print(f"\nAll {len(dep_misses)} missing dep(s) built successfully.")
    return True

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def dispatch(verb: str, target: str, config, cache: TieredCache,
             reporter: Reporter, push: bool, dry_run: bool) -> bool:
    from kiln.verbs.source    import verb_fetch, verb_checkout
    from kiln.verbs.build     import verb_configure, verb_build, verb_test, verb_install
    from kiln.verbs.packaging import verb_package
    from kiln.verbs.workspace import verb_clean, verb_purge, verb_clear_cache

    if verb == "deps":
        return verb_deps(target, config, cache, reporter, push, dry_run)
    elif verb == "fetch":
        return verb_fetch(target, config, reporter)
    elif verb == "checkout":
        return verb_checkout(target, config, cache, reporter)
    elif verb == "configure":
        return verb_configure(target, config, reporter)
    elif verb == "build":
        return verb_build(target, config, reporter)
    elif verb == "test":
        return verb_test(target, config, reporter)
    elif verb == "install":
        return verb_install(target, config, reporter)
    elif verb == "package":
        return verb_package(target, config, cache, reporter, push)
    elif verb == "clean":
        return verb_clean(target, config, reporter)
    elif verb == "purge":
        return verb_purge(target, config, reporter)
    elif verb == "clear_cache":
        return verb_clear_cache(config, cache)
    else:
        print(f"ERROR: unknown verb '{verb}'", file=sys.stderr)
        return False

# ---------------------------------------------------------------------------
# resolve dispatch -- separate from dispatch() because it does not use
# target inference and writes JSON to stdout rather than driving a build.
# ---------------------------------------------------------------------------
def _run_resolve(args, config, cache: TieredCache) -> int:
    """
    Handle the resolve verb end-to-end.  Returns an exit code.

    Input priority:
      1. stdin is a pipe (or --from-stdin is set) → read JSON array from stdin
      2. --target <name>                           → single component
      Both are usable from CI/Cast without any extra flags.
    """
    from kiln.verbs.resolve import verb_resolve, read_targets_from_stdin

    use_stdin = args.from_stdin or not sys.stdin.isatty()

    if use_stdin:
        targets = read_targets_from_stdin()
        if targets is None:
            return 2
    elif args.target:
        targets = [args.target]
    else:
        print(
            "ERROR: resolve requires components via stdin (JSON array)\n"
            "       or a single component via --target <name>.",
            file=sys.stderr,
        )
        return 2

    ok = verb_resolve(targets, config, cache)
    return 0 if ok else 1

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    print(
        f"[{datetime.datetime.now().isoformat(timespec='seconds')}] "
        f"kiln {' '.join(sys.argv[1:])}",
        file=sys.stderr,
        flush=True,
    )
    print("---------------------------------------------------------------------------", file=sys.stderr)

    parser = make_parser()
    args   = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # Multi-target verbs bypass the normal single-target inference path.
    # Currently only 'resolve'.  These must be used alone.
    # ------------------------------------------------------------------
    active_multi = _MULTI_TARGET_VERBS.intersection(args.verbs)
    if active_multi:
        if len(args.verbs) != len(active_multi) or len(active_multi) > 1:
            print(
                f"ERROR: {', '.join(active_multi)} cannot be combined with other verbs.",
                file=sys.stderr,
            )
            return 2

        try:
            config = load_config()
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        if args.weight is not None:
            config.scheduler.max_weight = args.weight
        try:
            cache = cache_from_config(config)
        except Exception as exc:
            print(f"ERROR: cache initialisation failed: {exc}", file=sys.stderr)
            return 1

        verb = next(iter(active_multi))
        if verb == "resolve":
            return _run_resolve(args, config, cache)
        # Future multi-target verbs added here.
        print(f"ERROR: unhandled multi-target verb '{verb}'", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Normal single-target path (unchanged from original)
    # ------------------------------------------------------------------
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
            "       Run from components/<n>/ or use --target <n>",
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
        try:
            ok = dispatch(
                verb     = verb,
                target   = target,
                config   = config,
                cache    = cache,
                reporter = reporter,
                push     = args.push,
                dry_run  = args.dry_run,
            )
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"\nERROR: {exc}", file=sys.stderr)
            print(f"Failed at verb: {verb}", file=sys.stderr)
            if os.environ.get("KILN_TRACEBACK"):
                import traceback
                traceback.print_exc()
            return 1
        if not ok:
            print(f"\nFailed at verb: {verb}", file=sys.stderr)
            return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())