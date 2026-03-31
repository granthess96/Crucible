# Crucible Copilot Instructions

## Project Overview

**Crucible** is a hermetic, fully auditable build system for constructing custom Linux software stacks from source. Every input that affects a build is hashed into a manifest, making the system reproducible and deterministic.

The platform consists of four main tools:

- **Kiln** — Meta-build orchestrator: reads `build.py` files, resolves dependency DAG, manages artifact cache, runs build verbs
- **Forge** — Hermetic build sandbox: uses Linux user namespaces + squashfuse + overlayfs to isolate builds from host environment
- **Coffer** — Ephemeral SSH-based remote artifact cache for team collaboration
- **Vault** (planned) — Long-term image/container registry for permanent artifact storage

## Build and Test Commands

### Running Builds

```bash
# Build a single component (from component directory or anywhere inside it)
cd components/curl
kiln fetch checkout configure build install package

# Push artifacts to Coffer remote cache
kiln fetch checkout configure build install package --push

# Build all missing dependencies, then build the component
kiln deps fetch checkout configure build install package

# Build and assemble a final image
cd components/base-image
kiln deps assemble
```

### Available Build Verbs

Run in order; stop on first failure. All paths resolve relative to `forge.toml`:

| Verb | Purpose | Runs in |
|------|---------|---------|
| `deps` | Resolve DAG, stat cache, build all missing deps in topo order | host |
| `fetch` | Download/clone source, lock sha256 or commit to `kiln.lock` | host |
| `checkout` | Extract source, apply patches, populate `__sysroot__` from dep cache | host |
| `configure` | Run cmake/autoconf/etc configure step | forge |
| `build` | Compile | forge |
| `test` | Run test suite (skip if none defined) | host |
| `install` | DESTDIR install into `__install__/` | forge |
| `package` | Split `__install__/` into runtime + buildtime tarballs, store in cache | host |
| `assemble` | Merge dep runtime artifacts, call `assemble_command()` (e.g. mksquashfs) | host |
| `clean` | Wipe `__build__/` and `__install__/` | host |
| `purge` | Wipe everything including source and sysroot | host |
| `clear_cache` | Remove all local cache entries | host |

### Running Tests

Components define tests via `test_command()` or `test_script()` in `build.py`. The test verb runs during the build lifecycle:

```bash
# Build up to and including tests
kiln fetch checkout configure build test

# Run just the test step on an existing build
kiln test --verbose
```

### Interactive Forge Shell

```bash
# Drop into an interactive shell in the build environment
forge

# Run a single command in the build environment
forge -- <command>

# With explicit working directory
forge --cwd /path/inside/chroot -- <command>
```

## High-Level Architecture

### Component Model

Each component is defined in `components/<name>/build.py` and declares a single class inheriting from `BuildDef`:

```python
# Structure
KilnComponent (abstract base)
├── BuildDef (for compilation)
│   ├── AutotoolsBuild (./configure && make)
│   ├── CMakeBuild (cmake-based projects)
│   ├── MakeBuild (raw Makefiles, minimal support)
│   ├── MesonBuild (meson build system)
│   └── ScriptBuild (custom shell scripts)
└── AssemblyDef (for image composition)
    ├── ImageDef (squashfs images via mksquashfs)
    └── ContainerDef (OCI/podman — planned)
```

### Component Lifecycle

**Host-side operations:** Fetch source from upstream, lock versions to `kiln.lock`, manage artifact cache, assemble final images.

**Forge operations:** All compilation steps (configure, build, test, install) run inside the hermetic forge environment with pinned base image + toolchain.

### Dependency Resolution

Kiln builds a directed acyclic graph (DAG) from the `deps` list in each component. `kiln deps` recursively builds all missing dependencies in topological order based on manifest hashes — a single-byte change anywhere in the dependency chain invalidates exactly the right set of downstream artifacts.

### Artifact Cache and Manifests

