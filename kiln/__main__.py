"""
kiln/__main__.py

CLI entry point for kiln.

Usage (from any directory inside a build tree):
    kiln <verb> [verb ...] [options]

Verbs (run in the order given, stop on first failure):
    deps        resolve DAG, stat cache/registry, report hits/misses
    fetch       git fetch source into bare clone cache
    checkout    export source tree, apply patches, prepare build dirs
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
    kiln deps fetch checkout configure build test install package
    kiln deps --publish
    kiln fetch configure build --verbose
"""

from __future__ import annotations

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
from kiln.cache import TieredCache, cache_from_config, CacheMiss, CacheError
from kiln.output import Reporter, Status, OutputMode, detect_output_mode


# ---------------------------------------------------------------------------
# Valid verbs
# ---------------------------------------------------------------------------

ALL_VERBS = [
    "deps", "fetch", "checkout", "configure", "build", "test",
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
    """
    Adapter used by the DAG resolver — checks cache existence by key only,
    without needing the component name. Uses Artifact.find() to scan by glob.
    """
    def __init__(self, tiered: TieredCache):
        self._t = tiered

    def stat(self, key: str) -> bool:
        # The resolver only needs to know if an artifact exists.
        # Use the local backend's _artifact_path directly and scan for any
        # *.manifest.txt — avoids needing the component name at resolve time.
        local = self._t._local
        if hasattr(local, '_artifact_path'):
            from kiln.cache import Artifact
            artifact = Artifact.find(local._artifact_path(key))
            if artifact is not None and artifact.is_complete():
                return True
        # Fallback: try global if present
        if self._t._global is not None:
            global_b = self._t._global
            if hasattr(global_b, '_artifact_path'):
                from kiln.cache import Artifact
                artifact = Artifact.find(global_b._artifact_path(key))
                if artifact is not None and artifact.is_complete():
                    return True
        return False


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



def _populate_sysroot(
    target:      str,
    instance,
    config,
    cache:       TieredCache,
    sysroot_dir: Path,
) -> bool:
    """
    Unpack buildtime artifacts for all deps into sysroot_dir.
    Re-runs the resolver to get manifest hashes — fast, correct, no state file needed.
    Returns True on success, False with error message printed on failure.
    """
    import subprocess
    import tempfile

    if not instance.deps:
        return True

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
        print(f"ERROR: dep resolution failed: {result.message}", file=sys.stderr)
        return False

    nodes     = result.components if isinstance(result, ResolvedDAG) else result.dag.components
    dep_nodes = [n for n in nodes if n.name != target and n.output_store == "cache"]

    if not dep_nodes:
        return True

    # Fail fast — all deps must be cached before we start unpacking
    missing = [n for n in dep_nodes if not n.cache_hit]
    if missing:
        names = ", ".join(n.name for n in missing)
        print(
            f"ERROR: deps not in cache: {names}\n"
            f"       Run \'kiln deps\' to check status, build missing deps first.",
            file=sys.stderr,
        )
        return False

    print(f"  {target}: populating __sysroot__/ from {len(dep_nodes)} dep(s)")

    for node in dep_nodes:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            try:
                cache.fetch(node.manifest_hash, node.name, tmp_path)
            except (CacheMiss, CacheError) as exc:
                print(f"ERROR: failed to fetch dep {node.name}: {exc}", file=sys.stderr)
                return False

            buildtime_tarball = tmp_path / f"{node.name}.buildtime.tar.zst"
            if not buildtime_tarball.exists():
                print(
                    f"ERROR: dep {node.name} has no buildtime.tar.zst in cache.\n"
                    f"       Was it built with 'kiln package'?",
                    file=sys.stderr,
                )
                return False

            # Extract buildtime artifact into __sysroot__/
            # Try native zstd first, fall back to tar auto-detection
            unpack = subprocess.run(
                ["tar", "--use-compress-program=zstd", "-xf",
                 str(buildtime_tarball), "-C", str(sysroot_dir)],
                stderr=subprocess.PIPE,
            )
            if unpack.returncode != 0:
                unpack = subprocess.run(
                    ["tar", "-xf", str(buildtime_tarball), "-C", str(sysroot_dir)],
                    stderr=subprocess.PIPE,
                )
            if unpack.returncode != 0:
                print(
                    f"ERROR: failed to unpack {node.name} buildtime artifact:\n"
                    f"       {unpack.stderr.decode().strip()}",
                    file=sys.stderr,
                )
                return False

            print(f"  {target}: unpacked {node.name} ({node.manifest_hash[:12]})")

    return True


def verb_checkout(target: str, config, cache: TieredCache, reporter: Reporter) -> bool:
    """
    Set up the complete build environment for a component:
      1. Verify kiln fetch was run (source_commit sentinel exists)
      2. Wipe __source__/, __sysroot__/, __build__/, __install__/ for clean slate
      3. Export source tree from bare clone into __source__/
      4. Apply patches in lexicographic order
      5. Unpack dep buildtime artifacts into __sysroot__/
      6. Create empty __build__/ and __install__/
      7. Write checked_out sentinel

    Destructive — always starts from a clean slate. No prompts.
    Precondition: kiln fetch must have run.
    All deps must be present in the artifact cache.
    """
    import shutil
    import subprocess
    from kiln.registry import ComponentRegistry, RegistryError

    try:
        reg = ComponentRegistry(config.components_dir)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return False

    if target not in reg:
        print(f"ERROR: component \'{target}\' not found in components/", file=sys.stderr)
        return False

    if not reg.is_build_def(target):
        print(f"ERROR: {target} is an AssemblyDef — no source to check out",
              file=sys.stderr)
        return False

    # --- Verify fetch was run ---
    state_dir   = config.build_root / ".kiln" / "state" / target
    commit_file = state_dir / "source_commit"
    if not commit_file.exists():
        print(
            f"ERROR: {target} has not been fetched.\n"
            f"       Run \'kiln fetch\' first.",
            file=sys.stderr,
        )
        return False

    sha       = commit_file.read_text(encoding="utf-8").strip()
    bare_path = config.git_cache_dir / f"{target}.git"

    if not bare_path.exists():
        print(
            f"ERROR: bare clone missing for {target}.\n"
            f"       Run \'kiln fetch\' first.",
            file=sys.stderr,
        )
        return False

    instance      = reg.instantiate(target)
    component_dir = config.components_dir / target
    source_dir    = component_dir / "__source__"
    sysroot_dir   = component_dir / "__sysroot__"
    build_dir     = component_dir / "__build__"
    install_dir   = component_dir / "__install__"
    patches_dir   = component_dir / "patches"

    reporter.update(target, Status.FETCH)

    # --- Wipe all managed directories — clean slate ---
    for d in (source_dir, sysroot_dir, build_dir, install_dir):
        if d.exists():
            shutil.rmtree(d)

    # --- Export source tree at locked SHA ---
    source_dir.mkdir()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", sha],
        cwd    = bare_path,
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE,
    )
    if archive.returncode != 0:
        print(
            f"ERROR: git archive failed for {target} at {sha[:16]}:\n"
            f"       {archive.stderr.decode().strip()}",
            file=sys.stderr,
        )
        reporter.update(target, Status.ERROR)
        return False

    extract = subprocess.run(
        ["tar", "x", "-C", str(source_dir)],
        input  = archive.stdout,
        stderr = subprocess.PIPE,
    )
    if extract.returncode != 0:
        print(
            f"ERROR: tar extract failed for {target}:\n"
            f"       {extract.stderr.decode().strip()}",
            file=sys.stderr,
        )
        reporter.update(target, Status.ERROR)
        return False

    print(f"  {target}: checked out {sha[:16]}")

    # --- Apply patches ---
    if patches_dir.is_dir():
        patch_files = sorted(patches_dir.glob("*.patch"))
        if patch_files:
            print(f"  {target}: applying {len(patch_files)} patch(es)")
            for patch_file in patch_files:
                patched = subprocess.run(
                    ["patch", "-p1", "-i", str(patch_file)],
                    cwd    = source_dir,
                    stdout = subprocess.PIPE,
                    stderr = subprocess.PIPE,
                )
                if patched.returncode != 0:
                    print(
                        f"ERROR: patch failed: {patch_file.name}\n"
                        f"       {patched.stderr.decode().strip()}\n"
                        f"       {patched.stdout.decode().strip()}",
                        file=sys.stderr,
                    )
                    reporter.update(target, Status.ERROR)
                    return False
                print(f"  {target}: applied {patch_file.name}")

    # --- Populate __sysroot__/ from dep buildtime artifacts ---
    sysroot_dir.mkdir()
    if not _populate_sysroot(target, instance, config, cache, sysroot_dir):
        reporter.update(target, Status.ERROR)
        return False

    # --- Create empty __build__/ and __install__/ ---
    build_dir.mkdir()
    install_dir.mkdir()

    # --- Write checked_out sentinel ---
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "checked_out").write_text(f"{sha}\n", encoding="utf-8")

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


