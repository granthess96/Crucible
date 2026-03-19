"""
kiln/builders/cmake.py

CMakeBuild — cmake configure + build + install
"""

from __future__ import annotations

import os
from typing import ClassVar

from kiln.builders.base import BuildDef, BuildPaths


class CMakeBuild(BuildDef):
    """cmake configure + build + install"""

    cmake_generator: ClassVar[str] = "Ninja"

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["cmake_generator"] = self.cmake_generator
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        cmd = [
            "cmake", paths.source,
            f"-B{paths.build}",
            f"-DCMAKE_STAGING_PREFIX={paths.install}/usr",
            f"-DCMAKE_SYSROOT={paths.sysroot}",
            f"-G{self.cmake_generator}",
            "-DCMAKE_C_COMPILER_WORKS=1",
            "-DCMAKE_CXX_COMPILER_WORKS=1",
        ]

        c_flags   = ["--sysroot={sysroot}"] + self.c_flags
        cxx_flags = ["--sysroot={sysroot}"] + self.cxx_flags

        cmd.append(f"-DCMAKE_C_FLAGS={' '.join(self._resolve(c_flags, paths))}")
        cmd.append(f"-DCMAKE_CXX_FLAGS={' '.join(self._resolve(cxx_flags, paths))}")

        if self.link_flags:
            cmd.append(f"-DCMAKE_EXE_LINKER_FLAGS={' '.join(self._resolve(self.link_flags, paths))}")

        return cmd + self._resolve(self.configure_args, paths)


    def build_command(self, paths: BuildPaths) -> list[str]:
        return [
            "cmake", "--build", paths.build,
            "--parallel", str(os.cpu_count() or 4),
        ]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ["cmake", "--install", paths.build]
