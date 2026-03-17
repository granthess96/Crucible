"""
kiln/builders/script.py

ScriptBuild — arbitrary build logic via shell scripts
"""

from __future__ import annotations

from kiln.builders.base import BuildDef, BuildPaths


class ScriptBuild(BuildDef):
    """
    Arbitrary build logic — override *_command() or *_script() methods.
    Use when a component's build system doesn't fit autotools, cmake,
    meson, or plain make.
    """

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement build_command() or build_script()"
        )

    def install_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement install_command() or install_script()"
        )
