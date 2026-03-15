"""
crucible/vault_client.py
Minimal Vault client for Forge image resolution.
Pulls blobs from Vault by digest, caches locally.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import httpx

VAULT_PREFIX = "vault:blake3:"
CHUNK        = 1024 * 1024  # 1MB


def is_vault_ref(value: str) -> bool:
    return value.startswith(VAULT_PREFIX)


def parse_digest(value: str) -> str:
    """Extract digest from 'vault:blake3:<hex>' reference."""
    return value.removeprefix(VAULT_PREFIX)


def resolve_image(vault_url: str, vault_ref: str, cache_dir: Path) -> Path:
    """
    Resolve a vault:blake3: reference to a local path.
    Downloads and caches the blob if not already present.
    Returns path to the local cached file.
    """
    digest    = parse_digest(vault_ref)
    cached    = cache_dir / "vault-blobs" / digest
    if cached.exists():
        return cached

    cached.parent.mkdir(parents=True, exist_ok=True)

    url = f"{vault_url}/blob/{digest}"
    tmp = cached.with_suffix(".tmp")

    try:
        with httpx.stream("GET", url, timeout=60) as r:
            if r.status_code == 404:
                raise FileNotFoundError(f"Vault blob not found: {digest}")
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(CHUNK):
                    f.write(chunk)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    tmp.rename(cached)
    cached.chmod(0o444)  # local WORM — don't accidentally overwrite cached blobs
    return cached