Every artifact is addressed by the SHA256 hash of its canonical manifest:

```
component: curl
version: 8.11.1
deps: [openssl, zlib]
dep:openssl: <manifest hash>
dep:zlib: <manifest hash>
source_sha256: <locked sha256 of tarball>
builder_hash: <sha256 of curl/build.py>
forge_base: <hash of base.sqsh>
toolchain: <hash of tools.sqsh>
```

Cached artifacts are stored as:

```
<shard>/<hash>/<name>.runtime.tar.zst      # binaries, .so files
<shard>/<hash>/<name>.buildtime.tar.zst    # headers, .a files, pkgconfig
<shard>/<hash>/<name>.manifest.txt         # manifest fields (human readable)
```

Local cache default: `~/.kiln/cache/`  
Remote (Coffer): configured in `~/.kiln/config.toml`

### Directory Layout Per Component

```
components/<name>/
  build.py              # component definition (required)
  patches/              # *.patch files applied in lex order (optional)
  __source__/           # extracted source tree (managed by kiln, .gitignored)
  __sysroot__/          # unpacked buildtime artifacts from deps (.gitignored)
  __build__/            # out-of-tree build directory (.gitignored)
  __install__/          # DESTDIR install staging (.gitignored)
```

Intermediate directories are always wiped on `kiln checkout`.

## Key Conventions

### Writing a Component `build.py`

Define a single class inheriting from the appropriate builder:

```python
from kiln.builders import CMakeBuild

class CurlBuild(CMakeBuild):
    name         = 'curl'
    version      = '8.11.1'
    deps         = ['zlib', 'openssl', 'linux-headers', 'glibc']
    build_weight = 2  # scheduler hint: empirical build time
    source       = {
        'url': 'https://curl.se/download/curl-8.11.1.tar.xz',
    }
    
    configure_args = [
        '--with-ssl=/usr',
        '--disable-static',
    ]
    
    # Optional overrides:
    # c_flags = ['-O2']
    # cxx_flags = ['-O2']
    # link_flags = ['-Wl,-rpath,/usr/lib']
    # runtime_globs = [...]  # control runtime vs buildtime split
    # buildtime_globs = [...]
    
    # For custom build logic:
    # def configure_command(self, paths: BuildPaths) -> list[str]:
    # def build_command(self, paths: BuildPaths) -> list[str]:
    # def test_command(self, paths: BuildPaths) -> list[str]:
    # def install_command(self, paths: BuildPaths) -> list[str]:
```

### Source Locking (`kiln.lock`)

Committed to the repo. Maps component names to locked source identity:

```
bash.sha256 abc123...
bash.url https://ftp.gnu.org/gnu/bash/bash-5.3.tar.gz
curl.commit def456...
curl.url https://github.com/curl/curl.git
```

**Tarball sources:** sha256 is established on first `kiln fetch`, verified on every subsequent fetch.  
**Git sources:** ref (tag/branch) is resolved to commit SHA on first fetch and locked. Subsequent fetches use the locked commit — tags are not trusted as immutable.

### Target Inference

Kiln infers the target component from the current working directory. The target resolves to the nearest `components/<name>/` directory in any parent path:

```bash
cd components/curl
kiln build              # target: curl

cd components/curl/__source__/lib
kiln build              # target: still curl (resolved from cwd ancestry)

cd /tmp
kiln build --target curl  # explicit target required outside project
```

### Path Locations Inside Forge

All command methods receive a `BuildPaths` object with paths representing locations inside the forge chroot:

```python
class BuildPaths:
    source      # /workspace/components/<name>/__source__
    build       # /workspace/components/<name>/__build__
    sysroot     # /workspace/components/<name>/__sysroot__
    install     # /workspace/components/<name>/__install__
```

### Configuration Files

**`forge.toml`** (project root, committed) — project-wide defaults:

