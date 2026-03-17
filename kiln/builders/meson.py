"""
kiln/builders/meson.py

MesonBuild — meson setup + meson compile + meson install
"""

from __future__ import annotations

import os

from kiln.builders.base import BuildDef, BuildPaths


class MesonBuild(BuildDef):
    """meson setup + meson compile + meson install"""

    def configure_command(self, paths: BuildPaths) -> list[str]:
        cmd = [
            "meson", "setup",
            paths.build, paths.source,
        ]

        if self.c_flags:
            cmd.append(f"-Dc_args={' '.join(self._resolve(self.c_flags, paths))}")
        if self.cxx_flags:
            cmd.append(f"-Dcpp_args={' '.join(self._resolve(self.cxx_flags, paths))}")
        if self.link_flags:
            cmd.append(f"-Dc_link_args={' '.join(self._resolve(self.link_flags, paths))}")
            cmd.append(f"-Dcpp_link_args={' '.join(self._resolve(self.link_flags, paths))}")

        return cmd + self._resolve(self.configure_args, paths)

    def build_command(self, paths: BuildPaths) -> list[str]:
        return [
            "meson", "compile",
            "-C", paths.build,
            "-j", str(os.cpu_count() or 4),
        ]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ["meson", "install", "-C", paths.build]
