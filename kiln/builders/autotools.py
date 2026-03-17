"""
kiln/builders/autotools.py

AutotoolsBuild — ./configure && make && make install
"""

from __future__ import annotations

import os
from typing import ClassVar

import cmd

from kiln.builders.base import BuildDef, BuildPaths


class AutotoolsBuild(BuildDef):
    """./configure && make && make install"""

    configure_exe: ClassVar[str] = "configure"

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["configure_exe"] = self.configure_exe
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        cflags   = " ".join(self._resolve(self.c_flags, paths)).strip()
        cxxflags = " ".join(self._resolve(self.cxx_flags, paths)).strip()
        ldflags  = " ".join(self._resolve(self.link_flags, paths)).strip()

        cmd = [f"{paths.source}/{self.configure_exe}"]

        if cflags:
            cmd.append(f"CFLAGS={cflags}")
        if cxxflags:
            cmd.append(f"CXXFLAGS={cxxflags}")
        if ldflags:
            cmd.append(f"LDFLAGS={ldflags}")

        return cmd + self._resolve(self.configure_args, paths)  

    def build_command(self, paths: BuildPaths) -> list[str]:
        return ["make", f"-j{os.cpu_count() or 4}"]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ["make", f"DESTDIR={paths.install}", "install"]
