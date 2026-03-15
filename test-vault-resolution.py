#!/usr/bin/env python3
"""
test-vault-resolution.py
Proves the Vault resolution chain works end to end.
Run from the project root before attempting a real Forge build.
"""
import sys
import hashlib
from pathlib import Path

# ── Test 1: Vault is reachable ───────────────────────────────────────────────

print("Test 1: Vault health check...")
import httpx
try:
    r = httpx.get("http://127.0.0.1:7777/health", timeout=5)
    data = r.json()
    assert data["status"] == "ok",   f"Vault status not ok: {data}"
    assert data["garage"] == True,   f"Garage not reachable: {data}"
    print(f"  OK — {data}")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── Test 2: Config loads and parses vault refs correctly ─────────────────────

print("\nTest 2: Config loads correctly...")
try:
    from crucible.config import load_config
    from crucible.vault_client import is_vault_ref, parse_digest
    cfg = load_config()
    print(f"  build_root:  {cfg.build_root}")
    print(f"  vault url:   {cfg.vault.url}")
    print(f"  base_image:  {cfg.forge.base_image}")
    print(f"  toolchain:   {cfg.forge.toolchain}")
    assert is_vault_ref(cfg.forge.base_image),  "base_image is not a vault ref"
    assert is_vault_ref(cfg.forge.toolchain),   "toolchain is not a vault ref"
    base_digest  = parse_digest(cfg.forge.base_image)
    tools_digest = parse_digest(cfg.forge.toolchain)
    assert len(base_digest)  == 64, f"base digest wrong length: {base_digest}"
    assert len(tools_digest) == 64, f"tools digest wrong length: {tools_digest}"
    print(f"  base digest:  {base_digest}")
    print(f"  tools digest: {tools_digest}")
    print(f"  OK")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── Test 3: Name tags resolve correctly in Vault ─────────────────────────────

print("\nTest 3: Name tags resolve in Vault...")
try:
    r = httpx.get("http://127.0.0.1:7777/name/forge-base:bootstrap", timeout=5)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    tag = r.json()
    assert tag["digest"] == base_digest, \
        f"Tag digest mismatch:\n  expected {base_digest}\n  got      {tag['digest']}"
    assert tag["protected"] == True, "forge-base:bootstrap should be protected"
    print(f"  forge-base:bootstrap  → {tag['digest'][:16]}...  protected={tag['protected']}")

    r = httpx.get("http://127.0.0.1:7777/name/forge-tools:bootstrap", timeout=5)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    tag = r.json()
    assert tag["digest"] == tools_digest, \
        f"Tag digest mismatch:\n  expected {tools_digest}\n  got      {tag['digest']}"
    print(f"  forge-tools:bootstrap → {tag['digest'][:16]}...  protected={tag['protected']}")
    print(f"  OK")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── Test 4: Blobs are reachable by digest (HEAD only — don't download yet) ───

print("\nTest 4: Blobs reachable by digest (HEAD)...")
try:
    for label, digest in [("base", base_digest), ("tools", tools_digest)]:
        r = httpx.head(f"http://127.0.0.1:7777/blob/{digest}", timeout=5)
        assert r.status_code == 200, f"{label} blob HEAD returned HTTP {r.status_code}"
        print(f"  {label}: {digest[:16]}...  HTTP 200  OK")
    print(f"  OK")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── Test 5: Actually download base image, verify digest ──────────────────────

print("\nTest 5: Download base image, verify digest...")
print("  (this will take a moment — 587 MB)")
try:
    import blake3
    cache_dir = cfg.local_cache_dir / "vault-blobs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / base_digest
    tmp  = dest.with_suffix(".tmp")

    if dest.exists():
        print(f"  Already cached — verifying digest...")
        h = blake3.blake3()
        with dest.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        actual = h.hexdigest()
        assert actual == base_digest, f"Cache digest mismatch: {actual}"
        print(f"  Cache hit, digest verified OK")
    else:
        h = blake3.blake3()
        with httpx.stream("GET", f"http://127.0.0.1:7777/blob/{base_digest}", timeout=httpx.Timeout(5.0, read=600.0)) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    h.update(chunk)
                    f.write(chunk)
        actual = h.hexdigest()
        assert actual == base_digest, \
            f"Downloaded digest mismatch:\n  expected {base_digest}\n  got      {actual}"
        tmp.rename(dest)
        dest.chmod(0o444)
        print(f"  Downloaded and verified OK")
    print(f"  OK")
except Exception as e:
    if tmp.exists():
        tmp.unlink()
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── Test 6: resolve_image returns correct path and is idempotent ─────────────

print("\nTest 6: resolve_image() is idempotent...")
try:
    from crucible.vault_client import resolve_image
    path1 = resolve_image(cfg.vault.url, cfg.forge.base_image, cfg.local_cache_dir)
    path2 = resolve_image(cfg.vault.url, cfg.forge.base_image, cfg.local_cache_dir)
    assert path1 == path2,    f"Paths differ: {path1} vs {path2}"
    assert path1.exists(),    f"Resolved path does not exist: {path1}"
    assert path1.stat().st_size > 0, f"Resolved file is empty: {path1}"
    print(f"  Resolved to: {path1}")
    print(f"  Size: {path1.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  OK")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── Done ─────────────────────────────────────────────────────────────────────

print("\n══════════════════════════════════════")
print("All tests passed. Forge can pull from Vault.")
print("══════════════════════════════════════")
