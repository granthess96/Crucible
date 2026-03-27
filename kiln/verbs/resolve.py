"""
kiln/verbs/resolve.py

resolve verb -- gather all artifact hashes needed to project an image.

Accepts a list of component names either:
  - as positional CLI arguments:  kiln resolve bash coreutils
  - as a JSON array on stdin:     echo '["bash"]' | kiln resolve --from-stdin

Output (stdout): a JSON blob listing every artifact required -- both the
components that were explicitly requested and any transitive dependencies
pulled in by the resolver.  The list is complete and definitive: Cast passes
every hash directly to Coffer; no further resolution is needed.

Output schema:
  {
    "schema_version": 1,
    "artifacts": [
      {
        "component": "readline",
        "version":   "8.2",
        "hash":      "sha256:<hex>",
        "requested": false
      },
      ...
    ]
  }

The artifact list is topo-sorted (leaves / deepest deps first).
"requested" is true only for components named explicitly by the caller.

Errors go to stderr; stdout is always either valid JSON or empty.
Exit codes:
  0  success
  1  resolution failure (unknown component, cycle, backend error, etc.)
  2  bad input (malformed JSON on stdin, no components specified)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kiln.cache import TieredCache
    from kiln.dag import ResolvedDAG, BuildSchedule, ComponentNode


# ---------------------------------------------------------------------------
# Core logic -- no argparse here; __main__.py owns argument parsing
# ---------------------------------------------------------------------------

def verb_resolve(
    targets: list[str],
    config,
    cache: "TieredCache",
) -> bool:
    """
    Resolve *targets* and write the definitive JSON artifact manifest to stdout.

    Pure query -- no builds, no fetches, no side effects.  Cast is responsible
    for ensuring all components are already built (via its own kiln invocation
    loop) before calling resolve.  This verb simply walks the DAG, collects
    the manifest hashes, and emits JSON.

    stdout is always pure JSON (or empty on error).
    All progress/error output goes to stderr.

    Returns True on success, False on any error (message already on stderr).
    """
    if not targets:
        print("ERROR: resolve requires at least one component name.", file=sys.stderr)
        print("       echo '[\"bash\"]' | kiln resolve", file=sys.stderr)
        print("       kiln resolve --target bash", file=sys.stderr)
        return False

    requested_set = set(targets)

    from kiln.backends import make_resolver
    from kiln.dag import ResolveError, ResolvedDAG, BuildSchedule

    resolver = make_resolver(config, cache)

    # Accumulate nodes in topo order, deduplicated across all requested targets.
    seen: dict[str, "ComponentNode"] = {}
    ordered: list["ComponentNode"] = []

    for target in targets:
        result = resolver.resolve(target)

        if isinstance(result, ResolveError):
            print(f"\nERROR: {result.message}", file=sys.stderr)
            if result.involved:
                print(f"       involved: {', '.join(result.involved)}", file=sys.stderr)
            return False

        nodes = result.components if isinstance(result, ResolvedDAG) else result.dag.components

        for node in nodes:
            if node.name not in seen:
                seen[node.name] = node
                ordered.append(node)

    artifacts = []
    for node in ordered:
        artifacts.append({
            "component": node.name,
            "version":   node.version,
            "hash":      f"sha256:{node.manifest_hash}",
            "requested": node.name in requested_set,
        })

    print(json.dumps({
        "schema_version": 1,
        "artifacts": artifacts,
    }))
    return True


# ---------------------------------------------------------------------------
# stdin helper -- used by __main__.py before calling verb_resolve
# ---------------------------------------------------------------------------

def read_targets_from_stdin() -> list[str] | None:
    """
    Read a JSON array of component names from stdin.
    Returns the list on success, None on parse failure (error already printed).
    """
    try:
        raw = sys.stdin.read()
    except KeyboardInterrupt:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: stdin is not valid JSON: {exc}", file=sys.stderr)
        return None

    if not isinstance(data, list):
        print("ERROR: stdin JSON must be an array of component name strings.", file=sys.stderr)
        return None

    bad = [x for x in data if not isinstance(x, str)]
    if bad:
        print(f"ERROR: non-string entries in stdin JSON: {bad}", file=sys.stderr)
        return None

    return [x.strip() for x in data if x.strip()]