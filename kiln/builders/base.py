"""
kiln/builders/base.py

Base classes for all kiln build and assembly components.
Two class hierarchies:
  BuildDef    — compiles source into runtime + buildtime artifacts
  AssemblyDef — composes cached artifacts into environments or images

BuildDef subclasses implement *_command() methods that return lists of
strings — commands to run inside the forge chroot. They receive a
BuildPaths instance carrying the chroot-internal paths, so the builder
never needs to know where anything lives on the host.

Verb → method mapping:
  kiln configure  →  configure_command()
  kiln build      →  build_command()
  kiln test       →  test_command()      (returns [] if no tests)
  kiln install    →  install_command()
"""

from __future__ import annotations

import os
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


# ---------------------------------------------------------------------------
# BuildPaths — chroot-internal paths passed to all command methods
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildPaths:
    """
    All paths are strings representing locations inside the forge chroot.
    Derived from the component name and the fixed /workspace/ mount point.

    Example for component 'zlib':
      source  = /workspace/components/zlib/__source__
      build   = /workspace/components/zlib/__build__
      sysroot = /workspace/components/zlib/__sysroot__
      install = /workspace/components/zlib/__install__
    """
    source:  str
    build:   str
    sysroot: str
    install: str

    @classmethod
    def for_component(cls, name: str, workspace: str = "/workspace") -> BuildPaths:
        """Construct BuildPaths for a named component at the standard locations."""
        base = f"{workspace}/components/{name}"
        return cls(
            source  = f"{base}/__source__",
            build   = f"{base}/__build__",
            sysroot = f"{base}/__sysroot__",
            install = f"{base}/__install__",
        )


# ---------------------------------------------------------------------------
# Shared root
# ---------------------------------------------------------------------------

class KilnComponent(ABC):
    """
    Shared base for all component types — both BuildDef and AssemblyDef.
    Class attributes are declared here and overridden in subclasses.
    """

    # --- Identity ---
    name:    ClassVar[str]
    version: ClassVar[str]

    # --- DAG ---
    deps: ClassVar[list[str]] = []

    # --- Scheduler ---
    build_weight: ClassVar[int] = 1

    def manifest_fields(self) -> dict[str, object]:
        return {
            "component": self.name,
            "version":   self.version,
            "deps":      sorted(self.deps),
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}=={self.version}>"


# ---------------------------------------------------------------------------
# Hierarchy 1: BuildDef
# ---------------------------------------------------------------------------

class BuildDef(KilnComponent):
    """
    Compiles source into a runtime and buildtime artifact pair.
    Lifecycle: deps → fetch → checkout → configure → build → test → install → package
    """

    source:         ClassVar[dict]      = {}
    comp_flags:     ClassVar[list[str]] = []
    link_flags:     ClassVar[list[str]] = []
    configure_args: ClassVar[list[str]] = []

    runtime_globs:   ClassVar[list[str]] = [
        "bin/**", "lib/*.so*", "lib/*.dylib*", "etc/**", "share/**",
    ]
    buildtime_globs: ClassVar[list[str]] = [
        "include/**", "lib/*.a", "lib/pkgconfig/**", "lib/cmake/**",
    ]

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({
            "kind":           "build",
            "builder":        self.__class__.__name__,
            "source_git":     self.source.get("git", ""),
            "comp_flags":     self.comp_flags,
            "link_flags":     self.link_flags,
            "configure_args": self.configure_args,
        })
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement configure_command()")

    def build_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement build_command()")

    def test_command(self, paths: BuildPaths) -> list[str]:
        return []   # default: no tests

    def install_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement install_command()")


# ---------------------------------------------------------------------------
# Concrete BuildDef subclasses
# ---------------------------------------------------------------------------

