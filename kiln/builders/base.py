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
    c_flags:        ClassVar[list[str]] = []
    cxx_flags:      ClassVar[list[str]] = []
    link_flags:     ClassVar[list[str]] = []
    configure_args: ClassVar[list[str]] = []

    runtime_globs:   ClassVar[list[str]] = [
        "usr/bin/**",
        "usr/lib/*.so*",
        "usr/lib64/*.so*",
        "usr/lib/*.dylib*",
        "usr/etc/**",
        "usr/share/**",
        "etc/**",
        "share/**",
    ]
    buildtime_globs: ClassVar[list[str]] = [
        "usr/include/**",
        "usr/lib/*.a",
        "usr/lib64/*.a",
        "usr/lib/pkgconfig/**",
        "usr/lib64/pkgconfig/**",
        "usr/lib/cmake/**",
        "usr/lib64/cmake/**",
        "usr/lib/*.so",
        "usr/lib64/*.so*",
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

    # --- Script overrides ---
    # Return a bash script body instead of a command list.
    # Written to __build__/kiln-<verb>.sh and executed inside forge.
    # Takes precedence over the corresponding *_command() method.
    # Use when a verb needs multi-step logic, env vars, or conditionals
    # that don't fit cleanly in a single command list.

    def configure_script(self, paths: BuildPaths) -> "str | None":
        return None

    def build_script(self, paths: BuildPaths) -> "str | None":
        return None

    def test_script(self, paths: BuildPaths) -> "str | None":
        return None

    def install_script(self, paths: BuildPaths) -> "str | None":
        return None


# ---------------------------------------------------------------------------
# Concrete BuildDef subclasses
# ---------------------------------------------------------------------------

class AutotoolsBuild(BuildDef):
    """./configure && make && make install"""

    configure_exe: ClassVar[str] = "configure"   # relative to __source__/

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["configure_exe"] = self.configure_exe
        return fields

def configure_command(self, paths: BuildPaths) -> list[str]:
    cflags   = f"-I{paths.sysroot}/usr/include {' '.join(self.c_flags)}".strip()
    cxxflags = f"-I{paths.sysroot}/usr/include {' '.join(self.cxx_flags)}".strip()
    ldflags  = f"-L{paths.sysroot}/usr/lib64 -L{paths.sysroot}/usr/lib {' '.join(self.link_flags)}".strip()
    pkg_config_path = (
        f"{paths.sysroot}/usr/lib/pkgconfig"
        f":{paths.sysroot}/usr/lib64/pkgconfig"
    )
    return [
        f"{paths.source}/{self.configure_exe}",
        "--prefix=/usr",
        f"PKG_CONFIG_PATH={pkg_config_path}",
        f"CFLAGS={cflags}",
        f"CXXFLAGS={cxxflags}",
        f"LDFLAGS={ldflags}",
    ] + self.configure_args

    def build_command(self, paths: BuildPaths) -> list[str]:
        return ['make', f'-j{os.cpu_count() or 4}']

    def install_command(self, paths: BuildPaths) -> list[str]:
        # DESTDIR redirects the install into __install__/ without affecting
        # the baked-in prefix — files land at __install__/usr/lib/ etc.
        return ['make', f'DESTDIR={paths.install}', 'install']


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
            f'-DCMAKE_PREFIX_PATH={paths.sysroot}/usr',
            f'-DCMAKE_INSTALL_PREFIX=/usr',
            f'-DCMAKE_STAGING_PREFIX={paths.install}/usr',
            f'-G{self.cmake_generator}',
            '-DCMAKE_C_COMPILER_WORKS=1',
            '-DCMAKE_CXX_COMPILER_WORKS=1',
            f'-DCMAKE_LIBRARY_PATH={paths.sysroot}/usr/lib64;{paths.sysroot}/usr/lib',
            f'-DCMAKE_INCLUDE_PATH={paths.sysroot}/usr/include',
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
    """Plain Makefile — no configure step, build in source dir."""

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
        return [
            'make', f'-j{os.cpu_count() or 4}',
            '-C', paths.source,
        ] + self.make_targets

    def install_command(self, paths: BuildPaths) -> list[str]:
        return [
            'make',
            '-C', paths.source,
            f'PREFIX=/usr',
            f'DESTDIR={paths.install}',
        ] + self.install_targets


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

class ImageDef(AssemblyDef):
    """
    Assembles dep runtime artifacts into a squashfs image.
    Subclasses declare deps and optionally override squashfs_args
    or post_install() for image-specific fixups.

    Output: <output_dir>/image.sqsh
    """

    # Override in subclass to pass extra flags to mksquashfs
    squashfs_args: ClassVar[list[str]] = ['-comp', 'zstd', '-noappend',
                                          '-force-uid', '0', '-force-gid', '0']

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({
            "kind":          "image",
            "squashfs_args": self.squashfs_args,
        })
        return fields

    def post_install(self, rootfs: Path) -> None:
        """
        Override to perform image-specific fixups after all runtime
        tarballs have been extracted but before mksquashfs runs.
        Examples: create symlinks, write /etc files, add device nodes.
        """
        pass

    def assemble_command(self, artifact_inputs: dict[str, Path],
                         output_dir: Path) -> None:
        import subprocess

        rootfs = output_dir / 'rootfs'
        rootfs.mkdir(parents=True, exist_ok=True)

        # Extract runtime tarballs in topo order
        for name, artifact_dir in artifact_inputs.items():
            runtime = artifact_dir / f'{name}.runtime.tar.zst'
            if not runtime.exists():
                raise RuntimeError(
                    f'{name}: missing runtime tarball — '
                    f'was it built with kiln package?'
                )
            result = subprocess.run(
                ['tar', '--use-compress-program=zstd', '-xf', str(runtime),
                 '-C', str(rootfs)],
            )
            if result.returncode != 0:
                raise RuntimeError(f'{name}: failed to extract runtime tarball')

        # Image-specific fixups
        self.post_install(rootfs)

        # Pack into squashfs
        sqsh = output_dir / 'image.sqsh'
        result = subprocess.run(
            ['mksquashfs', str(rootfs), str(sqsh)] + self.squashfs_args,
        )
        if result.returncode != 0:
            raise RuntimeError(f'{self.name}: mksquashfs failed')


class ContainerDef(AssemblyDef):
    """
    Assembles dep runtime artifacts into an OCI/podman container image.
    TBD — subclass AssemblyDef when container support is needed.
    """

    def assemble_command(self, artifact_inputs: dict[str, Path],
                         output_dir: Path) -> None:
        raise NotImplementedError(
            f'{self.name}: ContainerDef.assemble_command not yet implemented'
        )