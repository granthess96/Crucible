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

Options:
    --verbose   single worker, stream build output to terminal
    --no-tty    plain line-per-completion output (auto if not a terminal)
    --push      push artifacts to Coffer remote cache after package
    --target    component name to build (default: inferred from cwd)
    --weight    override max_weight for this run

Examples:
    cd components/zlib
    kiln deps
    kiln fetch checkout configure build test install package
    kiln fetch checkout configure build test install package --push
    kiln fetch configure build --verbose

    cd components/base-image
    kiln deps assemble
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
import subprocess
import tempfile


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


# ---------------------------------------------------------------------------
# Valid verbs
# ---------------------------------------------------------------------------

ALL_VERBS = [
    "deps", "fetch", "checkout", "configure", "build", "test",
    "install", "package", "assemble", "clean", "purge", "clear_cache",
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
    parser.add_argument("--push", action="store_true",
        help="push packaged artifact to Coffer remote cache (requires coffer_host in config)")
    parser.add_argument("--target", metavar="COMPONENT", default=None,
        help="component to build (default: inferred from cwd)")
    parser.add_argument("--weight", metavar="N", type=int, default=None,
        help="override max_weight for this run")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
        help="resolve and display dependency DAG, then exit without building")
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
            break   # walked above components/ -- stop searching

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
                print(f"  WARNING: Coffer unreachable during deps stat: {exc.reason}",
                      file=sys.stderr)
                return False

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
              reporter: Reporter, push: bool, dry_run: bool) -> bool:
    """
    Resolve DAG, stat cache/registry, report hits/misses.
    If any deps are missing, build them in topo order before returning.
    The target itself is excluded -- only its dependencies are built here.

    --push  push each built dep to Coffer after packaging
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
        print()
        for node in result.components:
            print(f"  {_tag(Status.CACHED)}  {node.name:<24}  {node.version:<12}  "
                  f"weight:{node.build_weight}  {node.manifest_hash[:16]}")
        print(f"\nAll {len(result.components)} dependencies satisfied.")
        return True

    # BuildSchedule -- some misses
    dep_misses = [n for n in result.ordered_misses if n.name != target]
    hits       = len(result.dag.components) - len(result.ordered_misses)

    print()
    for node in result.dag.components:
        status = Status.CACHED if node.cache_hit else Status.PENDING
        print(f"  {_tag(status)}  {node.name:<24}  {node.version:<12}  "
              f"weight:{node.build_weight}  {node.manifest_hash[:16]}")
    print(f"\n{hits} cached, {len(dep_misses)} dep(s) to build.")
    
    if dry_run:
        # User just wanted to see the DAG and cache status -- don't build, just exit
        return True

    if not dep_misses:
        # Only the target itself is missing -- deps are satisfied
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


def verb_fetch(target: str, config, reporter: Reporter) -> bool:
    """
    Fetch source into local cache and lock source identity.

    git:     bare clone -> .kiln/git-cache/<n>.git, locks commit SHA
    tarball: download   -> .kiln/tarball-cache/<n>/<file>, locks sha256

    Writes source identity to .kiln/state/<n>/source_id on success.
    """
    from kiln.registry import ComponentRegistry, RegistryError
    from kiln.fetcher import Fetcher, TarballFetcher, FetchError
    from kiln.dag import KilnLock, _source_type

    try:
        reg = ComponentRegistry(config.components_dir)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return False

    if target not in reg:
        print(f"ERROR: component '{target}' not found in components/", file=sys.stderr)
        return False

    if not reg.is_build_def(target):
        print(f"ERROR: '{target}' is an AssemblyDef -- no source to fetch", file=sys.stderr)
        return False

    instance = reg.instantiate(target)
    source   = getattr(instance, 'source', None)
    if not source:
        print(f"ERROR: {target}.source is empty -- add source spec to build.py",
              file=sys.stderr)
        return False

    stype = _source_type(source)
    if stype == "unknown":
        print(
            f"ERROR: {target}.source has no recognised key.\n"
            f"       Use 'git' for git sources or 'url' for tarball sources.",
            file=sys.stderr,
        )
        return False

    lock      = KilnLock(config.lock_file)
    state_dir = config.build_root / ".kiln" / "state" / target
    state_dir.mkdir(parents=True, exist_ok=True)

    reporter.update(target, Status.FETCH)

    try:
        if stype == "git":
            fetcher   = Fetcher(config.git_cache_dir, lock)
            source_id = fetcher.fetch(target, source)
            id_type   = "commit"
        else:  # tarball
            fetcher   = TarballFetcher(config.tarball_cache_dir, lock)
            source_id = fetcher.fetch(target, source)
            id_type   = "sha256"

        # Write source identity sentinel -- read back by verb_checkout
        (state_dir / "source_id").write_text(source_id, encoding="utf-8")
        (state_dir / "source_type").write_text(stype, encoding="utf-8")

        print(f"  {target}: locked {id_type} {source_id[:16]}")
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
    Re-runs the resolver to get manifest hashes -- fast, correct, no state file needed.
    Returns True on success, False with error message printed on failure.
    """
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

    # Fail fast -- all deps must be cached before we start unpacking
    missing = [n for n in dep_nodes if not n.cache_hit]
    if missing:
        names = ", ".join(n.name for n in missing)
        print(
            f"ERROR: deps not in cache: {names}\n"
            f"       Run 'kiln deps' to check status, build missing deps first.",
            file=sys.stderr,
        )
        return False

    print(f"  {target}: populating __sysroot__/ from {len(dep_nodes)} dep(s)")

    for node in dep_nodes:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            try:
                cache.fetch(node.manifest_hash, node.name, tmp_path)
            except CofferUnavailable as exc:
                print(f"ERROR: Coffer unreachable while fetching dep {node.name}: {exc.reason}",
                      file=sys.stderr)
                return False
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