def _get_builder(target: str, config):
    """Load component registry and instantiate the builder for target."""
    from kiln.registry import ComponentRegistry, RegistryError
    try:
        reg = ComponentRegistry(config.components_dir)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None, None
    if target not in reg:
        print(f"ERROR: component '{target}' not found", file=sys.stderr)
        return None, None
    return reg, reg.instantiate(target)


def _check_sentinel(config, target: str, sentinel: str, missing_verb: str) -> bool:
    """Return True if sentinel file exists, print clear error if not."""
    sentinel_file = config.build_root / ".kiln" / "state" / target / sentinel
    if not sentinel_file.exists():
        print(
            f"ERROR: {target} has not been {sentinel.replace('_', ' ')}.\n"
            f"       Run 'kiln {missing_verb}' first.",
            file=sys.stderr,
        )
        return False
    return True


def _forge_run(config, target: str, cmd: list[str],
               reporter: Reporter, status: Status,
               cwd: Path | None = None) -> bool:
    """Run cmd inside a ForgeInstance. Returns True on success."""
    from forge.instance import ForgeInstance

    reporter.update(target, status)
    effective_cwd = cwd or config.components_dir / target
    try:
        with ForgeInstance(config) as instance:
            rc = instance.run(cmd, cwd=effective_cwd)
        if rc != 0:
            reporter.update(target, Status.ERROR)
            print(f"ERROR: {target}: command exited {rc}", file=sys.stderr)
            return False
        return True
    except Exception as exc:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: forge failed for {target}: {exc}", file=sys.stderr)
        return False