```toml
[forge]
base_image = "vault:blake3:..."    # or local path
toolchain  = "vault:blake3:..."

[cache]
local = "~/.kiln/cache"
coffer_host = "user@host"
coffer_port = 22

[scheduler]
max_weight = 8
```

**`~/.kiln/config.toml`** (machine-local, not committed) — per-machine overrides for coffer_host, cache paths, etc.

### Artifact File Splitting

The base class `runtime_globs` and `buildtime_globs` determine how `__install__/` is split into runtime and buildtime tarballs:

- **Runtime:** binaries, .so files (glob patterns: `**/*.so*`, `bin/**`, `sbin/**`, etc.)
- **Buildtime:** headers, .a static libraries, pkgconfig files (glob patterns: `**/*.h`, `**/*.a`, `lib/pkgconfig/**`, etc.)

Override in subclass to include/exclude specific paths for unusual projects:

```python
runtime_globs = AutotoolsBuild.runtime_globs + ["usr/libexec/**"]
buildtime_globs = AutotoolsBuild.buildtime_globs + ["usr/lib/**/*.o"]
```

### Build Flags

Standard flags passed to the build system:

```python
c_flags = ['-O2', '-march=x86-64']       # CFLAGS
cxx_flags = ['-O2']                      # CXXFLAGS
link_flags = ['-Wl,-rpath,/usr/lib']     # LDFLAGS
configure_args = ['--enable-feature']    # passed to ./configure or cmake
```

### Patches

Place `.patch` files in `components/<name>/patches/`. Applied in lexicographic order during `kiln checkout`:

```
components/mylib/patches/
  001-fix-compiler-warning.patch
  002-upstream-security-fix.patch
  003-darwin-compatibility.patch
```

### Build Weight Scheduler Hint

`build_weight` is an empirical hint for the scheduler (currently sequential, but planned for parallelism):

```python
build_weight = 2   # fast, ~2-5 minutes
build_weight = 6   # slow, 20+ minutes (e.g., glibc)
```

### Environment Variables in Build

Inside forge, the following are available:

- `SYSROOT` — points to `__sysroot__` (dependency artifacts)
- `DESTDIR` — points to `__install__` (install staging area)
- Standard `CC`, `CXX`, `CFLAGS`, `CXXFLAGS`, `LDFLAGS` (set from component class attributes)

Outside forge (host-side verbs), standard shell environment with SSH/network access.

## Project Structure

```
.
├── .github/                  # GitHub metadata (workflows — TBD, copilot-instructions.md)
├── README.md                 # main project documentation
├── README-summary.md         # high-level overview
├── TODO.md                   # active tasks and decisions
├── forge.toml                # project config (committed)
├── kiln.lock                 # locked source versions (committed)
├── bin/
│   ├── forge                 # CLI entry point (Python wrapper)
│   └── kiln                  # CLI entry point (Python wrapper)
├── forge/                    # hermetic sandbox implementation
│   ├── __main__.py           # entry point
│   ├── instance.py           # ForgeInstance: chroot/namespace setup
│   └── ...
├── kiln/                     # meta-build orchestrator
│   ├── __main__.py           # CLI and verb dispatch
│   ├── dag.py                # dependency graph resolution
│   ├── cache.py              # two-tier cache (local + Coffer)
│   ├── manifest.py           # manifest hashing
│   ├── fetcher.py            # source fetching and locking
│   ├── registry.py           # container registry (planned)
│   ├── verbs/                # per-verb implementations
│   │   ├── build.py
│   │   ├── packaging.py
│   │   ├── source.py
│   │   └── ...
│   └── builders/             # build system abstractions
│       ├── base.py           # BuildDef base class
│       ├── autotools.py      # AutotoolsBuild
│       ├── cmake.py          # CMakeBuild
│       ├── make.py           # MakeBuild
│       ├── meson.py          # MesonBuild
│       └── script.py         # ScriptBuild
├── coffer/                   # remote cache server (Python/Paramiko SSH)
├── vault/                    # image registry (TBD)
├── crucible/                 # shared config module
│   ├── config.py             # TOML parsing
│   └── vault_client.py       # vault client
├── components/               # 34 components total (curl, bash, glibc, etc.)
│   ├── <name>/
│   │   ├── build.py          # component definition
│   │   ├── patches/          # optional patches
│   │   └── __source__, __sysroot__, __build__, __install__/  (generated)
│   └── ...
├── obsoletes/                # deprecated components (kept for reference)
└── import-bootstrap.py       # utility scripts
    verify-bootstrap.py
```

