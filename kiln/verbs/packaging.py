"""
kiln/verbs/packaging.py
Packaging verbs: package and assemble.
package  -- split __install__/ into runtime + buildtime tarballs, cache
assemble -- compose cached runtime artifacts into image or container
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from kiln.output import Reporter, Status
from kiln.cache import TieredCache, CacheMiss, CacheError, CofferUnavailable
from kiln.dag import KilnLock, ResolvedDAG, ResolveError
from kiln.executor import get_builder, check_sentinel
from kiln.backends import make_resolver


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
    if not check_sentinel(config, target, "configured", "configure"):
        return False

    reg, instance = get_builder(target, config)
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
            f"       Add coffer_host = \"user@host\" to forge.toml or "
            f"~/.kiln/config.toml",
            file=sys.stderr,
        )
        return False

    reporter.update(target, Status.PACKAGE)

    # --- Resolve manifest hash ---
    resolver = make_resolver(config, cache)
    result   = resolver.resolve(target)
    if isinstance(result, ResolveError):
        print(f"ERROR: manifest resolution failed: {result.message}",
              file=sys.stderr)
        reporter.update(target, Status.ERROR)
        return False

    nodes       = (result.components if isinstance(result, ResolvedDAG)
                   else result.dag.components)
    target_node = next((n for n in nodes if n.name == target), None)
    if target_node is None:
        print(f"ERROR: {target} not found in resolved DAG", file=sys.stderr)
        reporter.update(target, Status.ERROR)
        return False

    manifest_hash = target_node.manifest_hash

    # --- Collect files by glob pattern ---
    def collect(globs: list[str]) -> list[Path]:
        """
        Match files (and symlinks) under install_dir against glob patterns.
        Uses PurePosixPath.full_match() which handles ** correctly across path
        separators.
        """
        matched = []
        for f in sorted(install_dir.rglob("*")):
            if not f.is_file() and not f.is_symlink():
                continue
            rel = f.relative_to(install_dir)
            for pattern in globs:
                if rel.full_match(pattern):
                    matched.append(f)
                    break
        return matched

    all_installed   = sorted(
        f for f in install_dir.rglob("*")
        if f.is_file() or f.is_symlink()
    )
    runtime_files   = collect(instance.runtime_globs)
    buildtime_files = collect(instance.buildtime_globs)

    # --- Unclassified file report -- nothing is ever silently dropped ---
    runtime_set   = set(runtime_files)
    buildtime_set = set(buildtime_files)
    unclassified  = [
        f for f in all_installed
        if f not in runtime_set and f not in buildtime_set
    ]
    print(f"  {target}: {len(runtime_files)} runtime, "
          f"{len(buildtime_files)} buildtime, "
          f"{len(unclassified)} unclassified  "
          f"({len(all_installed)} total installed files)")
    if unclassified:
        print(f"  {target}: UNCLASSIFIED (not captured in either tarball):")
        for f in unclassified:
            print(f"    unclassified: {f.relative_to(install_dir)}")

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
        print(f"  WARNING: {target}: no runtime files matched -- "
              f"runtime tarball will be empty")
    if not buildtime_files:
        print(f"  WARNING: {target}: no buildtime files matched -- "
              f"buildtime tarball will be empty")

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
                    f"ERROR: Coffer unreachable -- local cache written, "
                    f"push failed.\n"
                    f"       {exc.reason}\n"
                    f"       Re-run 'kiln package --push' when the server "
                    f"is available.",
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

    reg, instance = get_builder(target, config)
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
    resolver = make_resolver(config, cache)
    result   = resolver.resolve(target)
    if isinstance(result, ResolveError):
        print(f"ERROR: DAG resolution failed: {result.message}", file=sys.stderr)
        reporter.update(target, Status.ERROR)
        return False

    nodes     = (result.components if isinstance(result, ResolvedDAG)
                 else result.dag.components)
    dep_nodes = [n for n in nodes
                 if n.name != target and n.output_store == "cache"]

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
        artifact_inputs: dict[str, Path] = {}

        for node in dep_nodes:
            dep_dir = tmp_path / node.name
            dep_dir.mkdir()
            try:
                cache.fetch(node.manifest_hash, node.name, dep_dir)
            except CofferUnavailable as exc:
                print(
                    f"ERROR: Coffer unreachable fetching {node.name}: "
                    f"{exc.reason}",
                    file=sys.stderr,
                )
                reporter.update(target, Status.ERROR)
                return False
            except (CacheMiss, CacheError) as exc:
                print(f"ERROR: failed to fetch {node.name}: {exc}",
                      file=sys.stderr)
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
            print(
                f"ERROR: {target}: assemble_command not implemented: {exc}",
                file=sys.stderr,
            )
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
        image_dir = config.build_root / ".kiln" / "images" / target
        if image_dir.exists():
            shutil.rmtree(image_dir)
        image_dir.mkdir(parents=True)

        for f in output_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, image_dir / f.name)
                print(f"  {target}: wrote {f.name} -> {image_dir}")

        if push:
            print(f"  WARNING: {target}: --push not yet implemented "
                  f"for AssemblyDef")

    reporter.update(target, Status.OK)
    return True