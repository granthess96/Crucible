# Cast

Image generation and projection tool. Consumes component artifacts from Kiln's build cache, applies role-based filtering via FileSpec, and generates final images (squashfs, OCI, tar) for deployment and testing.

Cast is not a developer tool; it's an automated system component. But it must be debuggable — both for troubleshooting the tool itself and for understanding image composition workflows.

---

## Purpose

Cast bridges two worlds:
- **Input:** Component artifacts from Kiln (compiled source, cached, with FileSpec role annotations)
- **Output:** Deployable images for Forge (bootstrap), production (containers), and testing

Cast **does not:**
- Build components (Kiln's job)
- Cache artifacts (Coffer's job)
- Store permanently (Vault's job)
- Run tests (Ledger's job)
- Report results (Aegis's job)

---

## MVP Scope: Forge Bootstrap Images

The first Cast use case is generating Forge's base and tools squashfs images for hermetic builds.

**Input:** `bootstrap.toml` + Kiln cache
```toml
[image.base]
components = ["bash", "coreutils", "glibc", ...]
[image.tools]
components = ["gcc", "binutils", "gmp", ...]
```

**Output:** `base.sqsh` and `tools.sqsh` (squashfs images)

**Workflow:**
1. Read bootstrap.toml (component lists and role filters)
2. Call `kiln resolve <components>` for each image layer
3. Fetch component artifacts from cache (tarballs + role indexes)
4. Filter files by role (runtime, dev, tool, config, doc, debug)
5. Assemble squashfs images
6. Optionally push to Vault for permanence

---

## CLI Interface

```bash
cast [OPTIONS] [LAYER ...]
```

### Arguments

**LAYER** — Image layers to generate (optional, default: base tools)
- `base` — Arch-independent OS foundation
- `tools` — Arch-specific compiler toolchain

```bash
cast                    # Build both base and tools
cast base               # Build only base
cast tools              # Build only tools
cast base tools         # Explicit (same as default)
```

### Configuration Options

**`--spec PATH`** — Configuration file (default: auto-discover bootstrap.toml)
- Walks up from cwd looking for bootstrap.toml (like Kiln with forge.toml)
- Alternative flag: `--source PATH` (both acceptable)
- Fails with clear error if not found

```bash
cast --spec ./bootstrap.toml
cast --source my-custom-bootstrap.toml
```

### Output Options

**`--output-dir PATH`** — Directory for generated images (default: `./images`)
- Creates directory if needed
- Outputs: `base.sqsh`, `tools.sqsh`, `base.sqsh.manifest`, `tools.sqsh.manifest`

```bash
cast --output-dir /tmp/images
cast --output-dir $CI_ARTIFACTS_DIR
```

**`--vault URL`** — Vault server URL (default: from forge.toml [vault].url)
- Required if `--push` is used
- Can be overridden via env var `VAULT_URL`

```bash
cast --vault http://vault.example.com:7777 --push
```

**`--push`** — Push generated images to Vault
- Optional; without this, images stay local
- Stores as Vault blobs, creates name tags `base-latest` and `tools-latest`

```bash
cast --push                          # Uses default Vault from forge.toml
cast --push --vault $VAULT_URL       # Override Vault URL
```

### Debug Options

**`-v, --verbose`** — Verbose output
- Shows each phase: resolving, fetching, filtering, assembling
- Lists components being processed and file counts extracted
- Progress indicators for large operations
- Useful for validating workflows and troubleshooting

```bash
cast --verbose
# Output:
# Resolving base components... 27 components, 120 total files
# Fetching readline (8.2) sha256:abc123... [===========] 2.3MB
# Filtering by role (include: runtime,dev,tool,config,doc)...
# Assembling base.sqsh...
# Created: ./images/base.sqsh (145MB, blake3:xyz789)
```

**`--debug`** — Include debug symbols in images
- Overrides bootstrap.toml role filters
- Adds `debug` role to inclusion list for both layers
- Useful for troubleshooting production issues (slightly larger images)

```bash
cast --debug                # Build with full debug symbols
cast tools --debug --keep-staging  # Inspect toolchain debug symbols
```

**`--dry-run`** — Show what would be done without actually building
- Performs component resolution and role filtering
- Shows which files would be included/excluded
- Exits without generating squashfs or pushing to Vault
- Fast feedback for validating configuration

```bash
cast --dry-run --verbose     # See complete file list and decisions
```

**`--keep-staging`** — Preserve staging directories after build
- Staging dirs: `./images/staging-base/`, `./images/staging-tools/`
- Allows manual inspection of extracted files
- Useful for verifying role filtering is correct
- Directories are deleted after successful builds by default

```bash
cast base --keep-staging
ls ./images/staging-base/usr/bin/   # Inspect extracted binaries
```

**`-q, --quiet`** — Suppress non-error output
- Only print results (image paths, Vault IDs)
- Useful for CI scripts that capture stdout
- Errors still print to stderr

```bash
cast --quiet | while read img; do echo "Generated: $img"; done
```

### Help

**`-h, --help`** — Show help text

```bash
cast --help
```

---

## Configuration: bootstrap.toml

Cast reads `bootstrap.toml` to determine which components belong in each image and how to filter files.

**Location:** Project root (same directory as forge.toml)

**Structure:**
```toml
[image.base]
description = "Base OS image"
components = [
    "bash", "coreutils", "glibc", "make", "cmake",
    # ... 23 more components
]

[image.tools]
description = "Architecture-specific compiler toolchain"
components = [
    "gcc", "binutils", "gmp", "mpfr", "mpc", "libxcrypt",
    "glibc", "linux-headers"
]

[roles]
[roles.base]
include = ["runtime", "dev", "tool", "config", "doc"]
exclude = ["debug"]
rationale = "Base image: all except debug symbols"

[roles.tools]
include = ["runtime", "dev", "tool", "debug"]
exclude = ["config", "doc"]
rationale = "Tools image: includes debug for troubleshooting"
```

For detailed rationale on component split, see [bootstrap.toml documentation](./bootstrap.toml).

---

## Workflow

### Phase 1: Configuration Loading

```
Read bootstrap.toml
├─ Validate structure
├─ Load component lists (base, tools)
├─ Load role filters
└─ Store in memory
```

### Phase 2: Component Resolution

For each image layer (base, then tools):

```
kiln resolve <components> --from-stdin
    (or on command line: kiln resolve bash coreutils glibc ...)
│
├─ Receive JSON: topo-sorted artifacts with manifest hashes
├─ Parse and validate (expect schema_version: 1)
└─ Store artifact order for Phase 3
```

Output (example for base):
```json
{
  "schema_version": 1,
  "artifacts": [
    {"component": "readline", "version": "8.2", "hash": "sha256:...", "requested": false},
    {"component": "glibc", "version": "2.38", "hash": "sha256:...", "requested": true},
    ...
  ]
}
```

### Phase 3: Fetch and Filter

For each artifact in topo order:

```
For component in artifacts:
  ├─ Fetch <hash>.files.json.zst from cache
  │  └─ Decompress zstd → JSON
  │     Contains: {"path": "role", ...}
  │
  ├─ Fetch <hash>.tar.zst from cache
  │  └─ Decompress zstd → tarball
  │
  ├─ Filter files by role
  │  └─ If role in bootstrap.toml[roles.base].include:
  │     Extract to staging/base/path
  │
  └─ Log: component, file count, sizes
```

**Example for glibc:**
```
Fetching glibc (2.38) sha256:abc123d...
  lib/libc.so.6 → runtime (included)
  usr/include/stdio.h → dev (included)
  var/db/Makefile → exclude (skipped)
  Result: 87 files extracted, 12.3 MB
```

### Phase 4: Assemble Images

For each layer:

```
Staging dir → squashfs image
└─ mksquashfs staging/base/ base.sqsh
   ├─ Compute blake3 hash
   ├─ Generate manifest file (metadata about contents)
   └─ Output: base.sqsh, base.sqsh.manifest
```

### Phase 5: Vault Push (optional)

If `--push` flag:

```
For each image:
  ├─ Create Vault blob
  │  └─ PUT /blob/<hash> with image data
  │
  ├─ Create name tag
  │  └─ PUT /name/base-latest with digest + protected flag
  │
  └─ Output: Vault name tag and digest
```

---

## Output

After successful run:

```
./images/
├── base.sqsh                    # Squashfs image for base OS
├── base.sqsh.manifest           # Metadata about base
├── tools.sqsh                   # Squashfs image for toolchain
├── tools.sqsh.manifest          # Metadata about tools
└── staging-base/                # (only if --keep-staging)
    └── staging-tools/
```

**With --verbose:**
```
Resolving base components (27 total, 2 with no requested flag)... OK
Fetching components: bash coreutils glibc ... [==========] 100%
Filtering files by role (runtime, dev, tool, config, doc):
  bash: 43 files, 2.1 MB
  coreutils: 121 files, 5.8 MB
  glibc: 87 files, 12.3 MB
  ...
Total: 1247 files, 145.2 MB
Creating squashfs... [==========] 100%
Output: ./images/base.sqsh (87 MB compressed)
Manifest: ./images/base.sqsh.manifest

[Repeat for tools...]
```

**With --push:**
```
Pushing base.sqsh to Vault (87 MB)... [==========] 100%
  Digest: sha256:xyz789...
  Tag: base-latest
  Status: OK

Pushing tools.sqsh to Vault (34 MB)... [==========] 100%
  Digest: sha256:def456...
  Tag: tools-latest
  Status: OK
```

---

## Design Principles

### 1. **Declarative Configuration**
- `bootstrap.toml` is the source of truth
- No magic; what you see is what you get
- Version control-friendly

### 2. **Non-invasive**
- Cast is a separate tool, not integrated into Kiln
- No build-side changes needed
- Pure data flow: cache → Cast → images

### 3. **Debuggable**
- `--verbose` shows every decision
- `--dry-run` validates without building
- `--keep-staging` enables inspection
- Clear, structured logging

### 4. **Efficient**
- Topo order from `kiln resolve` enables single-pass unpacking
- Role filtering happens during extraction (no post-processing)
- Streaming where possible (large tarballs)

### 5. **Extensible**
- `--format` ready for OCI containers (future)
- Role definitions are table-driven (easy to add filters)
- Vault integration can be swapped for other backends

---

## Future Directions

### OCI Container Support
```bash
cast --format oci base tools       # Generate OCI images instead of squashfs
# Outputs: base-oci/, tools-oci/ (OCI layout)
```

### Multiple Image Targets
```bash
cast --spec custom-images.toml     # Not just base/tools
# Could define: dev-image, prod-image, test-image, etc.
```

### Role Customization
```bash
cast base --roles runtime          # Override roles from CLI
cast tools --exclude debug         # Exclude debug symbols at runtime
```

### Performance Optimization
```bash
cast --parallel 4                  # Parallel component extraction
cast --cache-dir ~/.cast-cache     # Pre-fetch cache locally
```

---

## Integration Points

### Kiln Integration
- Calls `kiln resolve <components>` to get artifact manifest
- Reads from Kiln's cache (`~/.kiln/cache/`)
- No build orchestration; Cast assumes artifacts are pre-built

### Vault Integration
- Reads Vault URL from forge.toml [vault].url
- Writes images as Vault blobs (optional `--push`)
- Tags with name entries for stable references

### Forge Integration
- Generates images for `forge --base base.sqsh --tools tools.sqsh`
- Or: `forge.toml` can reference Vault names: `vault:blake3:<hash>`

---

## Error Handling

Cast fails fast with clear error messages:

**Missing bootstrap.toml:**
```
ERROR: bootstrap.toml not found
  Searched in: ./, ../,  ../../, (stop at git root)
  Use --spec PATH to specify location
  Exit code: 1
```

**Unknown component:**
```
ERROR: Component 'unknown-pkg' not found
  Involved: base layer
  Use 'kiln components' to list available components
  Exit code: 1
```

**Cache miss:**
```
ERROR: Artifact not in cache: bash sha256:abc123...
  Suggestion: Run 'kiln deps --target bash' first
  Exit code: 1
```

**Vault unreachable:**
```
ERROR: Cannot reach Vault at http://vault:7777
  Connection timeout after 10s
  Use --vault URL to specify a different Vault instance
  Exit code: 1
```

---

## Security Considerations

### Current (MVP)
- No authentication for Vault (local development)
- No TLS validation (localhost only)
- Images are not signed

### Future
- TLS client certificates for Vault
- Image signing with OIDC attestation
- Role-based access control for `--push`

---

## Testing Cast

### Unit Tests
- bootstrap.toml parsing
- Role filter logic
- Artifact order validation

### Integration Tests
- Full workflow: resolve → fetch → filter → assemble
- Dry-run correctness
- Vault push/pull

### Manual Debugging

```bash
# 1. Validate configuration
cast --dry-run --verbose

# 2. Build base with staging inspection
cast base --keep-staging --verbose
ls -la ./images/staging-base/usr/bin/

# 3. Build and push to local Vault
cast --push --vault http://localhost:7777 --verbose

# 4. Quiet run for CI
cast --quiet --push
```

---

## See Also

- [bootstrap.toml](./bootstrap.toml) — Component lists and role definitions
- [README.md](./README.md) — Architecture overview
- `kiln resolve` — Component resolution and manifest generation
- `kiln package` — Build cache with FileSpec role annotations
