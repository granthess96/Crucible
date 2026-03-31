# Crucible TODO

A running list of design decisions, planned work, and deferred items.
**Zone 1** (below) is the stable ground-truth task list — edit deliberately.
**Zone 2** (bottom) is the session log — append summaries here, promote items to Zone 1.

---

## Zone 1 — Standing TODO

---

### Forge — Completed

#### ✓ forge — stdlib shadowing bug (FIXED)

PYTHONPATH isolation resolved. `forge/instance.py` shlex imports now resolve correctly to stdlib. 

### Kiln — Active Tasks

**HIGH PRIORITY:**

- [ ] **Packaging Model (framework complete, awaiting deployment)**: FileSpec-based
      policy-driven artifact classification is fully implemented in verb_package().
      Defines seven roles (runtime, tool, dev, doc, config, debug, exclude) with
      path inference + explicit overrides. All infrastructure complete:
      - path_role() FHS-based heuristics
      - _resolve_role() FileSpec glob matching
      - files.json.zst role index output (for cast)
      
      **Next step:** Identify edge-case components that need FileSpec overrides
      (e.g., glibc ld-linux case, overlapping .so files) and add explicit
      `files` list declarations. Path inference alone handles most cases.

**CORE FUNCTIONALITY:**

- [ ] Visual distinction on `kiln deps --dry-run` output:
      local-only hit, remote-only hit, and both-local-and-remote should
      display differently. Easy win, improves cache transparency.

- [ ] Builder base class cache invalidation:
      Changes to `kiln/builders/base.py` (AutotoolsBuild, CMakeBuild, etc.)
      do not currently invalidate the cache. The manifest hash only covers
      the component's own `build.py` via `builder_hash`.
      Fix: include a hash of the builder base class file (or the specific
      base class used) in the manifest.
      **Hold:** do not enable until kiln is stable — cache rebuilds are
      expensive and minor edits during development should not trigger misses.

- [ ] `tools.sqsh` contents: document formally so the image can be
      reproduced independently. Provenance matters once it is pulled from Vault.
      **Note:** This effort migrates to the new `Cast` tool for image reproduction.

- [ ] `kiln init` command — scaffold a new project with a `forge.toml`
      template (template already exists in `crucible/config.py` as
      `FORGE_TOML_TEMPLATE`).

---

### Kiln — Deferred / Design

- [ ] Parallel builds (future goal, migrate to `crucible` tool):
      DAG topological order is already correct (leaves first).
      Long-term: a scheduler that dispatches any node whose dependencies
      are all cache hits or completed this run. `build_weight` is already
      present on each node.
      **Not an immediate task** — design needs more thought before implementation.
      **Note:** Parallel scheduling capability may be implemented in the
      upcoming `crucible` tool rather than directly in kiln.

---

### Vault — Active Tasks

- [ ] Design and implement Vault API for promoted artifact / image storage:
      - `--publish` flag on `kiln package` → promote artifact to Vault
        (permanent record, explicitly weightier than `--push` to Coffer)
      - Full OCI / image registry role beyond the current sqsh use case
      **Blocked on:** `verb_assemble` working correctly first.

---

### Coffer — Active Tasks

- [ ] `cachectl list` command: cache inspection from the client side.
      Low priority but useful for CI debugging.

- [ ] CI integration documentation:
      Document `KILN_PUBLISH_TOKEN` + `KILN_COFFER_HOST` env vars and
      expected SSH key setup for CI → Coffer authentication.

---

### Per-Build Provenance Artifacts (Design — Active)

Every component build should eventually produce audit artifacts stored
adjacent to the runtime/buildtime tarballs in the cache entry.

Every component build should eventually produce audit artifacts stored
adjacent to the runtime/buildtime tarballs in the cache entry.

**File manifest:** after `kiln install`, walk `__install__/` and record
every installed file with path, size, and blake3 hash. Store as
`<target>.filelist.txt` in the cache entry. Not part of the manifest hash
(does not affect cache invalidation) but adjacent for audit purposes.

**Build logs:** capture stdout+stderr of each forge invocation (configure,
build, test, install). Compress with zstd. Store as
`<target>.buildlog.tar.zst` in the cache entry.

**Provenance attestation:** `verb_assemble` produces
`<name>.provenance.json` alongside image output. Contains per-component:
manifest fields, source identity, forge base + toolchain hashes, kiln.lock
entries for full source pinning. Goes into image output dir, pushed to
Vault with the image.

**Implementation notes (when ready):**
- `_forge_run()` / `_forge_run_script()` tee stdout+stderr to
  `__build__/kiln-<verb>.log` while still streaming to terminal in verbose mode.
