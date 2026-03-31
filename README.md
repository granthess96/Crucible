# Crucible

A hermetic, fully auditable build system for constructing a custom Linux software stack from source. Every input that could affect a build output is hashed into a manifest, and that manifest hash is the cache address. A single byte change anywhere in the dependency chain invalidates exactly the right set of downstream artifacts.

The system is designed around a small number of composable tools with clear responsibilities and no magic.

---

## What problem this solves

Building a reproducible, from-scratch Linux userspace (LFS-style) is a multi-day process with no reliable way to know what changed between builds, whether a cached artifact is still valid, or which components need rebuilding when a dependency is updated.

Crucible solves this by:
- Treating every component as a pure function of its inputs (source, build script, deps, toolchain, base image)
- Hashing those inputs into a manifest → cache key
- Never rebuilding what's already cached, never using a stale cache entry
- Providing a simple CLI that handles the entire lifecycle: fetch → checkout → configure → build → test → install → package

---

## Tools

### Forge
Hermetic build sandbox. Uses Linux user namespaces + squashfuse + overlayfs to create a chroot-like environment without requiring real root. Mounts `base.sqsh` (read-only rootfs) and `tools.sqsh` (compiler/toolchain) as the build environment, overlays the component's `__source__`, `__sysroot__`, `__build__`, and `__install__` directories, then runs the build command inside.

Forge is invoked as a subprocess by Kiln — it handles its own `unshare` context and exits cleanly, so Kiln stays in user context for host-side operations (fetch, checkout, package).

```
forge -- <command>               # run command in forge environment
forge --cwd <path> -- <command>  # with explicit working directory
```

### Kiln
Meta-build orchestrator. Reads `build.py` files from `components/<name>/`, resolves the dependency DAG, manages the artifact cache, and drives builds through a sequence of verbs.

```
kiln <verb> [verb ...] [--target <component>] [--push] [--verbose]
```

Verbs run in order, stop on first failure:

| Verb | What it does | Runs in |
|------|-------------|---------|
| `deps` | Resolve DAG, stat cache, build all missing deps in topo order | host |
| `fetch` | Download/clone source, lock sha256 or commit to `kiln.lock` | host |
| `checkout` | Extract source, apply patches, populate `__sysroot__` from dep cache | host |
| `configure` | Run cmake/autoconf/etc configure step | forge |
| `build` | Compile | forge |
| `test` | Run test suite (skip if none defined) | host |
| `install` | DESTDIR install into `__install__/` | forge |
| `package` | Split `__install__/` into runtime + buildtime tarballs, store in cache | host |
| `clean` | Wipe `__build__/` and `__install__/` | host |
| `purge` | Wipe everything including source and sysroot | host |
| `clear_cache` | Remove all local cache entries | host |

Target is inferred from cwd — running `kiln build` from anywhere inside `components/curl/__source__/lib/` resolves to `curl`.

### Coffer
Ephemeral SSH-based remote artifact cache. Acts as a shared team cache — after building locally, `--push` uploads to Coffer so teammates (or CI) can skip the build entirely.

```
kiln package --push              # build + cache locally + push to Coffer
kiln deps --push                 # build all missing deps + push each to Coffer
```

Server-side tool is `cachectl`. Configured via `coffer_host = "user@host"` in `forge.toml` or `~/.kiln/config.toml`. SSH key auth — no tokens.

### Vault *(planned)*
Long-term image/container registry for permanent artifact storage. Coffer is ephemeral (LRU eviction); Vault is designed as the permanent archive. Not yet implemented.

### Cast *(planned)*
Image generation and projection tool. Consumes packaged artifacts (with FileSpec role annotations) and generates target images (squashfs, tar, OCI, etc). Replaces the planned `assemble` verb from Kiln. Works downstream of Kiln — takes cached, packaged artifacts and uses FileSpec role classifications to selectively include/exclude components and files based on image requirements.

```
cast --base <base_image> --output <image.sqsh> [--format squashfs|tar|oci] <components...>
```

### Crucible *(planned)*
End-to-end coordination tool. Orchestrates the full build-to-image pipeline: runs Kiln to resolve and build components, manages artifacts, and invokes Cast to generate final images. Provides a single entry point for complete builds and handles parallelization of independent component builds.

