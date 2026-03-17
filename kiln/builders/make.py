"""
kiln/builders/make.py

MakeBuild — plain Makefile, no configure step
"""

from __future__ import annotations

import os
from typing import ClassVar

from kiln.builders.base import BuildDef, BuildPaths


class MakeBuild(BuildDef):
    """Plain Makefile — no configure step, build in source dir."""

    make_targets:    ClassVar[list[str]] = ["all"]
    install_targets: ClassVar[list[str]] = ["install"]
    make_vars:       ClassVar[list[str]] = []

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["make_targets"]    = self.make_targets
        fields["install_targets"] = self.install_targets
        fields["make_vars"]       = self.make_vars
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_command(self, paths: BuildPaths) -> list[str]:
        return [
            "make", f"-j{os.cpu_count() or 4}",
            "-C", paths.source,
        ] + self._resolve(self.make_vars, paths) + self.make_targets

    def install_command(self, paths: BuildPaths) -> list[str]:
        return [
            "make",
            "-C", paths.source,
            f"DESTDIR={paths.install}",
        ] + self._resolve(self.make_vars, paths) + self.install_targets