class AutotoolsBuild(BuildDef):
    """./configure && make && make install"""

    configure_script: ClassVar[str] = "configure"   # relative to __source__/

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["configure_script"] = self.configure_script
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        cflags  = f"-I{paths.sysroot}/usr/include {' '.join(self.comp_flags)}".strip()
        ldflags = f"-L{paths.sysroot}/usr/lib {' '.join(self.link_flags)}".strip()
        pkg_config_path = (
            f"{paths.sysroot}/usr/lib/pkgconfig"
            f":{paths.sysroot}/usr/lib64/pkgconfig"
        )
        return [
            f"{paths.source}/{self.configure_script}",
            f"--prefix={paths.install}",
            f"PKG_CONFIG_PATH={pkg_config_path}",
            f"CFLAGS={cflags}",
            f"LDFLAGS={ldflags}",
        ] + self.configure_args

    def build_command(self, paths: BuildPaths) -> list[str]:
        return ['make', f'-j{os.cpu_count() or 4}']

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['make', 'install']


class CMakeBuild(BuildDef):
    """cmake configure + build + install"""

    cmake_generator: ClassVar[str] = "Ninja"

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["cmake_generator"] = self.cmake_generator
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        cmd = [
            'cmake', paths.source,
            f'-B{paths.build}',
            f'-DCMAKE_PREFIX_PATH={paths.sysroot}',
            f'-DCMAKE_INSTALL_PREFIX={paths.install}',
            f'-G{self.cmake_generator}',
        ]
        if self.comp_flags:
            flags = ' '.join(self.comp_flags)
            cmd += [f'-DCMAKE_C_FLAGS={flags}', f'-DCMAKE_CXX_FLAGS={flags}']
        if self.link_flags:
            cmd.append(f'-DCMAKE_EXE_LINKER_FLAGS={" ".join(self.link_flags)}')
        return cmd + self.configure_args

    def build_command(self, paths: BuildPaths) -> list[str]:
        return ['cmake', '--build', paths.build,
                '--parallel', str(os.cpu_count() or 4)]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['cmake', '--install', paths.build]


class MakeBuild(BuildDef):
    """Plain Makefile — no configure step."""

    make_targets:    ClassVar[list[str]] = ['all']
    install_targets: ClassVar[list[str]] = ['install']

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields['make_targets']    = self.make_targets
        fields['install_targets'] = self.install_targets
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []   # no configure step

    def build_command(self, paths: BuildPaths) -> list[str]:
        return ['make', f'-j{os.cpu_count() or 4}'] + self.make_targets

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['make', f'PREFIX={paths.install}'] + self.install_targets


class MesonBuild(BuildDef):
    """meson setup + meson compile + meson install"""

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return [
            'meson', 'setup',
            paths.build, paths.source,
            f'--prefix={paths.install}',
            f'--pkg-config-path={paths.sysroot}/usr/lib/pkgconfig',
        ] + self.configure_args

    def build_command(self, paths: BuildPaths) -> list[str]:
        return ['meson', 'compile', '-C', paths.build,
                '-j', str(os.cpu_count() or 4)]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['meson', 'install', '-C', paths.build]


class ScriptBuild(BuildDef):
    """Arbitrary build logic — override *_command() methods directly."""

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement build_command()")

    def install_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement install_command()")


# ---------------------------------------------------------------------------
# Hierarchy 2: AssemblyDef
# ---------------------------------------------------------------------------

class AssemblyDef(KilnComponent):
    """
    Composes existing cached artifacts into a deployable environment or image.
    Does NOT compile. Does NOT use forge.
    Output goes to the container registry, not the artifact cache.
    """

    config_dir: ClassVar[Path | None] = None

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({"kind": "assembly", "builder": self.__class__.__name__})
        return fields

    def assemble_command(self, artifact_inputs: dict[str, Path],
                         output_dir: Path) -> None:
        raise NotImplementedError


class ChrootAssembly(AssemblyDef):
    """Assembles the forge base SquashFS image."""
    build_weight: ClassVar[int] = 2

class SysrootAssembly(AssemblyDef):
    """Cross-compilation sysroot from buildtime packages."""
    pass

class ToolchainAssembly(AssemblyDef):
    """gcc/clang/binutils composed into a coherent toolchain."""
    build_weight: ClassVar[int] = 3

class ContainerAssembly(AssemblyDef):
    """OCI/Docker image layer composition."""
    pass

class StackAssembly(AssemblyDef):
    """Top-level product assembly."""
    build_weight: ClassVar[int] = 2