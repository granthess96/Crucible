"""
kiln/config.py

Configuration loader for kiln/forge.

Two config sources, merged in order (later overrides earlier):
  1. forge.toml  — project config, at build tree root, committed to repo
  2. ~/.kiln/config.toml — machine-local overrides, never committed

Discovery:
  Walk up from cwd looking for forge.toml.
  That directory is the build root — all relative paths resolve from there.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class CacheConfig:
    local:  Path
    global_url: str | None = None      # https://, s3://, or local path

@dataclass
class RegistryConfig:
    url: str = ""

@dataclass
class SchedulerConfig:
    max_weight: int = 8

@dataclass
class ForgeConfig:
    base_image: str = ""               # registry URI for forge base squashfs
    toolchain:  str = ""               # registry URI for toolchain image

@dataclass
class KilnConfig:
    # Build tree root — set by find_build_root(), not from toml
    build_root:  Path = field(default_factory=Path.cwd)

    # Project config (forge.toml)
    forge:       ForgeConfig     = field(default_factory=ForgeConfig)
    cache:       CacheConfig     = field(default_factory=lambda: CacheConfig(
                                       local=Path.home() / ".kiln" / "cache"
                                   ))
    registry:    RegistryConfig  = field(default_factory=RegistryConfig)
    scheduler:   SchedulerConfig = field(default_factory=SchedulerConfig)

    # Derived paths — all relative to build_root
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


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_build_root(start: Path | None = None) -> Path:
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
        "Are you inside a kiln build tree?\n"
        f"Searched from: {current}"
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(start: Path | None = None) -> KilnConfig:
    """
    Find forge.toml, load project config, then overlay machine-local config.
    Returns a fully resolved KilnConfig.
    """
    build_root = find_build_root(start)
    config     = KilnConfig(build_root=build_root)

    # --- Layer 1: forge.toml (project config) ---
    forge_toml = build_root / "forge.toml"
    _apply_toml(config, forge_toml)

    # --- Layer 2: ~/.kiln/config.toml (machine-local overrides) ---
    local_toml = Path.home() / ".kiln" / "config.toml"
    if local_toml.exists():
        _apply_toml(config, local_toml)

    # --- Layer 3: Environment variable overrides ---
    # Useful for CI without a machine-local config file
    if (w := os.environ.get("KILN_MAX_WEIGHT")):
        try:
            config.scheduler.max_weight = int(w)
        except ValueError:
            raise ConfigError(f"KILN_MAX_WEIGHT must be an integer, got: {w!r}")

    if (c := os.environ.get("KILN_LOCAL_CACHE")):
        config.cache.local = Path(c)

    if (g := os.environ.get("KILN_GLOBAL_CACHE")):
        config.cache.global_url = g

    return config


def _apply_toml(config: KilnConfig, path: Path) -> None:
    """Apply a toml file's settings onto config in-place. Missing keys are ignored."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    if forge := data.get("forge"):
        if v := forge.get("base_image"):
            config.forge.base_image = v
        if v := forge.get("toolchain"):
            config.forge.toolchain = v

    if cache := data.get("cache"):
        if v := cache.get("local"):
            config.cache.local = Path(v)
        if v := cache.get("global"):
            config.cache.global_url = v

    if registry := data.get("registry"):
        if v := registry.get("url"):
            config.registry.url = v

    if scheduler := data.get("scheduler"):
        if v := scheduler.get("max_weight"):
            config.scheduler.max_weight = int(v)


# ---------------------------------------------------------------------------
# forge.toml template — written by `kiln init`
# ---------------------------------------------------------------------------

FORGE_TOML_TEMPLATE = """\
# forge.toml — kiln/forge build tree root marker and configuration
# Commit this file. Machine-local overrides go in ~/.kiln/config.toml

[forge]
base_image = ""    # registry URI for forge base squashfs image
toolchain  = ""    # registry URI for toolchain image

[cache]
local  = "~/.kiln/cache"    # local artifact cache (machine-local default)
# global = ""               # global cache URI — set when available

[registry]
url = ""                     # container registry URL

[scheduler]
max_weight = 8               # adjust per machine in ~/.kiln/config.toml
"""