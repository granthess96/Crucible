**DEPRECATED** — This file is deprecated. Its content has been consolidated into README.md.

The cache architecture, operations, and garbage collection details are now in the main README's "Artifact cache" section, and the Coffer documentation is in the "Tools" section under "Coffer".

---

# Remote Artifact Cache - Crucible Coffer


This is a minimal, content-addressed, manifest-rooted build artifact cache designed for accelerating builds. It is ephemeral, immutable, and file-system-based, requiring only SSH access to a remote server.

It is not a permanent storage solution — lost artifacts can always be rebuilt.

1. Artifact Layout

Artifacts live in a flat or shallow-sharded filesystem layout on the remote cache:

/cache/  
  <hash_prefix>/
    <hash_body>/
      <stem>.manifest.txt
      <stem>.runtime.tar.xz
      <stem>.buildtime.tar.xz

Filename conventions:

<stem>: human-readable package name (e.g., ncurses)

<hash_prefix>: first 2 digits of deterministic build identity hash (see below)

<hash_body>: remaining digits without 2 digit prefix

<type>: runtime or buildtime

<extension>: file format (any archive type, not enforced)

1. Deterministic Build Identity

Each build is identified by a manifest hash, calculated from:

Source tree hash

Build toolchain hash

Chroot image manifest

Build command (optional, recommended)

The manifest file itself is canonicalized and hashed. This hash is used as the cache key.

Artifacts themselves are immutable and referenced in the manifest:

{
  "name": "ncurses",
  "source_tree": "...",
  "build_tools": "...",
  "chroot_manifest": "...",
  "command": "./configure && make",
  "outputs": {
    "runtime": {
      "file": "ncurses-<hash>-runtime.tar.xz",
      "sha256": "...",
      "size": 123456
    },
    "buildtime": {
      "file": "ncurses-<hash>-buildtime.tar.xz",
      "sha256": "...",
      "size": 456789
    }
  }
}
3. Cache Operations
Local Build

Check local cache first

If a miss, fetch artifacts from remote cache (read-through)

After fetch, update last-accessed timestamp on the manifest to give GC LRU hints

Example commands (via SSH + SCP):

# Check if artifact exists
ssh cache@remote 'stat ncurses-<hash>-manifest.json'

# Fetch artifacts
scp cache@remote:ncurses-<hash>-runtime.tar.xz .
scp cache@remote:ncurses-<hash>-buildtime.tar.xz .

# Update last-accessed hint
ssh cache@remote 'touch ncurses-<hash>-manifest.json'
CI / Publisher

Only the CI tool should publish artifacts to the remote cache:

Stage artifacts in a temporary staging directory on the server:

/staging/<hash>/
  runtime.tar.xz
  buildtime.tar.xz
  manifest.json

Once all files are uploaded, atomically move them into the cache:

ssh cache@remote 'cachectl publish <hash>'

The server-side publish operation verifies:

Manifest hash matches expected <hash>

All artifacts listed in the manifest exist

Artifact hashes match manifest entries

4. Garbage Collection (GC)

The cache enforces a disk quota

GC is triggered on push if the quota is exceeded

Eviction uses last-accessed timestamps from manifests to implement LRU eviction

Optionally, old staging directories are removed periodically or via cron

Since the cache is ephemeral, lost artifacts are simply rebuilt — GC does not affect correctness.

5. Architecture Summary
Builder Local Cache
   │
   ├─ hit → use local artifact
   │
   └─ miss → fetch from remote cache (read-through)
                 │
                 └─ touch manifest → LRU hint
CI / Publisher
   │
   └─ upload artifacts → staging → atomic publish
                 │
                 └─ server GC triggers if quota exceeded

Key properties:

Immutable artifacts

Manifest-rooted builds (manifest contains provenance + outputs)

Ephemeral storage (cache loss is acceptable)

Lightweight, SSH-only remote access

Optional LRU GC using last-accessed timestamps

6. Advantages

Simple, robust, and portable

No daemon or database required

Fully deterministic build identity

Safe for concurrent builds (rare collisions handled with atomic rename)

Human-readable filenames aid debugging

This design prioritizes speed, determinism, and operational simplicity over permanence or multi-team scalability.