```
crucible build --target <image_name> [--push] [--registry <host>]
```

---

## Component model

Each component lives in `components/<name>/build.py` and declares a single class:

```
KilnComponent (abstract base)
├── BuildDef          compiles source → artifact cache    (kiln package)
│   ├── AutotoolsBuild
│   ├── CMakeBuild
│   ├── MakeBuild
│   ├── MesonBuild
│   └── ScriptBuild
```

*Note: AssemblyDef (for image composition via `assemble` verb) and ContainerDef are planned but not yet implemented. Image assembly will be handled by separate tooling.*

A `BuildDef` must declare:
- `name`, `version` — identity
- `deps` — list of component names (DAG edges)
- `source` — `{'git': url, 'ref': tag}` or `{'url': tarball_url}`
- `build_weight` — scheduler hint (empirical, based on build time)

A `BuildDef` may override:
- `configure_args`, `c_flags`, `cxx_flags`, `link_flags` — passed to build system
- `configure_command()`, `build_command()`, `install_command()` — full override
- `configure_script()`, `build_script()`, `install_script()` — shell script override (runs via forge bash)
- `runtime_globs`, `buildtime_globs` — controls how `__install__/` is split into tarballs

---

## Artifact cache

### Cache Layout and Manifest Hashing

Every built artifact is addressed by the SHA256 of its canonical manifest. The manifest captures every input:

```
component: curl
version: 8.11.1
deps: [openssl, zlib]
dep:openssl: <manifest hash of openssl>
dep:zlib: <manifest hash of zlib>
source_sha256: <locked sha256 of downloaded tarball>
builder_hash: <sha256 of curl/build.py>
forge_base: <hash of base.sqsh>
toolchain: <hash of tools.sqsh>
```

A change to any input — including a dep's dep — produces a new hash and a cache miss.

Artifacts are stored as three files per component in a sharded layout:

```
<shard>/<hash_body>/
  <name>.runtime.tar.zst    # binaries, .so files
  <name>.buildtime.tar.zst  # headers, .a files, pkgconfig
  <name>.manifest.txt       # manifest fields (human readable)
```

Where `<shard>` is the first 2 characters of the manifest hash (for shallow sharding, similar to git object store).

### Two-Tier Cache: Local + Remote

**Tier 1: Local cache** (`~/.kiln/cache/` by default)  
- Full read/write for any user
- Sharded by first 2 chars of manifest hash
- Clearable at any time with no side effects (just longer build times)

**Tier 2: Coffer remote cache** (SSH-based, server-side tool: `cachectl`)  
- Read for all users (fetch-through to local)
- Write only via `--push` flag
- Configured in `forge.toml` or `~/.kiln/config.toml`
- SSH key auth — no tokens

### Cache Hit Resolution Order

1. **Local hit** → use directly + background LRU touch on remote
2. **Local miss + remote hit** → fetch to local + promote to cache + use
3. **Both miss** → build required

### Garbage Collection

Coffer enforces a disk quota. When quota is exceeded:
- GC is triggered on `--push`
- Eviction uses last-accessed timestamps from manifests (LRU)
- Lost artifacts are simply rebuilt — cache loss is acceptable

Local cache can be cleared with `kiln clear_cache`.

---

## Source locking

`kiln.lock` is committed to the repo. It maps component names to their locked source identity:

```
# kiln.lock -- auto-generated, commit this file
bash.sha256 abc123...
bash.url https://ftp.gnu.org/gnu/bash/bash-5.3.tar.gz
curl.sha256 def456...
curl.url https://curl.se/download/curl-8.11.1.tar.xz
pcre2.commit 7f8a9b...
```

- **Tarball**: sha256 established on first `kiln fetch`, verified on every subsequent fetch. URL mismatch triggers re-download and sha256 re-verification. sha256 mismatch is a hard error.
- **Git**: ref resolved to commit SHA on first fetch, locked. Subsequent fetches use the locked SHA — tags are not trusted as immutable.

---

## Directory layout per component

