"""
kiln/builders/autotools.py

AutotoolsBuild — ./configure && make && make install
"""

from __future__ import annotations

import os
from typing import ClassVar

from kiln.builders.base import BuildDef, BuildPaths


class AutotoolsBuild(BuildDef):
    """./configure && make && make install"""

    configure_exe: ClassVar[str] = "configure"

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["configure_exe"] = self.configure_exe
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        cflags   = " ".join(['--sysroot={sysroot}'] + self.c_flags).strip()
        cxxflags = " ".join(['--sysroot={sysroot}'] + self.cxx_flags).strip()
        ldflags  = " ".join([
            '--sysroot={sysroot}',
            '-L{sysroot}/lib64',
            '-L{sysroot}/usr/lib64',
        ] + self.link_flags).strip()

        cflags   = self._resolve([cflags], paths)[0]
        cxxflags = self._resolve([cxxflags], paths)[0]
        ldflags  = self._resolve([ldflags], paths)[0]

        cc = self._resolve(
            [f'gcc --sysroot={{sysroot}} -isystem{{sysroot}}/usr/include'],
            paths
        )[0]

        cmd = [f"{paths.source}/{self.configure_exe}", 
               "--prefix=/usr", 
               "--libdir=/usr/lib64",
               "--disable-nls"]

        cmd.append(f"CC={cc}")

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
