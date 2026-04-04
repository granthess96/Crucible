"""
crucible/config.py
Shared configuration for kiln and forge.
Both tools read from the same forge.toml at the project root.
Neither tool should import from the other — both import from here.
Two config sources, merged in order (later overrides earlier):
  1. forge.toml          — project config, committed to repo
  2. ~/.kiln/config.toml — machine-local overrides, never committed
  3. Environment vars    — CI overrides
Discovery:
  Walk up from cwd looking for forge.toml.
  That directory is the project root — all relative paths resolve from there.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from crucible.vault_client import is_vault_ref, resolve_image

# Environment variable names — set by forge/__main__.py before unshare
# so that vault resolution (which needs network) happens before the
# network namespace is entered.
_ENV_BASE = "FORGE_BASE_IMAGE_PATH"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ConfigError(Exception):
    pass

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------
@dataclass
class VaultConfig:
    url: str = "http://localhost:7777"

@dataclass
class ForgeConfig:
    base_image: str = ""       # path or registry URI for base squashfs

@dataclass
class CacheConfig:
    local:              Path       = field(default_factory=lambda: Path.home() / ".kiln" / "cache")
    # Coffer remote cache (SSH-based)
    coffer_host:        str        = ""
    coffer_port:        int        = 22
    coffer_cachectl:    str        = ""
    coffer_ssh_timeout: int        = 10
    # Legacy / future
    global_url:         str | None = None

@dataclass
class RegistryConfig:
    url: str = ""

@dataclass
class SchedulerConfig:
    max_weight: int = 8

@dataclass
class CrucibleConfig:
    """
    Unified config for kiln and forge.
    build_root is set by find_project_root(), not from toml.
    """
    build_root: Path            = field(default_factory=Path.cwd)
    forge:      ForgeConfig     = field(default_factory=ForgeConfig)
    cache:      CacheConfig     = field(default_factory=CacheConfig)
    registry:   RegistryConfig  = field(default_factory=RegistryConfig)
    scheduler:  SchedulerConfig = field(default_factory=SchedulerConfig)
    vault:      VaultConfig     = field(default_factory=VaultConfig)

    # --- Derived paths ---
    @property
    def components_dir(self) -> Path:
        return self.build_root / "components"

    @property
    def lock_file(self) -> Path:
        return self.build_root / "kiln.lock"

    @property
    def git_cache_dir(self) -> Path:
        return self.build_root / ".kiln" / "git-cache"

    @property
    def local_cache_dir(self) -> Path:
        return self.cache.local.expanduser().resolve()

    @property
    def state_dir(self) -> Path:
        return self.build_root / ".kiln" / "state"

    @property
    def audit_dir(self) -> Path:
        return self.build_root / ".kiln" / "audit"

    @property
    def base_image_path(self) -> Path:
        """
        Resolved path to base squashfs image.

        Resolution order:
          1. FORGE_BASE_IMAGE_PATH env var — set by forge/__main__.py before
             unshare so vault resolution happens outside the network namespace.
          2. forge.toml base_image — vault:blake3: ref or plain path.
          3. Default: <project_root>/images/base.sqsh
        """
        if p := os.environ.get(_ENV_BASE):
            return Path(p)
        if self.forge.base_image:
            if is_vault_ref(self.forge.base_image):
                return resolve_image(
                    self.vault.url,
                    self.forge.base_image,
                    self.local_cache_dir,
                )
            return Path(self.forge.base_image).expanduser()
        return self.build_root / "images" / "base.sqsh"



    @property
    def tarball_cache_dir(self) -> Path:
        return self.build_root / ".kiln" / "tarball-cache"

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def find_project_root(start: Path | None = None) -> Path:
    """
    Walk up from start (default: cwd) looking for forge.toml.
    Raises ConfigError if not found.
    """
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if (directory / "forge.toml").exists():
            return directory
    raise ConfigError(
        "forge.toml not found.\n"
        "Are you inside a Crucible project?\n"
        f"Searched from: {current}"
    )

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def load_config(start: Path | None = None) -> CrucibleConfig:
    """
    Find forge.toml, load project config, overlay machine-local config.
    Returns a fully resolved CrucibleConfig.
    """
    build_root = find_project_root(start)
    config     = CrucibleConfig(build_root=build_root)

    # Layer 1: forge.toml
    _apply_toml(config, build_root / "forge.toml")

    # Layer 2: ~/.kiln/config.toml (machine-local overrides — never committed)
    local_toml = Path.home() / ".kiln" / "config.toml"
    if local_toml.exists():
        _apply_toml(config, local_toml)

    # Layer 3: environment variables (CI)
    if w := os.environ.get("KILN_MAX_WEIGHT"):
        try:
            config.scheduler.max_weight = int(w)
        except ValueError:
            raise ConfigError(f"KILN_MAX_WEIGHT must be an integer, got: {w!r}")
    if c := os.environ.get("KILN_LOCAL_CACHE"):
        config.cache.local = Path(c)
    if h := os.environ.get("KILN_COFFER_HOST"):
        config.cache.coffer_host = h

    return config

def _apply_toml(config: CrucibleConfig, path: Path) -> None:
    """Apply a toml file's settings onto config in-place. Missing keys ignored."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    if vault := data.get("vault"):
        if v := vault.get("url"):
            config.vault.url = v
    if forge := data.get("forge"):
        if v := forge.get("base_image"): config.forge.base_image = v
    if cache := data.get("cache"):
        if v := cache.get("local"):
            config.cache.local = Path(v)
        if v := cache.get("global"):
            config.cache.global_url = v
        if v := cache.get("coffer_host"):
            config.cache.coffer_host = v
        if v := cache.get("coffer_port"):
            try:
                config.cache.coffer_port = int(v)
            except (ValueError, TypeError):
                raise ConfigError(f"coffer_port must be an integer in {path}")
        if v := cache.get("coffer_cachectl"):
            config.cache.coffer_cachectl = v
        if v := cache.get("coffer_ssh_timeout"):
            try:
                config.cache.coffer_ssh_timeout = int(v)
            except (ValueError, TypeError):
                raise ConfigError(f"coffer_ssh_timeout must be an integer in {path}")
    if registry := data.get("registry"):
        if v := registry.get("url"): config.registry.url = v
    if scheduler := data.get("scheduler"):
        if v := scheduler.get("max_weight"):
            config.scheduler.max_weight = int(v)

# ---------------------------------------------------------------------------
# forge.toml template — written by `kiln init`
# ---------------------------------------------------------------------------
FORGE_TOML_TEMPLATE = """\
# forge.toml — Crucible project root marker and configuration
# Commit this file. Machine-local overrides go in ~/.kiln/config.toml
[forge]
# base_image = "images/base.sqsh"    # default: <project_root>/images/base.sqsh
[cache]
local  = "~/.kiln/cache"    # local artifact cache
# Coffer remote cache — set coffer_host to enable.
# Machine-local settings (host, port) belong in ~/.kiln/config.toml.
# coffer_host        = "cache@build.example.com"  # user@hostname
# coffer_port        = 22                          # default: 22
# coffer_cachectl    = ""                          # default: /home/<user>/bin/cachectl
# coffer_ssh_timeout = 10                          # seconds, default: 10
[registry]
url = ""                     # container registry URL
[scheduler]
max_weight = 8               # adjust per machine in ~/.kiln/config.toml
[vault]
url = "http://localhost:7777"  # default vault URL
"""