def verb_checkout(target: str, config, cache, reporter: Reporter) -> bool:
    """
    Set up the complete build environment for a component:
      1. Verify kiln fetch was run (source_id sentinel exists)
      2. Wipe __source__/, __sysroot__/, __build__/, __install__/ for clean slate
      3. Export/extract source into __source__/
         - git:     git archive from bare clone at locked SHA
         - tarball: tar extract from cached tarball, strip leading directory
      4. Apply patches in lexicographic order
      5. Unpack dep buildtime artifacts into __sysroot__/
      6. Create empty __build__/ and __install__/
      7. Write checked_out sentinel

    Destructive -- always starts from a clean slate. No prompts.
    Precondition: kiln fetch must have run.
    All deps must be present in the artifact cache.
    """
    import shutil
    from kiln.registry import ComponentRegistry, RegistryError
    from kiln.fetcher import Fetcher, TarballFetcher, FetchError
    from kiln.dag import KilnLock, _source_type

    try:
        reg = ComponentRegistry(config.components_dir)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return False

    if target not in reg:
        print(f"ERROR: component '{target}' not found in components/", file=sys.stderr)
        return False

    if not reg.is_build_def(target):
        print(f"ERROR: '{target}' is an AssemblyDef -- no source to check out",
              file=sys.stderr)
        return False

    # --- Verify fetch was run ---
    state_dir = config.build_root / ".kiln" / "state" / target
    id_file   = state_dir / "source_id"
    type_file = state_dir / "source_type"

    if not id_file.exists():
        print(
            f"ERROR: {target} has not been fetched.\n"
            f"       Run 'kiln fetch' first.",
            file=sys.stderr,
        )
        return False

    source_id   = id_file.read_text(encoding="utf-8").strip()
    source_type = type_file.read_text(encoding="utf-8").strip() if type_file.exists() else "git"

    instance      = reg.instantiate(target)
    source        = getattr(instance, 'source', {})
    component_dir = config.components_dir / target
    source_dir    = component_dir / "__source__"
    sysroot_dir   = component_dir / "__sysroot__"
    build_dir     = component_dir / "__build__"
    install_dir   = component_dir / "__install__"
    patches_dir   = component_dir / "patches"

    reporter.update(target, Status.FETCH)

    # --- Wipe all managed directories -- clean slate ---
    for d in (source_dir, sysroot_dir, build_dir, install_dir):
        if d.exists():
            shutil.rmtree(d)
    source_dir.mkdir()

    # --- Export/extract source ---
    if source_type == "git":
        bare_path = config.git_cache_dir / f"{target}.git"
        if not bare_path.exists():
            print(
                f"ERROR: bare clone missing for {target}.\n"
                f"       Run 'kiln fetch' first.",
                file=sys.stderr,
            )
            reporter.update(target, Status.ERROR)
            return False

        archive = subprocess.run(
            ["git", "archive", "--format=tar", source_id],
            cwd    = bare_path,
            stdout = subprocess.PIPE,
            stderr = subprocess.PIPE,
        )
        if archive.returncode != 0:
            print(
                f"ERROR: git archive failed for {target} at {source_id[:16]}:\n"
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

    else:  # tarball
        lock    = KilnLock(config.lock_file)
        fetcher = TarballFetcher(config.tarball_cache_dir, lock)
        tarball = fetcher.cached_path(target, source)

        if tarball is None:
            print(
                f"ERROR: cached tarball missing or sha256 mismatch for {target}.\n"
                f"       Run 'kiln fetch' to re-download.",
                file=sys.stderr,
            )
            reporter.update(target, Status.ERROR)
            return False

        extract = subprocess.run(
            ["tar", "x", "--strip-components=1", "-f", str(tarball),
             "-C", str(source_dir)],
            stderr = subprocess.PIPE,
        )
        if extract.returncode != 0:
            print(
                f"ERROR: tarball extract failed for {target}:\n"
                f"       {extract.stderr.decode().strip()}",
                file=sys.stderr,
            )
            reporter.update(target, Status.ERROR)
            return False

    print(f"  {target}: checked out {source_id[:16]}")

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
    (state_dir / "checked_out").write_text(f"{source_id}\n", encoding="utf-8")

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
    """
    Run cmd inside a forge environment via the forge CLI subprocess.
    forge handles its own unshare -- kiln stays in user context throughout.
    Returns True on success.
    """
    
    print(f"DEBUG command cmd: {' '.join(cmd)}")
    reporter.update(target, status)
    effective_cwd = cwd or config.components_dir / target

    env = os.environ.copy()
    env['PYTHONPATH'] = str(_here)

    forge_cmd = [
        sys.executable, '-m', 'forge',
        '--cwd', str(effective_cwd),
        '--',
    ] + [str(c) for c in cmd]

    try:
        result = subprocess.run(forge_cmd, check=False, env=env)
        if result.returncode != 0:
            reporter.update(target, Status.ERROR)
            print(f"ERROR: {target}: command exited {result.returncode}", file=sys.stderr)
            return False
        return True
    except FileNotFoundError:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: forge not found -- is it installed?", file=sys.stderr)
        return False
    except Exception as exc:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: forge failed for {target}: {exc}", file=sys.stderr)
        return False


def _forge_run_script(config, target: str, script_body: str,
                      verb: str, reporter: Reporter, status: Status,
                      cwd: Path | None = None) -> bool:
    """
    Write script_body to __build__/kiln-<verb>.sh on the host,
    then run it inside forge via the forge CLI subprocess.
    The script file is left in place after the run for debugging.
    forge handles its own unshare -- kiln stays in user context throughout.
    """
    build_dir   = config.components_dir / target / "__build__"
    script_path = build_dir / f"kiln-{verb}.sh"

    # Prepend strict mode -- catches silent failures in multi-step scripts
    full_script = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + script_body
    script_path.write_text(full_script, encoding="utf-8")
    script_path.chmod(0o755)

    # Chroot-internal path to the script
    from kiln.builders.base import BuildPaths
    paths         = BuildPaths.for_component(target)
    chroot_script = f"{paths.build}/kiln-{verb}.sh"

    effective_cwd = cwd or build_dir

    env = os.environ.copy()
    env['PYTHONPATH'] = str(_here)

    forge_cmd = [
        sys.executable, '-m', 'forge',
        '--cwd', str(effective_cwd),
        '--', 'bash', chroot_script,
    ]

    reporter.update(target, status)
    try:
        result = subprocess.run(forge_cmd, check=False, env=env)
        if result.returncode != 0:
            reporter.update(target, Status.ERROR)
            print(
                f"ERROR: {target}: script exited {result.returncode}\n"
                f"       Script left at: {script_path}",
                file=sys.stderr,
            )
            return False
        return True
    except FileNotFoundError:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: forge not found -- is it installed?", file=sys.stderr)
        return False
    except Exception as exc:
        reporter.update(target, Status.ERROR)
        print(f"ERROR: forge failed for {target}: {exc}", file=sys.stderr)
        return False


def _resolve_verb(instance, verb: str, paths):
    """
    Return (script_body_or_None, cmd_or_None) for a given verb.
    Script takes precedence -- command_method is never called if script is set.
    """
    script_method = getattr(instance, f"{verb}_script", None)
    script        = script_method(paths) if script_method else None

    if script:
        return script, []

    command_method = getattr(instance, f"{verb}_command", None)
    cmd            = command_method(paths) if command_method else []

    return None, cmd


def verb_configure(target: str, config, reporter: Reporter) -> bool:
    """Run build system configure step inside forge."""
    from kiln.builders.base import BuildPaths

    if not _check_sentinel(config, target, "checked_out", "checkout"):
        return False

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = _resolve_verb(instance, "configure", paths)
    build_dir   = config.components_dir / target / "__build__"
    state_dir   = config.build_root / ".kiln" / "state" / target

    if script:
        ok = _forge_run_script(config, target, script, "configure",
                               reporter, Status.CONFIG, cwd=build_dir)
    elif cmd:
        ok = _forge_run(config, target, cmd, reporter, Status.CONFIG, cwd=build_dir)
    else:
        print(f"  {target}: no configure step -- skipping")
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
    elif cmd:
        ok = _forge_run(config, target, cmd, reporter, Status.BUILD, cwd=build_dir)
    else:
        print(f"  {target}: no build step -- skipping")
        reporter.update(target, Status.OK)
        return True
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
        print(f"  {target}: no test suite defined -- skipping")
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
    elif cmd:
        ok = _forge_run(config, target, cmd, reporter, Status.INSTALL, cwd=build_dir)
    else:
        print(f"  {target}: no install step -- skipping")
        reporter.update(target, Status.OK)
        return True
    if ok:
        reporter.update(target, Status.OK)
    return ok


def verb_clean(target: str, config, reporter: Reporter) -> bool:
    """Wipe __build__/ and __install__/ -- keep source and sysroot."""
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
    """Wipe everything -- source, sysroot, build, install."""
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


def verb_package(target: str, config, cache: TieredCache,
                 reporter: Reporter, push: bool) -> bool:
    """
    Split __install__/ into runtime and buildtime tarballs, write manifest,
    store in local artifact cache. With --push, also upload to Coffer.
    BuildDef components only -- use 'kiln assemble' for AssemblyDef.

    runtime.tar.zst   -- .so libs, binaries, etc (runtime_globs)
    buildtime.tar.zst -- headers, .a libs, pkgconfig (buildtime_globs)
    manifest.txt      -- full canonical manifest fields
    """
    import fnmatch
    import json

    if not _check_sentinel(config, target, "configured", "configure"):
        return False

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    # Type gate -- AssemblyDef components use 'kiln assemble' not 'kiln package'
    if reg.is_assembly_def(target):
        print(
            f"ERROR: '{target}' is an AssemblyDef -- use 'kiln assemble' instead.\n"
            f"       'kiln package' is only for BuildDef components.",
            file=sys.stderr,
        )
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

    # Validate --push preconditions early -- fail before doing any work
    if push and cache._coffer is None:
        print(
            f"ERROR: --push requires coffer_host to be set in [cache] config.\n"
            f"       Add coffer_host = \"user@host\" to forge.toml or ~/.kiln/config.toml",
            file=sys.stderr,
        )
        return False

    reporter.update(target, Status.PACKAGE)

    # --- Resolve manifest hash ---
    from kiln.dag import Resolver, ResolvedDAG, ResolveError

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

    if not runtime_files and not buildtime_files:
        print(
            f"ERROR: {target}: no files matched any glob pattern.\n"
            f"       Check that 'kiln install' ran successfully and that\n"
            f"       the install prefix matches runtime_globs/buildtime_globs.",
            file=sys.stderr,
        )
        reporter.update(target, Status.ERROR)
        return False

    if not runtime_files:
        print(f"  WARNING: {target}: no runtime files matched -- runtime tarball will be empty")
    if not buildtime_files:
        print(f"  WARNING: {target}: no buildtime files matched -- buildtime tarball will be empty")

    # --- Pack into tarballs ---
    with tempfile.TemporaryDirectory(prefix="kiln-package-") as tmp:
        tmp_path = Path(tmp)

        def pack(files: list[Path], tarball: Path) -> bool:
            if not files:
                result = subprocess.run(
                    ["tar", "--use-compress-program=zstd", "-cf", str(tarball),
                     "--files-from=/dev/null"],
                    stderr=subprocess.PIPE,
                )
            else:
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
                print(f"ERROR: tar failed: {result.stderr.decode().strip()}",
                      file=sys.stderr)
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

        manifest_data = instance.manifest_fields()
        manifest_data["manifest_hash"] = manifest_hash
        manifest_file.write_text(
            json.dumps(manifest_data, indent=2) + "\n",
            encoding="utf-8",
        )

        try:
            cache.store_local(manifest_hash, target, tmp_path)
        except Exception as exc:
            print(f"ERROR: local cache store failed: {exc}", file=sys.stderr)
            reporter.update(target, Status.ERROR)
            return False

        print(f"  {target}: cached locally as {manifest_hash[:16]}")

        if push:
            try:
                cache.publish(manifest_hash, target, tmp_path)
                print(f"  {target}: pushed to Coffer")
            except CofferUnavailable as exc:
                print(
                    f"ERROR: Coffer unreachable -- local cache written, push failed.\n"
                    f"       {exc.reason}\n"
                    f"       Re-run 'kiln package --push' when the server is available.",
                    file=sys.stderr,
                )
                reporter.update(target, Status.ERROR)
                return False
            except CacheError as exc:
                print(f"ERROR: Coffer push failed: {exc}", file=sys.stderr)
                reporter.update(target, Status.ERROR)
                return False

    reporter.update(target, Status.OK)
    return True


def verb_assemble(target: str, config, cache: TieredCache,
                  reporter: Reporter, push: bool) -> bool:
    """
    Assemble an AssemblyDef component -- fetch all dep runtime artifacts
    from cache and call instance.assemble_command().
    AssemblyDef components only -- use 'kiln package' for BuildDef.

    Output is written to <build_root>/.kiln/images/<target>/
    --push accepted but not yet implemented (future: registry push).
    """
    import shutil
    from kiln.dag import Resolver, ResolvedDAG, ResolveError

    reg, instance = _get_builder(target, config)
    if instance is None:
        return False

    # Type gate -- BuildDef components use 'kiln package' not 'kiln assemble'
    if reg.is_build_def(target):
        print(
            f"ERROR: '{target}' is a BuildDef -- use 'kiln package' instead.\n"
            f"       'kiln assemble' is only for AssemblyDef components.",
            file=sys.stderr,
        )
        return False

    reporter.update(target, Status.PACKAGE)

    # --- Resolve DAG to get manifest hashes for all deps ---
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
        print(f"ERROR: DAG resolution failed: {result.message}", file=sys.stderr)
        reporter.update(target, Status.ERROR)
        return False

    nodes     = result.components if isinstance(result, ResolvedDAG) else result.dag.components
    dep_nodes = [n for n in nodes if n.name != target and n.output_store == "cache"]

    # Fail fast -- all deps must be in cache
    missing = [n for n in dep_nodes if not n.cache_hit]
    if missing:
        names = ", ".join(n.name for n in missing)
        print(
            f"ERROR: deps not in cache: {names}\n"
            f"       Run 'kiln deps' to build missing deps first.",
            file=sys.stderr,
        )
        reporter.update(target, Status.ERROR)
        return False

    # --- Fetch all dep runtime artifacts into a temp staging area ---
    print(f"  {target}: fetching {len(dep_nodes)} dep runtime artifact(s)")

    with tempfile.TemporaryDirectory(prefix="kiln-assemble-") as tmp:
        tmp_path = Path(tmp)
        artifact_inputs: dict[str, Path] = {}   # name -> dir containing tarballs

        for node in dep_nodes:
            dep_dir = tmp_path / node.name
            dep_dir.mkdir()
            try:
                cache.fetch(node.manifest_hash, node.name, dep_dir)
            except CofferUnavailable as exc:
                print(f"ERROR: Coffer unreachable fetching {node.name}: {exc.reason}",
                      file=sys.stderr)
                reporter.update(target, Status.ERROR)
                return False
            except (CacheMiss, CacheError) as exc:
                print(f"ERROR: failed to fetch {node.name}: {exc}", file=sys.stderr)
                reporter.update(target, Status.ERROR)
                return False

            runtime = dep_dir / f"{node.name}.runtime.tar.zst"
            if not runtime.exists():
                print(
                    f"ERROR: {node.name} has no runtime tarball in cache.\n"
                    f"       Was it built with 'kiln package'?",
                    file=sys.stderr,
                )
                reporter.update(target, Status.ERROR)
                return False

            artifact_inputs[node.name] = dep_dir
            print(f"  {target}: fetched {node.name} ({node.manifest_hash[:12]})")

        # --- Output directory for assembled artifacts ---
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # --- Call the component's assemble_command ---
        try:
            instance.assemble_command(artifact_inputs, output_dir)
        except NotImplementedError as exc:
            print(f"ERROR: {target}: assemble_command not implemented: {exc}",
                  file=sys.stderr)
            reporter.update(target, Status.ERROR)
            return False
        except Exception as exc:
            print(f"ERROR: {target}: assemble failed: {exc}", file=sys.stderr)
            if os.environ.get("KILN_TRACEBACK"):
                import traceback
                traceback.print_exc()
            reporter.update(target, Status.ERROR)
            return False

        # --- Copy output to well-known location ---
        # <build_root>/.kiln/images/<target>/
        # Future: push to registry when --push is implemented
        image_dir = config.build_root / ".kiln" / "images" / target
        if image_dir.exists():
            shutil.rmtree(image_dir)
        image_dir.mkdir(parents=True)

        for f in output_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, image_dir / f.name)
                print(f"  {target}: wrote {f.name} -> {image_dir}")

        if push:
            print(f"  WARNING: {target}: --push not yet implemented for AssemblyDef")

    reporter.update(target, Status.OK)
    return True


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(verb: str, target: str, config, cache: TieredCache,
             reporter: Reporter, push: bool, dry_run: bool) -> bool:
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
    elif verb == "assemble":
        return verb_assemble(target, config, cache, reporter, push)
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
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] kiln {' '.join(sys.argv[1:])}", flush=True)

    print("---------------------------------------------------------------------------")
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