## Common Editing Tasks

### Adding a New Component

1. Create `components/mylib/build.py` with a class inheriting from the appropriate builder.
2. Declare `name`, `version`, `source` (git or tarball URL), and `deps`.
3. Set `configure_args`, `c_flags`, etc. as needed.
4. Run `kiln fetch checkout configure build install package` from `components/mylib/`.
5. Once locked, commit `kiln.lock` to lock the source version.

### Modifying Build Flags or Arguments

Edit `configure_args`, `c_flags`, etc. in the component's `build.py`. Kiln automatically detects that `builder_hash` has changed (the manifest hash of the build.py file itself) and invalidates the cache, triggering a rebuild.

### Updating Component Source Version

Edit the `source` dict (URL or git ref) in `build.py`. Run `kiln fetch` to resolve the new version and update `kiln.lock`. The `source_sha256` or `.commit` will change, triggering a cascade of rebuilds for all dependents.

### Dealing with Build Cache Misses

If a build is not using cached artifacts when you expect it to, check:

1. Did `builder_hash` change? (edit to `build.py`)
2. Did `source_sha256` or `.commit` change? (run `kiln fetch` to update)
3. Did a dependency's manifest change? (rebuild that dependency with `kiln deps`)
4. Is `forge_base` or `toolchain` different? (check `forge.toml` and `~/.kiln/config.toml`)

Run `kiln deps --verbose` to see full manifest hashes. Local cache is `~/.kiln/cache/<shard>/<hash>/`.

### Adding Tests to a Component

In `build.py`, override `test_command()` or `test_script()`:

```python
def test_command(self, paths: BuildPaths) -> list[str]:
    return ['bash', '-c', 'cd {build} && make check'.format(build=paths.build)]

def test_script(self, paths: BuildPaths) -> str:
    return '''
        cd {build}
        make check
        ./test-suite
    '''.format(build=paths.build)
```

The test verb runs after `install`, so binaries and libraries are available in `{install}`.

### Patching Upstream Source

Place `.patch` files in `components/<name>/patches/`. Use standard `diff -u` format:

```bash
cd components/mylib/__source__
# Make your edits
cd /path/to/mylib/original
diff -u mylib.c.orig mylib.c > /path/to/Crucible/components/mylib/patches/001-fix.patch
```

Patches are applied in lexicographic order during `kiln checkout`.

## Important Notes

- **`PYTHONPATH` shadowing bug (deferred):** Kiln's `PYTHONPATH` includes the project root, so Python can find the component source trees. This can cause stdlib modules to be shadowed by component sources (e.g., `shlex` found in `components/python3/__source__/` instead of stdlib). See TODO.md for workaround.

- **Namespace execution refactor (in progress):** Currently, forge verbs re-exec the entire kiln process under `unshare`. This breaks chained invocations mixing forge and host-side verbs (e.g., `kiln build install package --push`). Workaround: split into separate commands.

- **Parallel scheduling (planned):** `build_weight` is tracked but scheduler currently runs sequentially. Parallel `kiln deps` is a future feature.

- **Vault implementation (planned):** Long-term image registry is designed but not yet implemented. Coffer is ephemeral (LRU eviction).

- **ContainerDef (planned):** OCI/podman support is stubbed but not implemented.

- **Test coverage:** Essentially zero and possibly bit-rotted. Not a blocker for development but a known gap.
