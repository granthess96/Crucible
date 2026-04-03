"""
kiln/verbs/source.py
Source verbs: fetch and checkout.
fetch   -- pull source into local cache, lock source identity
checkout -- export source, apply patches, populate sysroot
"""
from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path
import sys
from kiln.output import Reporter, Status
from kiln.cache import TieredCache, CacheMiss, CacheError, CofferUnavailable
from kiln.backends import make_resolver
from kiln.dag import ResolvedDAG, ResolveError

# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _populate_sysroot(
    target:      str,
    instance,
    config,
    cache:       TieredCache,
    sysroot_dir: Path,
) -> bool:
    """
    Unpack all dep artifacts into sysroot_dir.

    Extracts the full <n>.tar.zst for each dep — the sysroot gets
    everything so the compiler can find headers, shared libs, and
    static libs without any role filtering at this stage.

    Re-runs the resolver to get manifest hashes — fast, correct, no state
    file needed. Returns True on success, False with error printed on failure.
    """
    if not instance.deps:
        return True

    resolver = make_resolver(config, cache)
    result   = resolver.resolve(target)
    if isinstance(result, ResolveError):
        print(f"ERROR: dep resolution failed: {result.message}", file=sys.stderr)
        return False

    nodes     = (result.components if isinstance(result, ResolvedDAG)
                 else result.dag.components)
    dep_nodes = [n for n in nodes
                 if n.name != target and n.output_store == "cache"]

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
                print(
                    f"ERROR: Coffer unreachable while fetching dep "
                    f"{node.name}: {exc.reason}",
                    file=sys.stderr,
                )
                return False
            except (CacheMiss, CacheError) as exc:
                print(f"ERROR: failed to fetch dep {node.name}: {exc}",
                      file=sys.stderr)
                return False

            tarball = tmp_path / f"{node.name}.tar.zst"
            if not tarball.exists():
                print(
                    f"ERROR: dep {node.name} has no tarball in cache.\n"
                    f"       Was it built with 'kiln package'?",
                    file=sys.stderr,
                )
                return False

            unpack = subprocess.run(
                [
                    "tar", 
                    "--use-compress-program=zstd", 
                    "--keep-directory-symlink",
                    "-xf",
                     str(tarball), "-C", str(sysroot_dir)
                ],
                stderr=subprocess.PIPE,
            )
            if unpack.returncode != 0:
                print(
                    f"ERROR: failed to unpack {node.name} into sysroot:\n"
                    f"       {unpack.stderr.decode().strip()}",
                    file=sys.stderr,
                )
                return False

            print(f"  {target}: unpacked {node.name} ({node.manifest_hash[:12]})")

    return True

# ---------------------------------------------------------------------------
# verb_fetch
# ---------------------------------------------------------------------------

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
        print(f"ERROR: component '{target}' not found in components/",
              file=sys.stderr)
        return False

    instance = reg.instantiate(target)
    source   = getattr(instance, 'source', None)
    if not source:
        print(
            f"ERROR: {target}.source is empty -- add source spec to build.py",
            file=sys.stderr,
        )
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

    if stype == "none":
        (state_dir / "source_id").write_text("none", encoding="utf-8")
        (state_dir / "source_type").write_text("none", encoding="utf-8")
        print(f"  {target}: no source (synthetic component)")
        reporter.update(target, Status.OK)
        return True

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
        print(f"ERROR: unexpected error fetching {target}: {exc}",
              file=sys.stderr)
        return False

# ---------------------------------------------------------------------------
# verb_checkout
# ---------------------------------------------------------------------------

def _setup_usr_merge(root_dir: Path) -> None:
    """
    Force the UsrMerge layout on a directory before it is populated.
    Uses relative symlinks to ensure portability.
    """
    return # skip for now, debug test
    # 1. Create the targets first (the real directories)
    (root_dir / "usr/bin").mkdir(parents=True, exist_ok=True)
    (root_dir / "usr/lib").mkdir(parents=True, exist_ok=True)
    (root_dir / "usr/lib64").mkdir(parents=True, exist_ok=True)

    # 2. Map the legacy roots to the new usr locations
    # Note: Using relative targets (no leading slash) is vital for sysroots
    links = {
        "bin": "usr/bin",
        "sbin": "usr/bin",
        "lib": "usr/lib",
        "lib64": "usr/lib64"        
    }

    for link_name, target in links.items():
        link_path = root_dir / link_name
        if not link_path.exists():
            # Creates: root_dir/bin -> usr/bin
            link_path.symlink_to(target)

def verb_checkout(target: str, config, cache: TieredCache,
                  reporter: Reporter) -> bool:
    """
    Set up the complete build environment for a component:
      1. Verify kiln fetch was run (source_id exists)
      2. Wipe __source__/, __sysroot__/, __build__/, __install__/ for clean slate
      3. Export/extract source into __source__/
         - git:     git archive from bare clone at locked SHA
         - tarball: tar extract from cached tarball, strip leading directory
      4. Apply patches in lexicographic order
      5. Unpack all dep artifacts into __sysroot__/
      6. Create empty __build__/ and __install__/
      7. Create state directory
    Destructive -- always starts from a clean slate. No prompts.
    Precondition: kiln fetch must have run.
    All deps must be present in the artifact cache.
    """
    import shutil
    from kiln.registry import ComponentRegistry, RegistryError
    from kiln.fetcher import TarballFetcher
    from kiln.dag import KilnLock, _source_type

    try:
        reg = ComponentRegistry(config.components_dir)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return False

    if target not in reg:
        print(f"ERROR: component '{target}' not found in components/",
              file=sys.stderr)
        return False

    # --- Verify fetch was run ---
    state_dir = config.build_root / ".kiln" / "state" / target
    id_file   = state_dir / "source_id"
    type_file = state_dir / "source_type"

    instance      = reg.instantiate(target)
    source        = getattr(instance, 'source', {})
    component_dir = config.components_dir / target
    source_dir    = component_dir / "__source__"
    sysroot_dir   = component_dir / "__sysroot__"
    build_dir     = component_dir / "__build__"
    install_dir   = component_dir / "__install__"
    patches_dir   = component_dir / "patches"

    source_type = (type_file.read_text(encoding="utf-8").strip()
                   if type_file.exists() else "git")

    if source_type == "none":
        sysroot_dir.mkdir(exist_ok=True)
        build_dir.mkdir(exist_ok=True)
        install_dir.mkdir(exist_ok=True)
        print(f"  {target}: no source (synthetic component)")
        reporter.update(target, Status.OK)
        return True

    if not id_file.exists():
        print(
            f"ERROR: {target} has not been fetched.\n"
            f"       Run 'kiln fetch' first.",
            file=sys.stderr,
        )
        return False

    source_id = id_file.read_text(encoding="utf-8").strip()
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

    # --- Populate __sysroot__/ from dep artifacts ---
    sysroot_dir.mkdir()
    _setup_usr_merge(sysroot_dir)  # Ensure /usr merge prior to populating
    if not _populate_sysroot(target, instance, config, cache, sysroot_dir):
        reporter.update(target, Status.ERROR)
        return False

    # --- Create empty __build__/ and __install__/ ---
    build_dir.mkdir()
    install_dir.mkdir()
    _setup_usr_merge(install_dir)  # Prepare install directory for /usr merge

    state_dir.mkdir(parents=True, exist_ok=True)

    reporter.update(target, Status.OK)
    return True
