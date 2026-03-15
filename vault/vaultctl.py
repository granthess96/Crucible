#!/usr/bin/env python3
"""
vaultctl — Vault admin CLI
Finds forge.toml walking up from cwd, loads vault.toml from same root.
"""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import click
import httpx

# ---------------------------------------------------------------------------
# Project root / config discovery
# ---------------------------------------------------------------------------

def find_project_root() -> Path:
    current = Path.cwd().resolve()
    for directory in [current, *current.parents]:
        if (directory / "forge.toml").exists():
            return directory
    click.echo("Error: forge.toml not found.", err=True)
    click.echo("Are you inside a Crucible project?", err=True)
    click.echo(f"Searched from: {current}", err=True)
    sys.exit(1)

def load_vault_url() -> str:
    root = find_project_root()
    vault_toml = root / "vault" / "vault.toml"
    if not vault_toml.exists():
        click.echo(f"Error: vault.toml not found at {vault_toml}", err=True)
        sys.exit(1)
    with vault_toml.open("rb") as f:
        data = tomllib.load(f)
    server = data.get("server", {})
    host = server.get("host", "127.0.0.1")
    port = server.get("port", 7777)
    return f"http://{host}:{port}"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(url: str, path: str) -> httpx.Response:
    try:
        return httpx.get(f"{url}{path}", timeout=10)
    except httpx.ConnectError:
        click.echo(f"Error: cannot connect to Vault at {url}", err=True)
        sys.exit(1)

def put(url: str, path: str, body: dict) -> httpx.Response:
    try:
        return httpx.put(f"{url}{path}", json=body, timeout=10)
    except httpx.ConnectError:
        click.echo(f"Error: cannot connect to Vault at {url}", err=True)
        sys.exit(1)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Vault admin tool for the Crucible project."""
    pass

# ── Health ───────────────────────────────────────────────────────────────────

@click.command()
def health():
    """Check Vault and Garage are reachable."""
    url = load_vault_url()
    r = get(url, "/health")
    data = r.json()
    status  = data.get("status", "unknown")
    garage  = data.get("garage", False)
    click.echo(f"Vault:  {status}")
    click.echo(f"Garage: {'ok' if garage else 'unreachable'}")
    if status != "ok" or not garage:
        sys.exit(1)

# ── Blob commands ────────────────────────────────────────────────────────────

@click.group()
def blob():
    """Blob operations."""
    pass

@blob.command(name="list")
def blob_list():
    """List all blobs in Vault."""
    url = load_vault_url()
    r = get(url, "/blob")
    if r.status_code != 200:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)
    blobs = r.json()
    if not blobs:
        click.echo("No blobs stored.")
        return
    click.echo(f"{'DIGEST':<66}  {'SIZE':>12}")
    click.echo(f"{'-'*66}  {'-'*12}")
    for b in blobs:
        size = b.get("size", 0)
        size_str = _fmt_size(size)
        click.echo(f"{b['digest']}  {size_str:>12}")

@blob.command(name="verify")
@click.argument("digest")
def blob_verify(digest):
    """Verify a blob is present and reachable."""
    url = load_vault_url()
    r = httpx.head(f"{url}/blob/{digest}", timeout=10)
    if r.status_code == 200:
        click.echo(f"OK  {digest}")
    elif r.status_code == 404:
        click.echo(f"MISSING  {digest}", err=True)
        sys.exit(1)
    else:
        click.echo(f"Error: HTTP {r.status_code}", err=True)
        sys.exit(1)

# ── Name commands ────────────────────────────────────────────────────────────

@click.group()
def name():
    """Name tag operations."""
    pass

@name.command(name="list")
def name_list():
    """List all name tags."""
    url = load_vault_url()
    r = get(url, "/name")
    if r.status_code != 200:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)
    tags = r.json()
    if not tags:
        click.echo("No tags.")
        return
    click.echo(f"{'NAME':<40}  {'DIGEST':<20}  {'PROT':>5}")
    click.echo(f"{'-'*40}  {'-'*20}  {'-'*5}")
    for t in tags:
        short  = t['digest'][:16] + "..."
        prot   = "yes" if t.get("protected") else "no"
        click.echo(f"{t['name']:<40}  {short:<20}  {prot:>5}")

@name.command(name="get")
@click.argument("name_arg", metavar="NAME")
def name_get(name_arg):
    """Show a name tag record."""
    url = load_vault_url()
    r = get(url, f"/name/{name_arg}")
    if r.status_code == 404:
        click.echo(f"Not found: {name_arg}", err=True)
        sys.exit(1)
    data = r.json()
    click.echo(f"Name:      {name_arg}")
    click.echo(f"Digest:    {data['digest']}")
    click.echo(f"Protected: {data.get('protected', False)}")
    if note := data.get("note"):
        click.echo(f"Note:      {note}")

@name.command(name="tag")
@click.argument("name_arg", metavar="NAME")
@click.argument("digest")
@click.option("--protected", is_flag=True, help="Mark tag as protected.")
@click.option("--note", default="", help="Optional note.")
def name_tag(name_arg, digest, protected, note):
    """Create or update a name tag."""
    url = load_vault_url()
    r = put(url, f"/name/{name_arg}", {
        "digest":    digest,
        "protected": protected,
        "note":      note,
    })
    if r.status_code == 403:
        click.echo(f"Error: tag '{name_arg}' is protected.", err=True)
        click.echo("Use 'vaultctl name retag' to force.", err=True)
        sys.exit(1)
    if r.status_code != 200:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)
    click.echo(f"Tagged: {name_arg} → {digest}")

@name.command(name="protect")
@click.argument("name_arg", metavar="NAME")
def name_protect(name_arg):
    """Set the protected flag on an existing tag."""
    url = load_vault_url()
    # Fetch current record first
    r = get(url, f"/name/{name_arg}")
    if r.status_code == 404:
        click.echo(f"Not found: {name_arg}", err=True)
        sys.exit(1)
    data = r.json()
    if data.get("protected"):
        click.echo(f"Already protected: {name_arg}")
        return
    r2 = put(url, f"/name/{name_arg}", {
        "digest":    data["digest"],
        "protected": True,
        "note":      data.get("note", ""),
    })
    if r2.status_code != 200:
        click.echo(f"Error: {r2.status_code} {r2.text}", err=True)
        sys.exit(1)
    click.echo(f"Protected: {name_arg}")

@name.command(name="retag")
@click.argument("name_arg", metavar="NAME")
@click.argument("digest")
@click.option("--note", default="", help="Optional note.")
def name_retag(name_arg, digest, note):
    """Force retag a protected name. Admin override — use with care."""
    url = load_vault_url()
    # Must unprotect first, then retag
    click.echo(f"Warning: retagging protected name '{name_arg}'.")
    click.confirm("Continue?", abort=True)
    r = put(url, f"/name/{name_arg}", {
        "digest":    digest,
        "protected": True,   # stays protected after retag
        "note":      note,
        "force":     True,
    })
    if r.status_code != 200:
        click.echo(f"Error: {r.status_code} {r.text}", err=True)
        sys.exit(1)
    click.echo(f"Retagged: {name_arg} → {digest}")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

# ---------------------------------------------------------------------------
# Register subgroups and entry point
# ---------------------------------------------------------------------------

cli.add_command(health)
cli.add_command(blob)
cli.add_command(name)

if __name__ == "__main__":
    cli()