def _forge_run_script(config, target: str, script_body: str,
                      verb: str, reporter: Reporter, status: Status,
                      cwd: Path | None = None) -> bool:
    """
    Write script_body to __build__/kiln-<verb>.sh on the host,
    then run it inside a ForgeInstance via bash.
    The script file is left in place after the run for debugging.
    """
    from forge.instance import ForgeInstance

    build_dir  = config.components_dir / target / "__build__"
    script_path = build_dir / f"kiln-{verb}.sh"

    # Prepend strict mode — catches silent failures in multi-step scripts
    full_script = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + script_body
    script_path.write_text(full_script, encoding="utf-8")
    script_path.chmod(0o755)

    # Chroot-internal path to the script
    from kiln.builders.base import BuildPaths
    paths       = BuildPaths.for_component(target)
    chroot_script = f"{paths.build}/kiln-{verb}.sh"

    reporter.update(target, status)
    effective_cwd = cwd or build_dir
    try:
        with ForgeInstance(config) as instance:
            rc = instance.run(['bash', chroot_script], cwd=effective_cwd)
        if rc != 0:
            reporter.update(target, Status.ERROR)
            print(
                f"ERROR: {target}: script exited {rc}\n"
                f"       Script left at: {script_path}",
                file=sys.stderr,
            )
            return False
        return True
    except Exception as exc:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: forge failed for {target}: {exc}", file=sys.stderr)
        return False


def _resolve_verb(instance, verb: str, paths):
    """
    Return (script_body_or_None, cmd_or_None) for a given verb.
    Script takes precedence over command if both are defined.
    """
    script_method  = getattr(instance, f"{verb}_script",  None)
    command_method = getattr(instance, f"{verb}_command", None)

    script = script_method(paths)  if script_method  else None
    cmd    = command_method(paths) if command_method else []

    return script, cmd


def verb_configure(target: str, config, reporter: Reporter) -> bool:
    """Run build system configure step inside forge."""
    from kiln.builders.base import BuildPaths

    if not _check_sentinel(config, target, "checked_out", "checkout"):
        return False

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    paths          = BuildPaths.for_component(target)
    script, cmd    = _resolve_verb(instance, "configure", paths)
    build_dir      = config.components_dir / target / "__build__"
    state_dir      = config.build_root / ".kiln" / "state" / target

    if script:
        ok = _forge_run_script(config, target, script, "configure",
                               reporter, Status.CONFIG, cwd=build_dir)
    elif cmd:
        ok = _forge_run(config, target, cmd, reporter, Status.CONFIG, cwd=build_dir)
    else:
        print(f"  {target}: no configure step — skipping")
        (state_dir / "configured").write_text("skipped\n")
        reporter.update(target, Status.OK)
        return True

    if ok:
        (state_dir / "configured").write_text("ok\n")
        reporter.update(target, Status.OK)
    return ok


