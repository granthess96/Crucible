"""
kiln/verbs/ensure.py

ensure verb -- build a single component with full cache awareness.

Ensures a target component is fully built:
  1. Resolve target (get manifest hash)
  2. Check cache: if hit → report and return True
  3. If miss → run full build pipeline (fetch through package)
  4. Push to Coffer if requested

Does not recursively ensure deps—caller is responsible for that.
The verb_deps orchestrator uses verb_ensure for each missing dep.
"""
from __future__ import annotations
import sys
from kiln.output import Reporter
from kiln.backends import make_resolver
from kiln.dag import ResolveError, ResolvedDAG


def verb_ensure(
    target: str,
    config,
    cache,  # TieredCache
    reporter: Reporter,
    push: bool,
) -> bool:
    """
    Ensure target component is fully built.

    Returns True on success (either cached or successfully built).
    Returns False on error (resolution failure, build failure, etc.).
    """
    from kiln.verbs.source import verb_fetch, verb_checkout
    from kiln.verbs.build import verb_configure, verb_build, verb_test, verb_install
    from kiln.verbs.packaging import verb_package

    # 1. Resolve target
    resolver = make_resolver(config, cache)
    result = resolver.resolve(target)

    if isinstance(result, ResolveError):
        print(f"\nERROR: {result.message}", file=sys.stderr)
        if result.involved:
            print(f"       involved: {', '.join(result.involved)}", file=sys.stderr)
        return False

    # 2. Determine cache status of target
    nodes = result.components if isinstance(result, ResolvedDAG) else result.dag.components
    target_node = next((n for n in nodes if n.name == target), None)

    if target_node is None:
        print(f"ERROR: target '{target}' not found in resolved DAG", file=sys.stderr)
        return False

    if target_node.cache_hit:
        print(f"  [{target}]: already cached ({target_node.manifest_hash[:16]})")
        return True

    # 3. Cache miss → run full build pipeline
    print(f"\n--- building: {target} ---")

    # Build pipeline with correct signatures for each verb
    build_steps = [
        ("fetch",     lambda: verb_fetch(target, config, reporter)),
        ("checkout",  lambda: verb_checkout(target, config, cache, reporter)),
        ("configure", lambda: verb_configure(target, config, reporter)),
        ("build",     lambda: verb_build(target, config, reporter)),
        ("test",      lambda: verb_test(target, config, reporter)),
        ("install",   lambda: verb_install(target, config, reporter)),
        ("package",   lambda: verb_package(target, config, cache, reporter, push)),
    ]

    for verb_name, verb_fn in build_steps:
        ok = verb_fn()
        if not ok:
            print(
                f"\nERROR: {target} failed at verb '{verb_name}'.\n"
                f"       Fix the error above, then re-run 'kiln ensure'.",
                file=sys.stderr,
            )
            return False

    print(f"--- done:     {target} ---")
    return True
