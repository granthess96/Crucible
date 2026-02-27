"""
kiln/config.py — re-exports from crucible.config for backward compatibility.
Import from crucible.config directly in new code.
"""
from crucible.config import (
    CrucibleConfig as KilnConfig,
    ForgeConfig,
    CacheConfig,
    RegistryConfig,
    SchedulerConfig,
    ConfigError,
    find_project_root as find_build_root,
    load_config,
    FORGE_TOML_TEMPLATE,
)

__all__ = [
    "KilnConfig", "ForgeConfig", "CacheConfig",
    "RegistryConfig", "SchedulerConfig", "ConfigError",
    "find_build_root", "load_config", "FORGE_TOML_TEMPLATE",
]
