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
    c_flags:        ClassVar[list[str]] = []
    cxx_flags:      ClassVar[list[str]] = []
    link_flags:     ClassVar[list[str]] = []
    configure_args: ClassVar[list[str]] = []

    runtime_globs: ClassVar[list[str]] = [
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