```
components/<name>/
  build.py              component definition
  patches/              *.patch files applied in lex order (optional)
  __source__/           extracted source tree (managed by kiln)
  __sysroot__/          unpacked buildtime artifacts from deps (managed by kiln)
  __build__/            out-of-tree build directory (managed by kiln)
  __install__/          DESTDIR install staging (managed by kiln)
```

`__source__`, `__sysroot__`, `__build__`, `__install__` are always wiped on `kiln checkout`. They are in `.gitignore`.

---

## Configuration

`forge.toml` at the build root — committed to repo, contains project-wide defaults.  
`~/.kiln/config.toml` — machine-local overrides (coffer_host, cache paths, etc.)

Key settings:
```toml
[forge]
base_image = "/path/to/base.sqsh"
tools_image = "/path/to/tools.sqsh"

[cache]
local_dir = "~/.kiln/cache"
coffer_host = "cache@buildserver"   # user@host, SSH key auth
coffer_port = 22

[scheduler]
max_weight = 8
```

---

## Typical workflow

### Build a single component
```bash
cd components/curl
kiln fetch checkout configure build install package
kiln fetch checkout configure build install package --push   # + push to Coffer
```

### Build all missing deps for a component, then build it
```bash
cd components/curl
kiln deps                                    # builds zlib, openssl if missing
kiln fetch checkout configure build install package --push
```

### Rebuild after changing a dep
```bash
# Edit components/openssl/build.py
cd components/curl
kiln deps    # detects openssl manifest changed, rebuilds openssl + curl
```

### Check what needs building without building it
*(planned: `kiln deps --dry-run`)*  
Currently `kiln deps` both reports and builds. The reporting-only behavior will become `--dry-run`.

---

## Current component list

| Component | Version | Type | Notes |
|-----------|---------|------|-------|
| linux-headers | 6.12 | AutotoolsBuild | |
| glibc | 2.42 | AutotoolsBuild | build_weight=6 |
| zlib | 1.3.2 | CMakeBuild | |
| ncurses | 6.5 | AutotoolsBuild | --without-cxx-binding |
| readline | 8.2 | AutotoolsBuild | |
| bash | 5.3 | AutotoolsBuild | |
| coreutils | 9.10 | AutotoolsBuild | FORCE_UNSAFE_CONFIGURE=1 |
| sed | 4.9 | AutotoolsBuild | |
| grep | 3.11 | AutotoolsBuild | |
| gawk | 5.3.2 | AutotoolsBuild | |
| findutils | 4.10.0 | AutotoolsBuild | |
| pcre2 | 10.44 | CMakeBuild | |
| tar | 1.35 | AutotoolsBuild | FORCE_UNSAFE_CONFIGURE=1 |
| xz | 5.6.3 | AutotoolsBuild | |
| gzip | 1.13 | AutotoolsBuild | |
| bzip2 | 1.0.8 | MakeBuild | non-standard install, PREFIX only |
| make | 4.4.1 | AutotoolsBuild | |
| openssl | 3.4.1 | AutotoolsBuild | custom Configure script |
| curl | 8.11.1 | CMakeBuild | |
| libpng | 1.6.44 | CMakeBuild | |

---

## For AI Assistants

For comprehensive guidance on the Crucible architecture, build conventions, and development workflows, see [.github/copilot-instructions.md](.github/copilot-instructions.md). This document covers the build system design, component model, cache/manifest system, and common editing tasks needed to work effectively in the repository.

---

## Known issues / TODOs

- `kiln deps --dry-run` — current `kiln deps` behavior (report only) should become `--dry-run`; bare `kiln deps` now builds
- `bzip2` MakeBuild — `MakeBuild` base class is minimal; bzip2 overrides `install_command` directly
- Namespace/execution refactor — `fetch`, `checkout`, `package` are correctly host-side; forge verbs spawn forge subprocess; the old unshare re-exec of kiln is removed
- Parallel scheduling — `build_weight` is tracked but scheduler runs sequentially; parallel `kiln deps` is a future feature
- Audit log timestamps — `Reporter` writes to audit dir but per-verb timing is not yet recorded
- `AssemblyDef` / `ImageDef` — image assembly (squashfs, OCI containers) not yet implemented
- `ContainerDef` — OCI/podman support stubbed but not implemented
- Vault — permanent image/container registry designed but not yet implemented