- `verb_package()` collects per-verb logs, compresses, stores alongside tarballs.
- Filelist generation in `verb_package()` before tarball packing.
- `cache.fetch()` / `_populate_sysroot` unpack logs into
  `__sysroot__/build_logs/<depname>/` and manifests into
  `__sysroot__/manifests/<depname>.manifest.txt`.

---

### Packaging Model (Design — High Priority, Partially Implemented)

Long-term direction: evolve Kiln's packaging from a glob-based file
selector into a policy-driven, observable, reproducible artifact classifier.

**Status:** Partially implemented. This is the highest priority item
given existing glob-based limitations (overlapping .so files, ld-linux edge case).

Key principles:
- Every file in `__install__` must be explicitly classified: runtime,
  buildtime, or unclassified (never silently dropped).
- `PackagePolicy` per component: strict mode, fail-on-unclassified,
  overlap rules.
- Glob composition modes: replace (default), append (`_add`), method override.
- `__provenance__` as a first-class output directory, separate from
  `__install__` — contains logs, manifests, SBOM-style metadata.
- Long-term compatibility with dependency-closure-based runtime generation
  and hardware-targeted binary selection (ROCm/CUDA).

**Priority:** HIGH. Addresses existing glob issues and provides the
foundation for explicit packaging policy per component.

---

### General

- [ ] `crucible/log.py` shared logging helper:
      - `init(log_path: Path | None)` and `log(msg: str)`
      - Timestamps in `[YYYY-MM-DDTHH:MM:SS]` format on every line
      - All output goes to stdout AND appends to log file
      - Replace ad-hoc prints in `kiln/__main__.py`, `forge/__main__.py`,
        `kiln/dag.py`

- [ ] `README.md` rewrite — current README is not informative.
      Defer until design stabilises further.

---

## Zone 2 — Session Log

*Append LLM session summaries here. Promote concrete tasks to Zone 1.*

---

### 2026-03-31 — FileSpec implementation audit and trace

Traced FileSpec implementation through codebase. Found that the packaging model
framework is **complete and fully operational**:

**Implementation summary:**
- kiln/spec.py: Seven-role FileSpec dataclass (runtime, tool, dev, doc, config, debug, exclude)
- kiln/verbs/packaging.py: Complete integration
  - path_role() implements FHS-based inference heuristics (82 lines, comprehensive)
  - _resolve_role() applies FileSpec glob overrides before fallback
  - verb_package() extracts spec_overrides from component.files, classifies all files
  - Outputs files.json.zst (compressed path→role index) for downstream cast tool
  - Supports file exclusion (role='exclude')

**Current state:**
- ✅ All infrastructure implemented and operational
- ✅ Path inference covers 90% of common cases (headers, .so versioning, etc.)
- ❌ No components currently use FileSpec overrides (all rely on inference)
- ⏳ Ready for deployment: identify components needing explicit overrides

**Next step:** Identify edge-case components and add FileSpec lists:
1. glibc — ld-linux dual runtime/dev case
2. Any components with overlapping .so (both versioned runtime and unversioned dev)
3. Build tools that should be marked 'tool' instead of 'runtime'

---

Reviewed all standing TODOs against current codebase state. Results:

**FIXED (1):**
- ✓ forge stdlib shadowing bug — PYTHONPATH isolation resolved

**DEPRECATED (2):**
- ✗ verb_assemble (squashfs image assembly) — Image composition moved to separate tools (not part of kiln core)
- ✗ Test coverage (CofferBackend, TieredCache, etc) — Deferred indefinitely; unit test infrastructure not a blocker

**STILL RELEVANT (11):**
- Packaging Model (HIGH PRIORITY) — Partially implemented; glob-based system has known issues
- Visual cache distinction on `kiln deps --dry-run` — Useful for transparency
- Builder base class cache invalidation — Hold until kiln stable
- tools.sqsh documentation — Migrates to Cast tool
- kiln init command — Scaffold new projects
- Parallel builds — Migrate to crucible tool
- Vault API and --publish flag — Permanent artifact storage
- cachectl list — Cache inspection for CI
- CI integration docs — Env vars and SSH setup
- Per-build provenance artifacts — File manifests, build logs, attestation
- crucible/log.py helper — Shared logging infrastructure

---

### 2026-03-22 — TODO audit and restructure

Audited full TODO.md against current codebase state. The following were
confirmed done and removed from the active list:

- `kiln --push` wired through `verb_package` ✓
- `kiln deps` and `kiln deps --dry-run` verbs implemented ✓
- Tarball fetch support implemented ✓
- `kiln.lock` records tarball sha256 and git SHAs ✓
- `base.sqsh` and `tools.sqsh` pulling from Vault (Garage S3 backend) ✓
- Forge `--create` verb and `BASE_PACKAGES` deleted ✓
- cmake component converted from AutotoolsBuild to CMakeBuild ✓
- Coreutils switched to release tarball source ✓

