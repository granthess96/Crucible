"""
kiln/builders/base.py

Base classes for all kiln build and assembly components.
Two class hierarchies:
  BuildDef    — compiles source into runtime + buildtime artifacts
  AssemblyDef — composes cached artifacts into environments or images
"""

from __future__ import annotations

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
        return cls(
            source  = f"{workspace}/__source__",
            build   = f"{workspace}/__build__",
            sysroot = f"{workspace}/__sysroot__",
            install = f"{workspace}/__install__",
        )


# ---------------------------------------------------------------------------
# Shared root
# ---------------------------------------------------------------------------

class KilnComponent(ABC):
    name:         ClassVar[str]
    version:      ClassVar[str]
    deps:         ClassVar[list[str]] = []
    build_weight: ClassVar[int]       = 1

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
    c_flags:        ClassVar[list[str]] = ['-fPIC', '-DPIC']
    cxx_flags:      ClassVar[list[str]] = ['-fPIC', '-DPIC']
    link_flags:     ClassVar[list[str]] = []
    configure_args: ClassVar[list[str]] = []
    build_env:      ClassVar[dict[str, str]] = {}

    # Runtime: shared libraries, executables, data files needed at runtime.
    #
    # Patterns use pathlib.PurePosixPath.match() semantics:
    #   *   matches any name segment (no path separator crossing)
    #   **  matches zero or more path segments (crosses separators)
    #
    # All patterns are relative to __install__/ (no leading slash).
    #
    # usr/lib/**/*.so*    catches multiarch (.so, .so.6, .so.6.0.0)
    # usr/lib64/**/*.so*  catches lib64 layout (non-multiarch distros)
    # usr/sbin/**         catches system binaries (ldconfig, etc.)
    # lib/**/*.so*        catches components that install to /lib directly
    # lib64/**/*.so*      catches /lib64 direct installs and symlinks

    runtime_globs: ClassVar[list[str]] = [
        "usr/bin/**",
        "usr/sbin/**",
        "usr/lib/**/*.so",
        "usr/lib/**/*.so.*",
        "usr/lib64/**/*.so",
        "usr/lib64/**/*.so.*",
        "lib/**/*.so",
        "lib/**/*.so.*",
        "lib64/**/*.so",
        "lib64/**/*.so.*",
        "usr/etc/**",
        "usr/share/**",
        "etc/**",
        "share/**",
        "usr/libexec/**",
    ]

    # Buildtime: headers, static libs, pkgconfig, cmake config, linker scripts.
    #
    # usr/lib/**/*.a      catches multiarch static libs
    # usr/lib/**/*.o      catches crt files (crt1.o, crti.o, crtn.o) in multiarch
    # usr/lib/**/pkgconfig/**   catches multiarch pkgconfig
    # usr/lib/**/cmake/**       catches multiarch cmake config

    buildtime_globs: ClassVar[list[str]] = [
        "usr/include/**",
        "usr/lib/**/*.a",
        "usr/lib/**/*.o",
        "usr/lib64/**/*.a",
        "usr/lib64/**/*.o",
        "usr/lib/**/pkgconfig/**",
        "usr/lib64/**/pkgconfig/**",
        "usr/lib/**/cmake/**",
        "usr/lib64/**/cmake/**",
        "usr/lib/**/*.so",
        "usr/lib64/**/*.so",
        "var/lib/**/*.la",
        "var/lib64/**/*.la",
        "usr/man/**",
        "usr/share/man/**",
        "usr/share/info/**",
        "lib64/**",          # ld-linux, libc.so.6 etc — needed in sysroot for linking
        "usr/lib64/**/*.o",
        "usr/lib64/gconv/**",
    ]

    def _resolve(self, values: list[str], paths: BuildPaths) -> list[str]:
        context = {
            "sysroot": paths.sysroot,
            "source":  paths.source,
            "build":   paths.build,
            "install": paths.install,
            "version": self.version,
            "name":    self.name,
        }
        return [v.format_map(context) for v in values]
    
    def _resolve_env(self, paths: BuildPaths) -> dict[str, str]:
        """Resolve {sysroot} etc. placeholders in build_env values."""
        context = {
            "sysroot": paths.sysroot,
            "source":  paths.source,
            "build":   paths.build,
            "install": paths.install,
            "version": self.version,
            "name":    self.name,
        }
        return {k: v.format_map(context) for k, v in self.build_env.items()}    

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({
            "kind":           "build",
            "builder":        self.__class__.__name__,
            "source_pin":     self.source.get("git", self.source.get("url", "")),
            "build_env":      {"sysroot_isolation": True},
            "c_flags":        self.c_flags,
            "cxx_flags":      self.cxx_flags,
            "link_flags":     self.link_flags,
            "configure_args": self.configure_args,
        })
        return fields

    def configure_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError

    def build_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError

    def test_command(self, paths: BuildPaths) -> list[str]:
        return []

    def install_command(self, paths: BuildPaths) -> list[str]:
        raise NotImplementedError

    def configure_script(self, paths: BuildPaths) -> "str | None":
        return None

    def build_script(self, paths: BuildPaths) -> "str | None":
        return None

    def test_script(self, paths: BuildPaths) -> "str | None":
        return None

    def install_script(self, paths: BuildPaths) -> "str | None":
        return None


# ---------------------------------------------------------------------------
# Hierarchy 2: AssemblyDef
# ---------------------------------------------------------------------------

class AssemblyDef(KilnComponent):
    """
    Composes existing cached artifacts into a deployable environment or image.
    Does NOT compile. Does NOT use forge.
    """

    config_dir: ClassVar[Path | None] = None

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({"kind": "assembly", "builder": self.__class__.__name__})
        return fields

    def assemble_command(self, artifact_inputs: dict[str, Path],
                         output_dir: Path) -> None:
        raise NotImplementedError