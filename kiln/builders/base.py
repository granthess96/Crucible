"""
kiln/builders/base.py
Base class for all kiln build components.

BuildDef compiles source into installed artifacts.  Role assignment for
packaging is handled by path inference in kiln/verbs/packaging.py; the
optional `files` list carries FileSpec overrides for the minority of paths
where the heuristic would guess wrong.

Lifecycle: deps → fetch → checkout → configure → build → test → install → package
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
# BuildDef
# ---------------------------------------------------------------------------
class BuildDef(KilnComponent):
    """
    Compiles source into a packaged artifact.

    Path inference in kiln/verbs/packaging.py assigns a Role to every file
    under __install__/.  The `files` list is for exceptions only — paths
    where the heuristic would guess wrong, files that need a non-obvious
    role, or files that should be excluded entirely.  Most components leave
    `files` empty.
    """
    from kiln.spec import FileSpec  # local import to avoid circular at module level

    source:         ClassVar[dict]           = {}
    c_flags:        ClassVar[list[str]]      = ['-fPIC', '-DPIC']
    cxx_flags:      ClassVar[list[str]]      = ['-fPIC', '-DPIC']
    link_flags:     ClassVar[list[str]]      = []
    configure_args: ClassVar[list[str]]      = []
    build_env:      ClassVar[dict[str, str]] = {}
    files:          ClassVar[list]           = []   # list[FileSpec] — overrides only

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
