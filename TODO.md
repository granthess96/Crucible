# Crucible TODO

A running list of design decisions, planned work, and deferred items.
Update this as work is completed or new items are identified.

---

## Kiln — Cache & Coffer Integration

### Done
- [x] Local disk cache (`LocalDiskCache`)
- [x] `TieredCache` with fetch-through from remote
- [x] `CofferBackend` — SSH/SCP backend for remote Coffer cache
- [x] Background LRU touch on local hit (fire-and-forget daemon thread)
- [x] `CofferUnavailable` distinct from `CacheMiss`
- [x] `--push` flag (replaces `--publish`) for `kiln package`
- [x] `coffer_host`, `coffer_port`, `coffer_cachectl`, `coffer_ssh_timeout` in `[cache]` config
- [x] `KILN_COFFER_HOST` env var override for CI
- [x] `KILN_PUBLISH_TOKEN` env var gates write access to Coffer

### TODO
- [X] Wire `--push` flag through `verb_package` in `kiln/__main__.py`
      Currently calls `cache.store_local()` unconditionally.
      When `--push` is set, call `cache.publish()` instead.

- [ ] Redefine `kiln deps` verb semantics:
      - `kiln deps --dry-run`  →  current behavior: resolve DAG, stat cache, report hits/misses, no building
      - `kiln deps`            →  build and locally cache all missing deps (excluding current target)
      - `kiln deps --push`     →  build missing deps + push to Coffer
      This makes `kiln deps` a genuinely useful standalone operation rather than
      just an informational check.

- [ ] `kiln deps --dry-run` output: consider a `--verbose` mode that shows
      full manifest hashes rather than truncated 16-char prefixes.

---

## Kiln — Fetcher

### TODO
- [ ] Tarball fetch support (in addition to existing git fetch)
      - Source spec: `{ 'url': '...', 'sha256': '...' }`
      - Hash verified at download time — becomes part of manifest hash
      - No network access at build time (tarball pre-fetched like git clone)
      - Rationale: release tarballs have generated autotools files baked in —
        no bootstrap step needed, no gnulib network pulls, exact bytes are known

- [ ] `kiln.lock` should record tarball sha256 alongside git SHAs
      for full source provenance.

---

## Kiln — Build System

### TODO
- [ ] Bootstrap step for AutotoolsBuild
      Some components (e.g. coreutils from git) require `./bootstrap` or
      `autoreconf` before `./configure`. This pulls gnulib and generated files.
      Preferred solution: use release tarballs instead of git refs for autotools
      components — tarballs include pre-generated configure scripts.
      If git source is required, add an optional `bootstrap_script()` method
      to `AutotoolsBuild` (before `configure_script`/`configure_command`).

- [ ] Autotools bootstrap prerequisites must be present in `tools.sqsh`:
      Autoconf, Automake, Bison, Gettext, Git, Gperf, Gzip, Help2man,
      M4, Make, Perl, Tar, Texinfo, Wget, XZ Utils, po4a (TBD)
      Note: rsync must NOT be used — anything touching the network inside
      Forge is forbidden. Find workarounds for bootstrap scripts that use it.

- [ ] Document `tools.sqsh` contents formally so it can be reproduced.
      Eventually `tools.sqsh` will be pulled from Vault — provenance matters.

- [ ] Coreutils: switch from git ref to release tarball source.
      Git bootstrap was a 6-hour dead end (gnulib version pinning spiral).
      Release tarball has configure pre-generated — use that instead.
      Remove existing patches if they were working around bootstrap issues.

---

## Forge

### TODO
- [ ] `forge --create` is obsolete and broken — remove or clearly mark as such.
      `base.sqsh` and `tools.sqsh` are now built manually and will eventually
      be pulled from Vault.

- [ ] `BASE_PACKAGES` list in `forge/__main__.py` is stale (was used by
      `--create`). Remove when `--create` is removed.

---

## Vault — Long-term Storage (Design TBD)

### TODO
- [ ] Design Vault API — image/container registry for long-term artifact storage
- [ ] `base.sqsh` and `tools.sqsh` should be versioned in Vault and pulled
      on demand by Forge (replacing manual image management)
- [ ] Vault vs Coffer distinction:
      - Coffer = ephemeral build artifact cache (loss is acceptable, rebuild is cheap)
      - Vault   = permanent storage (images, promoted artifacts, release builds)
- [ ] `--publish` flag reserved for Vault promotion (explicitly weightier than `--push`)
      `kiln package --push`    → push build artifact to Coffer (team cache)
      `kiln package --publish` → promote artifact to Vault (permanent record)

---

## Coffer — Cache Server

### TODO
- [ ] `cachectl` path on server is derived from username in `user@host`.
      Add `coffer_cachectl` override in `[cache]` config for non-standard setups.
      (Already in config dataclass — just needs documentation/testing.)

- [ ] Consider adding `cachectl list` command for cache inspection from client side.

- [ ] CI integration: document `KILN_PUBLISH_TOKEN` + `KILN_COFFER_HOST` env vars
      and expected SSH key setup for CI → Coffer auth.

---

## General / Project

### TODO
- [ ] `kiln init` command — scaffold a new project with `forge.toml` template
      (template already exists in `crucible/config.py` as `FORGE_TOML_TEMPLATE`)

- [ ] `README.md` is not informative — rewrite once design stabilizes

- [ ] Test coverage:
      `test_forge.py` and `test_kernel.py` exist — unclear what they cover.
      Add tests for `CofferBackend` (mock SSH), `TieredCache` fetch-through,
      and `CacheConfig` TOML parsing.

- [ ] Add visual distinction for local cache hit vs remote cache hit on 
      `kiln deps  --dry-run` 


## Kiln — Namespace / Execution Context Refactor

### Background
`main()` unconditionally re-execs the entire kiln process under
`unshare --user --mount --map-root-user` if not already root. This was
originally "simpler" but causes problems for host-side verbs that need
normal user context (SSH, SCP, network access).

Current workaround: only re-exec when a forge verb is present in the
verb list. This breaks chained invocations that mix forge verbs with
host-side verbs e.g. `kiln build install package --push` — the re-exec
from `build` puts `package --push` inside the namespace, breaking SSH.

### Workaround
Split forge and host-side verbs into separate invocations:
    kiln build install        # forge verbs — runs in namespace
    kiln package --push       # host-side — runs normally

### Future Refactor
Forge verbs (checkout, configure, build, test, install) need the
unshare namespace. Host-side verbs (fetch, package, deps, clear_cache)
do not. The right fix is to enter the namespace inline per-verb rather
than re-execing the whole process:
- Add a ForgeContext that enters/exits the user+mount namespace
  around only the verbs that need it
- Package, fetch, and cache operations always run as the real user
  with the real SSH/network environment
- Consider an internal --already-unshared flag as a stepping stone
  if full per-verb namespace management is too complex initially
- Consider if forge can be launched in a separate process with the unshare state,
  but leave kiln itself in pure user context