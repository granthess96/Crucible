"""
kiln/verbs/packaging.py
Packaging verb: package.

package -- assign roles to __install__/ files via path inference + FileSpec
           overrides, write manifest, store single tarball in cache.

Role assignment
---------------
Every file under __install__/ receives a Role via path_role() below.
The component's `files` list (list[FileSpec]) contains overrides for the
minority of paths where the heuristic would guess wrong.  FileSpec paths
are matched as globs using PurePosixPath.full_match() against the
install-relative path.  The first matching FileSpec wins; unmatched files
fall through to path_role().

Files with role 'exclude' are silently dropped from the tarball.

Output
------
  <target>.tar.zst          -- all non-excluded files, flat tarball
  <target>.files.json.zst   -- compressed path→role index (for cast)
  <target>.manifest.txt     -- build identity / manifest hash

cast fetches the files index first (small), decides which roles it needs,
then fetches the tarball and extracts only the relevant paths.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from kiln.output import Reporter, Status
from kiln.cache import TieredCache, CacheMiss, CacheError, CofferUnavailable
from kiln.dag import KilnLock, ResolvedDAG, ResolveError
from kiln.executor import get_builder, check_sentinel
from kiln.backends import make_resolver
from kiln.spec import Role

# ---------------------------------------------------------------------------
# Path inference
# ---------------------------------------------------------------------------

def path_role(rel: PurePosixPath) -> Role:
    """
    Infer a Role from an install-relative path.

    Covers the common FHS layouts produced by autotools / cmake / meson.
    FileSpec entries on the component override this for exceptions.
    """
    parts = rel.parts
    if not parts:
        return 'runtime'

    top = parts[0]
    name = rel.name
    suffix = rel.suffix          # last extension, e.g. '.so', '.h', '.a'
    suffixes = rel.suffixes      # all extensions, e.g. ['.so', '.6', '.0']

    # ---- dev ---------------------------------------------------------------
    # Headers
    if top in ('usr',) and len(parts) > 1 and parts[1] == 'include':
        return 'dev'
    if top == 'include':
        return 'dev'

    # Static libs and object files (crt*.o, etc.)
    if suffix in ('.a', '.o', '.lo'):
        return 'dev'

    # libtool archives
    if suffix == '.la':
        return 'dev'

    # pkg-config / cmake / aclocal / autoconf data
    if 'pkgconfig' in parts:
        return 'dev'
    if 'cmake' in parts:
        return 'dev'
    if 'aclocal' in parts:
        return 'dev'

    # ---- debug -------------------------------------------------------------
    # Must run before the .so suffix check: a .so inside a .debug/ dir is
    # debug output, not a linker stub.
    if '.debug' in parts:
        return 'debug'
    if 'debug' in parts and top in ('usr', 'lib', 'lib64'):
        return 'debug'
    if suffix == '.debug':
        return 'debug'

    # Unversioned .so symlinks (e.g. libfoo.so) — linker inputs, dev only.
    # Versioned .so files (libfoo.so.6, libfoo.so.6.0.0) are runtime.
    # Heuristic: exactly one suffix and it is '.so' → dev.
    if suffixes and suffixes[-1] == '.so' and len(suffixes) == 1:
        return 'dev'

    # ---- doc ---------------------------------------------------------------
    if top in ('usr',) and len(parts) > 1 and parts[1] in ('share',):
        if len(parts) > 2 and parts[2] in ('man', 'info', 'doc', 'gtk-doc',
                                            'devhelp'):
            return 'doc'
    if top in ('usr', 'share') and 'man' in parts:
        return 'doc'
    if top in ('usr', 'share') and 'info' in parts:
        return 'doc'
    if top == 'usr' and len(parts) > 1 and parts[1] == 'man':
        return 'doc'

    # ---- config ------------------------------------------------------------
    if top == 'etc':
        return 'config'
    if top == 'usr' and len(parts) > 1 and parts[1] == 'etc':
        return 'config'

    # ---- tool --------------------------------------------------------------
    # Build-time tools that shouldn't land in the target sysroot.
    # Heuristic: anything under usr/share/locale gets 'runtime' (it's data),
    # but binaries under the cross-compile host prefix are 'tool'.
    # This is intentionally narrow — most usr/bin things are 'runtime'.
    # Components that need finer control use FileSpec.

    # ---- runtime (default) -------------------------------------------------
    return 'runtime'


# ---------------------------------------------------------------------------
# FileSpec glob matching
# ---------------------------------------------------------------------------

def _resolve_role(rel: PurePosixPath, spec_overrides: list) -> Role:
    """
    Return the role for rel, applying FileSpec overrides before path_role().
    First matching FileSpec wins.
    """
    rel_str = str(rel)
    for spec in spec_overrides:
        if rel.full_match(spec.path):
            return spec.role
    return path_role(rel)


# ---------------------------------------------------------------------------
# verb_package
# ---------------------------------------------------------------------------

def verb_package(target: str, config, cache: TieredCache,
                 reporter: Reporter, push: bool) -> bool:
    """
    Assign roles to __install__/ files, pack into cache artifact.

      <target>.tar.zst         -- all non-excluded files, flat
      <target>.files.json.zst  -- compressed path→role index
      <target>.manifest.txt    -- build identity / manifest hash
    """
    if not check_sentinel(config, target, "configured", "configure"):
        return False

    reg, instance = get_builder(target, config)
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

    # Validate --push preconditions early
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

    # --- Collect and classify all installed files ---
    spec_overrides = getattr(instance, 'files', [])

    all_installed = sorted(
        f for f in install_dir.rglob("*")
        if f.is_file() or f.is_symlink()
    )

    if not all_installed:
        print(
            f"ERROR: {target}: no files found under __install__/.\n"
            f"       Run 'kiln install' first.",
            file=sys.stderr,
        )
        reporter.update(target, Status.ERROR)
        return False

    # role → [Path]
    by_role: dict[Role, list[Path]] = {}
    for f in all_installed:
        rel  = f.relative_to(install_dir)
        role = _resolve_role(PurePosixPath(rel), spec_overrides)
        by_role.setdefault(role, []).append(f)

    excluded  = by_role.pop('exclude', [])
    to_pack   = [f for files in by_role.values() for f in files]

    # Summary
    counts = {r: len(fs) for r, fs in sorted(by_role.items())}
    count_str = ', '.join(f"{r}={n}" for r, n in counts.items())
    print(f"  {target}: {len(to_pack)} files to pack "
          f"({count_str}"
          + (f", excluded={len(excluded)}" if excluded else "")
          + f")  [{len(all_installed)} total installed]")

    if not to_pack:
        print(
            f"ERROR: {target}: all files excluded or __install__/ empty.",
            file=sys.stderr,
        )
        reporter.update(target, Status.ERROR)
        return False

    # --- Pack ---
    with tempfile.TemporaryDirectory(prefix="kiln-package-") as tmp:
        tmp_path = Path(tmp)

        tarball      = tmp_path / f"{target}.tar.zst"
        files_index  = tmp_path / f"{target}.files.json.zst"
        manifest_file = tmp_path / f"{target}.manifest.txt"

        filelist = tmp_path / "filelist.txt"
        filelist.write_text(
            "\n".join(str(f.relative_to(install_dir)) for f in sorted(to_pack))
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
            reporter.update(target, Status.ERROR)
            return False

        # --- Write compressed file index ---
        # cast fetches this first to decide which roles it needs, then
        # selectively extracts from the tarball.
        index_data = {
            "component":     target,
            "version":       instance.version,
            "manifest_hash": manifest_hash,
            "files": {
                str(f.relative_to(install_dir)): _resolve_role(
                    PurePosixPath(f.relative_to(install_dir)), spec_overrides
                )
                for f in sorted(to_pack)
            },
        }
        index_json = json.dumps(index_data, indent=None, separators=(',', ':')).encode()
        result = subprocess.run(
            ["zstd", "-q", "-o", str(files_index)],
            input=index_json,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            print(f"ERROR: zstd (files index) failed: {result.stderr.decode().strip()}",
                  file=sys.stderr)
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
