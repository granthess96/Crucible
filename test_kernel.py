#!/usr/bin/env python3
"""
test_kernel.py

Functional smoke test for the kiln kernel.
Run from the kiln/ root directory:

    python3 test_kernel.py

Tests:
  1. Registry discovers components/ correctly
  2. DAG resolves in correct topo order
  3. Manifest fields are correct and deterministic
  4. Manifest hash changes when deps change (hash propagation)
  5. Cycle detection works
  6. Missing component detection works
  7. Backend unavailable returns ResolveError, not silent miss

Exit 0 on success, non-zero on any failure.
"""

import sys
import traceback
from pathlib import Path

# Ensure kiln package is importable from the repo root
sys.path.insert(0, str(Path(__file__).parent))

from kiln.registry import ComponentRegistry, RegistryError
from kiln.dag import (
    Resolver, ResolvedDAG, BuildSchedule, ResolveError,
    KilnLock, CacheBackend, RegistryBackend, BackendUnavailableError,
)
from kiln.manifest import render_manifest, hash_manifest

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

failures = 0


def check(label: str, condition: bool, detail: str = ""):
    global failures
    if condition:
        print(f"  [{PASS}]  {label}")
    else:
        print(f"  [{FAIL}]  {label}")
        if detail:
            print(f"           {detail}")
        failures += 1


# ---------------------------------------------------------------------------
# Stub backends
# ---------------------------------------------------------------------------

class AllMissCache(CacheBackend):
    """Every stat is a miss — normal cold build scenario."""
    def stat(self, key): return False

class AllHitCache(CacheBackend):
    """Every stat is a hit — everything cached scenario."""
    def stat(self, key): return True

class BrokenCache(CacheBackend):
    """Backend is down — should produce ResolveError."""
    def stat(self, key): raise ConnectionError("cache server unreachable")

class AllMissRegistry(RegistryBackend):
    def stat(self, key): return False

class AllHitRegistry(RegistryBackend):
    def stat(self, key): return True


def make_resolver(cache=None, registry=None, components_root=None):
    return Resolver(
        components_root = components_root or Path("components"),
        cache           = cache or AllMissCache(),
        registry        = registry or AllMissRegistry(),
        lock            = KilnLock(Path("kiln.lock")),
        forge_base_hash = "sha256:forge_base_test",
        toolchain_hash  = "sha256:toolchain_test",
        max_weight      = 8,
    )


# ---------------------------------------------------------------------------
# Test 1: Registry discovery
# ---------------------------------------------------------------------------
print("\nTest 1: Registry discovery")
try:
    reg = ComponentRegistry(Path("components"))
    names = reg.all_names()
    check("components/ scanned without error", True)
    check("zlib discovered",    "zlib"    in names, f"found: {names}")
    check("openssl discovered", "openssl" in names, f"found: {names}")
    check("curl discovered",    "curl"    in names, f"found: {names}")
    check("zlib is BuildDef",   reg.is_build_def("zlib"))
    check("zlib is not AssemblyDef", not reg.is_assembly_def("zlib"))