def verb_build(target: str, config, reporter: Reporter) -> bool:
    """Compile inside forge."""
    from kiln.builders.base import BuildPaths

    if not _check_sentinel(config, target, "configured", "configure"):
        return False

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = _resolve_verb(instance, "build", paths)
    build_dir   = config.components_dir / target / "__build__"

    if script:
        ok = _forge_run_script(config, target, script, "build",
                               reporter, Status.BUILD, cwd=build_dir)
    else:
        ok = _forge_run(config, target, cmd, reporter, Status.BUILD, cwd=build_dir)
    if ok:
        reporter.update(target, Status.OK)
    return ok


def verb_test(target: str, config, reporter: Reporter) -> bool:
    """Run test suite inside forge."""
    from kiln.builders.base import BuildPaths

    if not _check_sentinel(config, target, "configured", "configure"):
        return False

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = _resolve_verb(instance, "test", paths)
    build_dir   = config.components_dir / target / "__build__"

    if script:
        ok = _forge_run_script(config, target, script, "test",
                               reporter, Status.TEST, cwd=build_dir)
    elif cmd:
        ok = _forge_run(config, target, cmd, reporter, Status.TEST, cwd=build_dir)
    else:
        print(f"  {target}: no test suite defined — skipping")
        reporter.update(target, Status.OK)
        return True
    if ok:
        reporter.update(target, Status.OK)
    return ok


def verb_install(target: str, config, reporter: Reporter) -> bool:
    """DESTDIR install into __install__/ inside forge."""
    from kiln.builders.base import BuildPaths

    if not _check_sentinel(config, target, "configured", "configure"):
        return False

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = _resolve_verb(instance, "install", paths)
    build_dir   = config.components_dir / target / "__build__"

    if script:
        ok = _forge_run_script(config, target, script, "install",
                               reporter, Status.INSTALL, cwd=build_dir)
    else:
        ok = _forge_run(config, target, cmd, reporter, Status.INSTALL, cwd=build_dir)
    if ok:
        reporter.update(target, Status.OK)
    return ok


def verb_clean(target: str, config, reporter: Reporter) -> bool:
    """Wipe __build__/ and __install__/ — keep source and sysroot."""
    import shutil
    component_dir = config.components_dir / target
    for d in ("__build__", "__install__"):
        path = component_dir / d
        if path.exists():
            shutil.rmtree(path)
            path.mkdir()
            print(f"  {target}: cleared {d}/")
    # Clear configured sentinel so configure must re-run
    sentinel = config.build_root / ".kiln" / "state" / target / "configured"
    if sentinel.exists():
        sentinel.unlink()
    reporter.update(target, Status.OK)
    return True


def verb_purge(target: str, config, reporter: Reporter) -> bool:
    """Wipe everything — source, sysroot, build, install."""
    import shutil
    component_dir = config.components_dir / target
    for d in ("__source__", "__sysroot__", "__build__", "__install__"):
        path = component_dir / d
        if path.exists():
            shutil.rmtree(path)
            print(f"  {target}: cleared {d}/")
    # Clear sentinels
    state_dir = config.build_root / ".kiln" / "state" / target
    for sentinel in ("checked_out", "configured"):
        f = state_dir / sentinel
        if f.exists():
            f.unlink()
    reporter.update(target, Status.OK)
    return True


