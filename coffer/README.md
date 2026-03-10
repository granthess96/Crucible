# cachectl

Server-side artifact cache controller for the kiln build system.

## Installation

```
/home/cache/
  bin/cachectl          # this script (chmod +x, python3 shebang)
  config/cachectl.toml  # configuration
  cache/                # artifact storage (sharded by hash prefix)
  staging/              # temporary upload buckets
  logs/cachectl.log     # operation log
```

Make executable:
```bash
chmod +x /home/cache/bin/cachectl
```

Requires Python 3.11+ (uses `tomllib` from stdlib).

## Configuration

```toml
[storage]
cache_root       = "/home/cache/cache"
staging_root     = "/home/cache/staging"
high_water_bytes = 50_000_000_000   # 50 GiB
low_water_bytes  = 40_000_000_000   # 40 GiB

[staging]
ttl_hours = 4

[server]
log_path = "/home/cache/logs/cachectl.log"
```

## Commands

### `cachectl get-bucket`
Allocates a new empty staging directory and prints its path.
The caller uploads artifacts into this directory before calling `publish`.
Staging buckets not published within `ttl_hours` are automatically reaped.

```bash
BUCKET=$(ssh cache@remote 'cachectl get-bucket')
scp ncurses.manifest.txt ncurses.runtime.tar.zst ncurses.buildtime.tar.zst \
    cache@remote:"$BUCKET/"
ssh cache@remote "cachectl publish $BUCKET $MANIFEST_HASH"
```

### `cachectl publish <bucket_path> <manifest_hash>`
Validates the staging bucket and atomically moves it into the cache.

Validation checks:
- Manifest file exists in bucket
- `manifest_hash` field in manifest matches the provided hash
- All artifact files listed in manifest `outputs` are present
- SHA256 of each artifact matches manifest (if recorded)

Triggers GC after publish.

### `cachectl fetch <manifest_hash>`
Returns the cache directory path if the hash is present (exit 0).
Exits with code 2 on cache miss.
Updates LRU timestamp on hit.
Triggers GC.

```bash
if CACHE_PATH=$(ssh cache@remote "cachectl fetch $HASH"); then
    scp "cache@remote:$CACHE_PATH/*" ./artifacts/
fi
# exit 2 = miss, handle rebuild
```

### `cachectl test <manifest_hash>`
Same as `fetch` but semantically a probe — use when the local cache already
has the artifacts and only needs to update the remote LRU hint.
Exit 0 = hit, exit 2 = miss.

```bash
ssh cache@remote "cachectl test $HASH" || echo "not cached"
```

### `cachectl gc`
Runs garbage collection explicitly. Suitable for cron.
GC also runs automatically on every other operation.

```bash
# crontab example — run GC at 3am daily
0 3 * * * /home/cache/bin/cachectl gc
```

### `cachectl status`
Prints a human-readable cache summary.

```
cache_root:      /home/cache/cache
cache_size:      23.4 GiB (25165824000 bytes)
cache_entries:   142
high_water:      50.0 GiB
low_water:       40.0 GiB
staging_root:    /home/cache/staging
staging_size:    1.2 GiB
staging_pending: 3
staging_ttl:     4h
```

## Exit Codes

| Code | Meaning              |
|------|----------------------|
| 0    | Success / cache hit  |
| 1    | Error                |
| 2    | Cache miss           |

## GC Behavior

GC uses LRU eviction based on file `mtime`, which is updated on every
`test`, `fetch`, and `publish` operation.

When cache size exceeds `high_water_bytes`, entries are evicted oldest-first
until size drops below `low_water_bytes` (hysteresis).

Stale staging buckets (older than `ttl_hours`) are also reaped on every GC run.

## Cache Layout

Mirrors the local kiln cache layout:

```
/home/cache/cache/
  <hash_prefix>/        # first 2 hex chars of manifest hash
    <hash_body>/        # remaining hex chars
      <stem>.manifest.txt
      <stem>.runtime.tar.zst
      <stem>.buildtime.tar.zst
```