Removed as obsolete or wrong direction:
- Autotools bootstrap prerequisites list (moot with tarball-first approach)
- `coffer_cachectl` path override (already in dataclass; deferred as rare case)

Sequencing note: `verb_assemble` must be working before `--publish` flag
and full Vault promotion API are worth implementing.

### 2026-03-23 -- Refactor / Redesign conversation with Claude AI
Here's the full list, grouped by layer:

Dep — structured dependency model
Replace deps: ClassVar[list[str]] with a Dep dataclass:
python@dataclass
class Dep:
    name:    str
    mode:    Literal["build", "runtime", "both"] = "both"
    version: str = ""      # semver constraint, "" = any
    order:   int = 100     # lower = unpacked first in assembly

mode="build" — goes into __sysroot__/ only, never into images
mode="runtime" — goes into images only, not into __sysroot__/
mode="both" — goes everywhere (glibc's ld-linux case)
order=0 on filesystem replaces the unpack_order special case
Flat string deps migrate via a compatibility shim so existing build.py files keep working


InstallFile — explicit packaging manifests
Replace glob classification in verb_package with per-component declarations:
python@dataclass
class InstallFile:
    pattern: str           # relative to __install__/, globs ok
    mode:    DepMode       # "build", "runtime", "both"

Builder subclasses (AutotoolsBuild, CMakeBuild) provide sensible defaults
Problem components like glibc override install_manifest() explicitly
Unclassified files become a hard error, not a warning
mode="both" means the file appears in both tarballs — solves the ld-linux problem cleanly
Glob fallback stays on BuildDef base class for unmitigated components


__sysroot__ population — unpack everything
_populate_sysroot currently unpacks only buildtime artifacts. Change it to unpack both runtime and buildtime tarballs for all deps. Rationale:

The sysroot is a simulated target root, not just a compilation aid
configure test programs need to execute against real runtime libs
With Dep.mode filtering, build-only deps (gcc, cmake) don't bloat the sysroot — only mode="both" and mode="runtime" deps get unpacked


skip_verbs on BuildDef
pythonskip_verbs: ClassVar[set[str]] = set()
Opt-out rather than opt-in — new verbs run by default, components declare exceptions. Dispatch checks before calling into forge:
pythonif verb in getattr(instance, 'skip_verbs', set()):
    reporter.update(target, Status.SKIPPED)
    return True

AssemblyDef layer infrastructure
Move shared unpack logic up from ImageDef into AssemblyDef:
pythondef _ordered_inputs(self, artifact_inputs) -> list[tuple[str, Path]]:
    # sort by Dep.order from self.deps declaration

def _unpack_artifacts(self, artifact_inputs, rootfs: Path) -> None:
    # the unpack loop, called by both ImageDef and OCILayerDef
```

`ImageDef.assemble_command` and future `OCILayerDef.assemble_command` both call `_unpack_artifacts` then diverge for format-specific output.

---

## `ContainerDef` hierarchy
```
AssemblyDef
├── ImageDef          # squashfs — done
└── ContainerDef
    ├── OCILayerDef   # single layer tarball + descriptor
    └── OCIImageDef   # manifest pointing at ordered layer deps
OCIImageDef is the composed image case — its deps are other OCILayerDef outputs, it doesn't unpack files, it assembles references. OCILayerDef uses _unpack_artifacts identically to ImageDef.

BuildPaths.for_component — fix the dropped name
The name parameter is accepted and silently ignored. Either use it (f"{workspace}/components/{name}") or remove it. Either way, make it intentional.

BuildDef — mutable ClassVar defaults
deps, c_flags, cxx_flags, link_flags, configure_args, build_env are all mutable lists/dicts as ClassVar defaults. Subclasses that don't override share the same object. Fix via __init_subclass__ or explicit per-subclass defaults.

manifest_fields — provenance not bits
Two fixes falling out of the provenance hash design:

source_pin should record the locked commit/sha256 from the lock file, not the fetch URL
"build_env": {"sysroot_isolation": True} is hardcoded and meaningless — remove or derive from actual config


_resolve / _resolve_env — shared context
Factor out _make_context(paths) so both methods build the substitution dict in one place.

base.py glob issues — deferred until InstallFile lands
The overlapping .so entries, the wrong var/lib/**/*.la paths, and the blanket lib64/** catch-all are all symptoms of the glob model being wrong. They get fixed as part of the InstallFile migration rather than patched in place.