def verb_package(target: str, config, cache: TieredCache, reporter: Reporter) -> bool:
    """
    Split __install__/ into runtime and buildtime tarballs, write manifest,
    store in local artifact cache.

    runtime.tar.zst   — .so libs, binaries, etc (runtime_globs)
    buildtime.tar.zst — headers, .a libs, pkgconfig (buildtime_globs)
    manifest.txt      — full canonical manifest fields

    Files are named <component>.{runtime,buildtime}.tar.zst and
    <component>.manifest.txt for human-readable cache inspection.
    """
    import fnmatch
    import json
    import subprocess
    import tempfile

    if not _check_sentinel(config, target, "configured", "configure"):
        return False

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    component_dir = config.components_dir / target
    install_dir   = component_dir / "__install__"

    if not install_dir.exists() or not any(install_dir.rglob("*")):
        print(
            f"ERROR: {target}: __install__/ is empty.\n"
            f"       Run 'kiln install' first.",
            file=sys.stderr,
        )
        return False

    reporter.update(target, Status.PACKAGE)

    # --- Resolve manifest hash ---
    from kiln.dag import Resolver, ResolvedDAG, ResolveError
    from kiln.cache import cache_from_config

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
        print(f"ERROR: manifest resolution failed: {result.message}", file=sys.stderr)
        reporter.update(target, Status.ERROR)
        return False

    nodes       = result.components if isinstance(result, ResolvedDAG) else result.dag.components
    target_node = next((n for n in nodes if n.name == target), None)
    if target_node is None:
        print(f"ERROR: {target} not found in resolved DAG", file=sys.stderr)
        reporter.update(target, Status.ERROR)
        return False

    manifest_hash = target_node.manifest_hash

    # --- Collect files by glob pattern ---
    def collect(globs: list[str]) -> list[Path]:
        matched = []
        for f in sorted(install_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(install_dir)
            for pattern in globs:
                if fnmatch.fnmatch(str(rel), pattern):
                    matched.append(f)
                    break
        return matched

    runtime_files   = collect(instance.runtime_globs)
    buildtime_files = collect(instance.buildtime_globs)

    print(f"  {target}: {len(runtime_files)} runtime files, "
          f"{len(buildtime_files)} buildtime files")

    # Refuse to package if both tarballs would be empty — almost certainly
    # means install didn't run or installed to an unexpected path.
    if not runtime_files and not buildtime_files:
        print(
            f"ERROR: {target}: no files matched any glob pattern.\n"
            f"       Check that 'kiln install' ran successfully and that\n"
            f"       the install prefix matches runtime_globs/buildtime_globs.",
            file=sys.stderr,
        )
        reporter.update(target, Status.ERROR)
        return False

    # Warn if only one side is empty — unusual but not always wrong
    if not runtime_files:
        print(f"  WARNING: {target}: no runtime files matched — runtime tarball will be empty")
    if not buildtime_files:
        print(f"  WARNING: {target}: no buildtime files matched — buildtime tarball will be empty")

    # --- Pack into tarballs ---
    with tempfile.TemporaryDirectory(prefix="kiln-package-") as tmp:
        tmp_path = Path(tmp)

        def pack(files: list[Path], tarball: Path) -> bool:
            if not files:
                # Write an empty tarball — artifact must be complete
                result = subprocess.run(
                    ["tar", "--use-compress-program=zstd", "-cf", str(tarball),
                     "--files-from=/dev/null"],
                    stderr=subprocess.PIPE,
                )
            else:
                # Write file list for tar --files-from
                filelist = tmp_path / "filelist.txt"
                filelist.write_text(
                    "\n".join(str(f.relative_to(install_dir)) for f in files)
                )
                result = subprocess.run(
                    ["tar", "--use-compress-program=zstd", "-cf", str(tarball),
                     "-C", str(install_dir),
                     "--files-from", str(filelist)],
                    stderr=subprocess.PIPE,
                )
            if result.returncode != 0:
                print(
                    f"ERROR: tar failed: {result.stderr.decode().strip()}",
                    file=sys.stderr,
                )
                return False
            return True

        runtime_tarball   = tmp_path / f"{target}.runtime.tar.zst"
        buildtime_tarball = tmp_path / f"{target}.buildtime.tar.zst"
        manifest_file     = tmp_path / f"{target}.manifest.txt"

        if not pack(runtime_files, runtime_tarball):
            reporter.update(target, Status.ERROR)
            return False

        if not pack(buildtime_files, buildtime_tarball):
            reporter.update(target, Status.ERROR)
            return False

        # --- Write manifest ---
        manifest_data = instance.manifest_fields()
        manifest_data["manifest_hash"] = manifest_hash
        manifest_file.write_text(
            json.dumps(manifest_data, indent=2) + "\n",
            encoding="utf-8",
        )

        # --- Store in cache ---
        try:
            cache.store_local(manifest_hash, target, tmp_path)
        except Exception as exc:
            print(f"ERROR: cache store failed: {exc}", file=sys.stderr)
            reporter.update(target, Status.ERROR)
            return False

    print(f"  {target}: cached as {manifest_hash[:16]}")
    reporter.update(target, Status.OK)
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
    elif verb == "clean":
        return verb_clean(target, config, reporter)
    elif verb == "purge":
        return verb_purge(target, config, reporter)
    elif verb == "clear_cache":
        return verb_clear_cache(config, cache)
    elif verb == "package":
        return verb_package(target, config, cache, reporter)
    else:
        print(f"ERROR: unknown verb '{verb}'", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    # Re-exec inside user+mount namespace if not already root.
    # Required for ForgeInstance mount operations (overlayfs, squashfs).
    # Only needed for verbs that invoke forge — but simpler to always do it.
    if os.geteuid() != 0:
        os.execvp("unshare", [
            "unshare", "--user", "--mount", "--map-root-user",
            "--", sys.executable, *sys.argv,
        ])
        print("ERROR: unshare failed", file=sys.stderr)
        return 1

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