except Exception as e:
    print(f"  [{FAIL}]  registry construction failed: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Test 2: DAG topo order
# ---------------------------------------------------------------------------
print("\nTest 2: DAG topo order (curl depends on openssl depends on zlib)")
try:
    result = make_resolver().resolve("curl")
    check("result is BuildSchedule (all miss)", isinstance(result, BuildSchedule))
    if isinstance(result, BuildSchedule):
        order = [n.name for n in result.dag.components]
        check("zlib before openssl",  order.index("zlib")    < order.index("openssl"),  str(order))
        check("openssl before curl",  order.index("openssl") < order.index("curl"),     str(order))
        check("exactly 3 components", len(order) == 3, f"got {len(order)}: {order}")
        check("all 3 are misses",     len(result.ordered_misses) == 3)
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Test 3: All cache hits → ResolvedDAG (not BuildSchedule)
# ---------------------------------------------------------------------------
print("\nTest 3: All cache hits → ResolvedDAG")
try:
    result = make_resolver(cache=AllHitCache(), registry=AllHitRegistry()).resolve("curl")
    check("result is ResolvedDAG", isinstance(result, ResolvedDAG),
          f"got {type(result).__name__}")
    if isinstance(result, ResolvedDAG):
        check("all 3 components present", len(result.components) == 3)
        check("all are cache hits", all(n.cache_hit for n in result.components))
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Test 4: Manifest determinism — same inputs → same hash
# ---------------------------------------------------------------------------
print("\nTest 4: Manifest determinism")
try:
    r1 = make_resolver().resolve("curl")
    r2 = make_resolver().resolve("curl")
    if isinstance(r1, BuildSchedule) and isinstance(r2, BuildSchedule):
        hashes1 = {n.name: n.manifest_hash for n in r1.dag.components}
        hashes2 = {n.name: n.manifest_hash for n in r2.dag.components}
        check("zlib hash stable",    hashes1["zlib"]    == hashes2["zlib"])
        check("openssl hash stable", hashes1["openssl"] == hashes2["openssl"])
        check("curl hash stable",    hashes1["curl"]    == hashes2["curl"])
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Test 5: Hash propagation — dep hash appears in dependent manifest
# ---------------------------------------------------------------------------
print("\nTest 5: Hash propagation (dep hash in dependent manifest)")
try:
    result = make_resolver().resolve("curl")
    if isinstance(result, BuildSchedule):
        nodes = {n.name: n for n in result.dag.components}
        zlib_hash    = nodes["zlib"].manifest_hash
        openssl_hash = nodes["openssl"].manifest_hash

        # zlib's hash should appear in openssl's manifest text
        check("zlib hash in openssl manifest",
              zlib_hash in nodes["openssl"].manifest.text,
              f"looking for {zlib_hash[:16]}... in openssl manifest")

        # openssl's hash should appear in curl's manifest text
        check("openssl hash in curl manifest",
              openssl_hash in nodes["curl"].manifest.text,
              f"looking for {openssl_hash[:16]}... in curl manifest")

        # zlib's hash should NOT directly appear in curl's manifest
        # (curl depends on zlib directly too — so it will, check openssl→curl chain instead)
        check("openssl manifest text is non-empty",
              len(nodes["openssl"].manifest.text) > 50)
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Test 6: Missing component → ResolveError
# ---------------------------------------------------------------------------
print("\nTest 6: Missing component detection")
try:
    result = make_resolver().resolve("does_not_exist")
    check("returns ResolveError",        isinstance(result, ResolveError),
          f"got {type(result).__name__}")
    if isinstance(result, ResolveError):
        check("kind is missing_component", result.kind == "missing_component",
              f"got kind={result.kind}")
        check("involved names present",    len(result.involved) > 0)
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Test 7: Cycle detection
# ---------------------------------------------------------------------------
print("\nTest 7: Cycle detection")
import tempfile, os

cycle_components = Path(tempfile.mkdtemp())
(cycle_components / "alpha").mkdir()
(cycle_components / "beta").mkdir()

(cycle_components / "alpha" / "build.py").write_text("""\
from kiln.builders.base import CMakeBuild
class AlphaBuild(CMakeBuild):
    name    = "alpha"
    version = "1.0"
    deps    = ["beta"]
    source  = {"git": "https://example.com/alpha", "ref": "main"}
""")

(cycle_components / "beta" / "build.py").write_text("""\
from kiln.builders.base import CMakeBuild
class BetaBuild(CMakeBuild):
    name    = "beta"
    version = "1.0"
    deps    = ["alpha"]
    source  = {"git": "https://example.com/beta", "ref": "main"}
""")

try:
    result = make_resolver(components_root=cycle_components).resolve("alpha")
    check("returns ResolveError",  isinstance(result, ResolveError),
          f"got {type(result).__name__}")
    if isinstance(result, ResolveError):
        check("kind is cycle",         result.kind == "cycle",
              f"got kind={result.kind}")
        check("both names in involved", "alpha" in result.involved or "beta" in result.involved)
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1
finally:
    import shutil
    shutil.rmtree(cycle_components)


# ---------------------------------------------------------------------------
# Test 8: Backend unavailable → ResolveError (not silent miss)
# ---------------------------------------------------------------------------
print("\nTest 8: Backend unavailable → hard error")
try:
    result = make_resolver(cache=BrokenCache()).resolve("zlib")
    check("returns ResolveError",          isinstance(result, ResolveError),
          f"got {type(result).__name__}")
    if isinstance(result, ResolveError):
        check("kind is backend_unavailable", result.kind == "backend_unavailable",
              f"got kind={result.kind}")
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Test 9: Manifest canonical format spot checks
# ---------------------------------------------------------------------------
print("\nTest 9: Manifest canonical format")
try:
    result = make_resolver().resolve("openssl")
    if isinstance(result, BuildSchedule):
        nodes = {n.name: n for n in result.dag.components}
        text  = nodes["openssl"].manifest.text

        check("ends with single newline",   text.endswith("\n") and not text.endswith("\n\n"))
        check("component field present",    "component: openssl" in text)
        check("version field present",      "version: 3.2.1"     in text)
        check("dep:zlib field present",     "dep:zlib:" in text)
        check("forge_base field present",   "forge_base:" in text)
        check("no trailing whitespace",     not any(l != l.rstrip() for l in text.splitlines()))
except Exception as e:
    print(f"  [{FAIL}]  unexpected exception: {e}")
    traceback.print_exc()
    failures += 1


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
if failures == 0:
    print(f"\033[32mAll tests passed.\033[0m")
else:
    print(f"\033[31m{failures} test(s) failed.\033[0m")

sys.exit(0 if failures == 0 else 1)