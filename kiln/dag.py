"""
kiln/dag.py

Dependency DAG resolver.

Responsibilities (in execution order):
  1. Load the DAG transitively from a target component name
  2. Detect cycles and missing components → ResolveError
  3. Topo-sort (leaves first)
  4. For each node in topo order:
       a. Generate manifest.txt (requires dep manifests already computed)
       b. Hash manifest → cache / registry key
       c. Stat the appropriate backend
       d. Record hit or miss
  5. Return ResolvedDAG, BuildSchedule, or ResolveError

Contract:
  - Pure planning phase — no builds, no fetches, no writes
  - No parallelism — even a slow resolve is faster than one build
  - Correctness and clarity over performance
  - Network/backend failure → ResolveError (not a silent miss)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from kiln.builders.base import BuildDef, KilnComponent
from kiln.manifest import Manifest, hash_file, hash_directory_tree
from kiln.registry import ComponentRegistry, RegistryError


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ComponentNode:
    name:          str
    version:       str
    manifest:      Manifest
    cache_hit:     bool
    output_store:  Literal["cache", "registry"]   # BuildDef→cache, AssemblyDef→registry
    dep_nodes:     list["ComponentNode"] = field(default_factory=list)
    build_weight:  int = 1

    @property
    def manifest_hash(self) -> str:
        return self.manifest.hash

    def __repr__(self) -> str:
        hit = "HIT" if self.cache_hit else "MISS"
        return f"<ComponentNode {self.name}=={self.version} {hit} {self.output_store}>"


@dataclass
class ResolvedDAG:
    """All components satisfied — ready to use."""
    target:     str
    components: list[ComponentNode]   # topo-sorted, leaves first

    def __repr__(self) -> str:
        return f"<ResolvedDAG target={self.target} components={len(self.components)}>"


@dataclass
class BuildSchedule:
    """Some components are missing — ordered_misses must be built."""
    target:         str
    dag:            ResolvedDAG          # full DAG including hits
    ordered_misses: list[ComponentNode]  # subset, topo-ordered, safe to execute sequentially

    def __repr__(self) -> str:
        return (
            f"<BuildSchedule target={self.target} "
            f"hits={len(self.dag.components) - len(self.ordered_misses)} "
            f"misses={len(self.ordered_misses)}>"
        )


@dataclass
class ResolveError(Exception):
    """Resolution failed — build cannot proceed."""
    kind: Literal[
        "cycle",
        "missing_component",
        "invalid_build_def",
        "backend_unavailable",
        "weight_exceeds_capacity",
    ]
    message: str
    involved: list[str] = field(default_factory=list)   # component names implicated

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"

    def __repr__(self) -> str:
        return f"<ResolveError {self.kind}: {self.message}>"


# Type alias for resolver return
ResolveResult = ResolvedDAG | BuildSchedule | ResolveError


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------

class BackendUnavailableError(Exception):
    """Raised by a cache or registry backend when it cannot be reached."""
    pass


class CacheBackend:
    """Protocol — implement for local disk, S3, etc."""
    def stat(self, key: str) -> bool:
        raise NotImplementedError

    def fetch(self, key: str, dest: Path) -> None:
        raise NotImplementedError

    def store(self, key: str, src: Path) -> None:
        raise NotImplementedError


class RegistryBackend:
    """Protocol — implement for local OCI, remote registry, etc."""
    def stat(self, key: str) -> bool:
        raise NotImplementedError

    def push(self, key: str, src: Path) -> str:
        raise NotImplementedError

    def pull(self, key: str, dest: Path) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Lock file — stores resolved source identities
#
# Format (one entry per line):
#   <component>.commit <sha>          git commit SHA (from tag/branch resolution)
#   <component>.sha256 <hex>          tarball sha256 (established on first fetch)
#   <component>.url    <url>          tarball URL (to detect url changes in build.py)
#
# The lock file is committed to the repo. It makes builds reproducible:
#   - git: tag refs are resolved once and locked; re-resolving is skipped
#   - tarball: sha256 is established on first fetch; subsequent fetches
#     verify the downloaded bytes match — mismatch is a hard error
# ---------------------------------------------------------------------------

class KilnLock:
    """
    kiln.lock — committed to the meta-build repo.

    Stores source identity for each component:
      git components:     <name>.commit <sha>
      tarball components: <name>.sha256 <hex>
                          <name>.url    <url>
    """

    def __init__(self, lock_path: Path):
        self._path = lock_path
        self._data: dict[str, str] = {}
        if lock_path.exists():
            self._load()

    def _load(self) -> None:
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                self._data[parts[0]] = parts[1]

    def _get(self, key: str) -> str | None:
        return self._data.get(key)

    def _set(self, key: str, value: str) -> None:
        self._data[key] = value

    # --- Git ---

    def get_commit(self, component_name: str) -> str | None:
        """Return locked git commit SHA, or None if not yet fetched."""
        return self._get(f"{component_name}.commit")

    def set_commit(self, component_name: str, commit_sha: str) -> None:
        self._set(f"{component_name}.commit", commit_sha)

    # --- Tarball ---

    def get_sha256(self, component_name: str) -> str | None:
        """Return locked tarball sha256, or None if not yet fetched."""
        return self._get(f"{component_name}.sha256")

    def set_sha256(self, component_name: str, sha256: str) -> None:
        self._set(f"{component_name}.sha256", sha256)

    def get_url(self, component_name: str) -> str | None:
        """Return the URL that was used when the sha256 was locked."""
        return self._get(f"{component_name}.url")

    def set_url(self, component_name: str, url: str) -> None:
        self._set(f"{component_name}.url", url)

    # --- Source type detection ---

    def source_type(self, component_name: str) -> Literal["git", "tarball", "unknown"]:
        """Infer what kind of source is locked for this component."""
        if self._get(f"{component_name}.commit") is not None:
            return "git"
        if self._get(f"{component_name}.sha256") is not None:
            return "tarball"
        return "unknown"

    # --- Persistence ---

    def write(self) -> None:
        lines = ["# kiln.lock — auto-generated, commit this file\n"]
        for key in sorted(self._data):
            lines.append(f"{key} {self._data[key]}\n")
        self._path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class Resolver:
    """
    Resolves a target component into a ResolvedDAG, BuildSchedule, or ResolveError.

    Usage:
        resolver = Resolver(
            components_root = Path("components"),
            cache   = local_cache_backend,
            registry= registry_backend,
            lock    = KilnLock(Path("kiln.lock")),
            forge_base_hash  = "sha256:...",
            toolchain_hash   = "sha256:...",
            max_weight       = 32,
        )
        result = resolver.resolve("rocm-stack-workstation")
    """

    def __init__(
        self,
        components_root:  Path,
        cache:            CacheBackend,
        registry:         RegistryBackend,
        lock:             KilnLock,
        forge_base_hash:  str,
        toolchain_hash:   str,
        max_weight:       int = 8,
    ):
        self._registry       = ComponentRegistry(components_root)
        self._cache          = cache
        self._reg_backend    = registry
        self._lock           = lock
        self._forge_base     = forge_base_hash
        self._toolchain      = toolchain_hash
        self._max_weight     = max_weight

        # Memoisation — component name → ComponentNode
        # Populated in topo order; later nodes can reference earlier nodes' manifests
        self._resolved: dict[str, ComponentNode] = {}

    def resolve(self, target: str) -> ResolveResult:
        # --- Step 1: Load DAG, detect cycles and missing components ---
        try:
            order, dep_map = self._topo_sort(target)
        except ResolveError as err:
            return err
        except RegistryError as err:
            return ResolveError(
                kind="invalid_build_def",
                message=str(err),
                involved=[err.component_dir.name],
            )

        # --- Step 2: For each node in topo order, generate manifest and stat ---
        nodes: list[ComponentNode] = []

        for name in order:
            try:
                node = self._build_node(name, dep_map[name])
            except BackendUnavailableError as err:
                return ResolveError(
                    kind="backend_unavailable",
                    message=str(err),
                    involved=[name],
                )
            except ResolveError as err:
                return err

            self._resolved[name] = node
            nodes.append(node)

        # --- Step 3: Weight sanity check (warn, not error — solo mode handles it) ---
        # (no error returned — oversized weight → solo mode, still runs)

        # --- Step 4: Return appropriate result ---
        dag = ResolvedDAG(target=target, components=nodes)
        misses = [n for n in nodes if not n.cache_hit]

        if not misses:
            return dag
        return BuildSchedule(target=target, dag=dag, ordered_misses=misses)

    # --- DAG loading and topo-sort ---

    def _topo_sort(self, target: str) -> tuple[list[str], dict[str, list[str]]]:
        """
        Load the DAG from target, return (topo_order, dep_map).
        topo_order is leaves-first (dependencies before dependents).
        Raises ResolveError on cycle or missing component.
        """
        dep_map: dict[str, list[str]] = {}
        queue = [target]
        visited: set[str] = set()

        while queue:
            name = queue.pop(0)
            if name in visited:
                continue
            visited.add(name)

            if name not in self._registry:
                raise ResolveError(
                    kind="missing_component",
                    message=f"component '{name}' not found in components/",
                    involved=[name],
                )

            instance = self._registry.instantiate(name)
            deps = list(instance.deps)
            dep_map[name] = deps

            for dep in deps:
                if dep not in visited:
                    queue.append(dep)

        # Kahn's algorithm for topo sort + cycle detection
        in_degree: dict[str, int] = {n: 0 for n in dep_map}
        dependents: dict[str, list[str]] = {n: [] for n in dep_map}

        for name, deps in dep_map.items():
            for dep in deps:
                in_degree[name] += 1
                dependents[dep].append(name)

        ready = sorted([n for n, d in in_degree.items() if d == 0])
        order: list[str] = []

        while ready:
            name = ready.pop(0)
            order.append(name)
            for dependent in sorted(dependents[name]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)

        if len(order) != len(dep_map):
            involved = [n for n in dep_map if n not in order]
            raise ResolveError(
                kind="cycle",
                message=f"dependency cycle detected among: {involved}",
                involved=involved,
            )

        return order, dep_map

    # --- Node construction ---

    def _build_node(self, name: str, dep_names: list[str]) -> ComponentNode:
        instance = self._registry.instantiate(name)
        #is_build = self._registry.is_build_def(name)
        is_build = True # all components are now BuildDefs, AssemblyDef is deprecated

        dep_nodes = [self._resolved[d] for d in dep_names]

        fields = instance.manifest_fields()

        # Add dep manifest hashes — deterministic order (sorted by dep name)
        for dep_name in sorted(dep_names):
            fields[f"dep:{dep_name}"] = self._resolved[dep_name].manifest_hash

        manifest = Manifest(
            component=name,
            version=instance.version,
            fields=fields,
        )

        # Populate resolver fields for BuildDef components.
        # Source identity goes in as either source_commit (git) or
        # source_sha256 (tarball) — both serve the same role in the hash.
        if is_build:
            source      = getattr(instance, "source", {})
            source_type = _source_type(source)

            manifest = manifest.with_resolved(
                source_commit = self._lock.get_commit(name) if source_type == "git" else None,
                source_sha256 = self._lock.get_sha256(name) if source_type == "tarball" else None,
                builder_hash  = hash_file(self._registry.build_py_path(name)),
                patches_hash  = self._hash_patches(name),
                forge_base    = self._forge_base,
                toolchain     = self._toolchain,
            )

        output_store: Literal["cache", "registry"] = "cache" if is_build else "registry"
        print(f"  checking: {name}", flush=True)
        cache_hit = self._stat(name, manifest.hash, output_store)

        return ComponentNode(
            name         = name,
            version      = instance.version,
            manifest     = manifest,
            cache_hit    = cache_hit,
            output_store = output_store,
            dep_nodes    = dep_nodes,
            build_weight = instance.build_weight,
        )

    def _hash_patches(self, name: str) -> str | None:
        patches_dir = self._registry.patches_dir(name)
        if patches_dir is None:
            return None
        return hash_directory_tree(patches_dir)

    def _stat(
        self,
        name: str,
        manifest_hash: str,
        output_store: Literal["cache", "registry"],
    ) -> bool:
        try:
            if output_store == "cache":
                return self._cache.stat(manifest_hash)
            else:
                return self._reg_backend.stat(manifest_hash)
        except Exception as exc:
            raise BackendUnavailableError(
                f"backend unavailable while checking '{name}' "
                f"(store={output_store}): {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Source type helper
# ---------------------------------------------------------------------------

def _source_type(source: dict) -> Literal["git", "tarball", "none", "unknown"]:
    """Classify a source dict from a build.py."""
    if "git" in source:
        return "git"
    if "url" in source:
        return "tarball"
    if "source_type" in source and source["source_type"] == "none":
        return "none"
    return "unknown"
