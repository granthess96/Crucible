# Coffer — Kiln Remote Artifact Cache

Coffer is the remote artifact cache backend used by the Kiln build system.

It provides a simple, filesystem-based content-addressed cache with:
- staging upload buckets
- manifest-validated publishing
- hash-based lookup
- LRU garbage collection

Coffer is designed for controlled internal infrastructure use and is not intended as a general-purpose or multi-tenant cache service.

---

## Architecture

Coffer operates on two directories:

### Staging
Temporary upload area for build outputs:


staging/<uuid>/


Created via `get-bucket`.

---

### Cache
Persistent artifact storage keyed by manifest hash:


cache/<hash-prefix>/<hash-body>/


Each entry contains the full set of build outputs from a staging bucket.

---

## Workflow

### 1. Allocate staging bucket

```bash
BUCKET=$(cachectl get-bucket)
2. Upload artifacts

Client uploads files + manifest into staging bucket.

3. Publish
cachectl publish $BUCKET $MANIFEST_HASH

Validates:

manifest exists
hash matches
all declared outputs exist
optional SHA256 checks

Then atomically stores artifacts in cache.

4. Fetch artifacts
CACHE_PATH=$(cachectl fetch $HASH)
returns cache directory path if present
exit code 2 if missing
updates LRU metadata on hit
5. Probe cache
cachectl test $HASH

Same as fetch but intended for existence checks.

Garbage Collection

Coffer automatically manages disk usage using a high/low watermark system:

GC triggers when cache exceeds high_water_bytes
eviction continues until below low_water_bytes
least-recently-used entries are removed first

Staging buckets older than TTL are also removed.

Configuration

cachectl.toml

[storage]
cache_root       = "/home/cache/cache"
staging_root     = "/home/cache/staging"
high_water_bytes = 50000000000
low_water_bytes  = 40000000000

[staging]
ttl_hours = 4

[server]
log_path = "/home/cache/logs/cachectl.log"
Exit Codes
Code	Meaning
0	success / cache hit
2	cache miss
1	error
Notes
Cache entries are stored as full directory copies of staging buckets.
LRU is approximated using file modification times.
GC runs automatically after most operations.

## 3. TODO.md (Actionable, grounded in code)

```markdown
# Coffer TODO

This reflects observed implementation gaps and operational improvements.

---

## Correctness / Reliability

- [ ] Add file locking around:
  - publish()
  - gc()
  - fetch/test access paths
  (prevents race conditions during concurrent SSH operations)

- [ ] Make manifest format explicit schema definition
  - currently implicit JSON structure

- [ ] Validate staging bucket contents more strictly:
  - ensure exactly one manifest file OR deterministic selection

---

## GC Improvements

- [ ] Replace repeated dir_size() calls with cached traversal
- [ ] Avoid full filesystem scan per GC invocation
- [ ] Consider storing per-bucket size metadata during publish

---

## LRU / Access Tracking

- [ ] Replace mtime-based LRU with explicit metadata file:
  - `.access_timestamp`
- [ ] Avoid touching every file in bucket for LRU updates

---

## Operational Improvements

- [ ] Add dry-run mode for gc
- [ ] Add GC metrics output (bytes freed, buckets removed)
- [ ] Add structured JSON output mode for status

---

## Observability

- [ ] Expand logging for:
  - publish success/failure reasons
  - GC decisions per bucket
- [ ] Add log rotation support (currently external responsibility)

---

## API Consistency

- [ ] Standardize fetch/test semantics:
  - currently duplicated logic
  - could share internal resolver function

---

## Safety (internal infra context)

- [ ] Add optional safeguard:
  - prevent GC if cache size rapidly changes during run

---

## Minor Cleanup

- [ ] Remove unused import: `fcntl`
- [ ] Normalize naming: bucket_dir vs body_dir vs prefix_dir