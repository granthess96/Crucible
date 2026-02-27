"""
kiln/builders/base.py

Base classes for all kiln build and assembly components.
Two class hierarchies:
  BuildDef    — compiles source into runtime + buildtime artifacts
  AssemblyDef — composes cached artifacts into environments or images
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar


# ---------------------------------------------------------------------------
# Shared root
# ---------------------------------------------------------------------------

class KilnComponent(ABC):
    """
    Shared base for all component types — both BuildDef and AssemblyDef.

    Class attributes are declared here and overridden in subclasses.
    Instance attributes are set by the executor during a build run.
    """

    # --- Identity ---
    name:    ClassVar[str]           # must match the components/ directory name
    version: ClassVar[str]

    # --- DAG ---
    deps: ClassVar[list[str]] = []   # short names, resolved via components/ filesystem

    # --- Scheduler ---
    build_weight: ClassVar[int] = 1  # relative resource cost
                                     # build_weight > max_weight → solo mode (still runs)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Ensure concrete subclasses declare name and version.
        # Abstract intermediates (AutotoolsBuild, CMakeBuild etc.) are exempt.
        if not getattr(cls, '__abstractmethods__', None):
            if not hasattr(cls, 'name') or cls.name is KilnComponent.__dict__.get('name'):
                pass   # will be caught at load time by the registry, not here
            if not hasattr(cls, 'version'):
                pass   # same

    def manifest_fields(self) -> dict[str, object]:
        """
        Returns an ordered dict of fields that contribute to the manifest hash.
        Subclasses must call super() and extend the result — never replace it.
        Fields must be deterministic: no timestamps, no host paths, no PIDs.
        """
        return {
            "component": self.name,
            "version":   self.version,
            "deps":      sorted(self.deps),   # sorted for determinism
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}=={self.version}>"


# ---------------------------------------------------------------------------
# Hierarchy 1: BuildDef — produces artifacts via compilation
# ---------------------------------------------------------------------------

class BuildDef(KilnComponent):
    """
    Compiles source (fetched via git) into a runtime and buildtime artifact pair.

    Lifecycle (each step is a discrete kiln verb):
        deps → fetch → configure → build → test → install → package
    """

    # --- Source ---
    source: ClassVar[dict] = {}
    # Expected shape:
    #   { "git": "https://...", "ref": "v1.2.3" }
    # ref is a tag, branch, or commit SHA.
    # kiln.lock stores the resolved commit SHA — ref is only used on first fetch.

    # --- Build flags (passed through to the build system) ---
    comp_flags:      ClassVar[list[str]] = []
    link_flags:      ClassVar[list[str]] = []
    configure_args:  ClassVar[list[str]] = []

    # --- Package split globs ---
    # Base class defaults cover the common case.
    # Override only when a component is non-standard.
    runtime_globs:   ClassVar[list[str]] = [
        "bin/**",
        "lib/*.so*",
        "lib/*.dylib*",
        "etc/**",
        "share/**",
    ]
    buildtime_globs: ClassVar[list[str]] = [
        "include/**",
        "lib/*.a",
        "lib/pkgconfig/**",
        "lib/cmake/**",
    ]

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({
            "kind":           "build",
            "builder":        self.__class__.__name__,
            "source_git":     self.source.get("git", ""),
            # source_commit is filled in at resolve time from kiln.lock
            # builder_hash is filled in at resolve time (hash of build.py)
            # patches_hash  is filled in at resolve time (hash of patches/ tree)
            "comp_flags":     self.comp_flags,
            "link_flags":     self.link_flags,
            "configure_args": self.configure_args,
        })
        return fields

    # --- Lifecycle hooks ---
    # Each method corresponds to one kiln verb.
    # Base class implementations are reasonable defaults.
    # Override in subclass only when the component needs non-standard behaviour.

    def do_fetch(self, src_dir: Path) -> None:
        """Fetch source into src_dir. Default: git clone/checkout."""
        raise NotImplementedError

    def do_configure(self, src_dir: Path, build_dir: Path, sysroot: Path) -> None:
        """Run configure step (autotools, cmake, meson etc.)"""
        raise NotImplementedError

    def do_build(self, build_dir: Path) -> None:
        """Compile."""
        raise NotImplementedError

    def do_test(self, build_dir: Path) -> None:
        """Run test suite. Default: no-op (override to enable)."""
        pass

    def do_install(self, build_dir: Path, install_dir: Path) -> None:
        """DESTDIR install into install_dir."""
        raise NotImplementedError

    def do_package(self, install_dir: Path) -> tuple[Path, Path]:
        """
        Split install_dir into runtime and buildtime tarballs.
        Returns (runtime_tarball, buildtime_tarball).
        Default implementation uses runtime_globs / buildtime_globs.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete BuildDef subclasses — one per supported build system
# ---------------------------------------------------------------------------

class AutotoolsBuild(BuildDef):
    """./configure && make && make install"""

    configure_script: ClassVar[str] = "./configure"   # override if non-standard

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["configure_script"] = self.configure_script
        return fields


class CMakeBuild(BuildDef):
    """cmake configure + build + install"""

    cmake_generator: ClassVar[str] = "Ninja"   # Ninja is faster than make

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["cmake_generator"] = self.cmake_generator
        return fields


class MakeBuild(BuildDef):
    """Plain Makefile — no configure step."""

    make_targets: ClassVar[list[str]] = ["all"]
    install_targets: ClassVar[list[str]] = ["install"]

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields["make_targets"]   = self.make_targets
        fields["install_targets"] = self.install_targets
        return fields


class MesonBuild(BuildDef):
    """meson setup + meson compile + meson install"""
    pass


class ScriptBuild(BuildDef):
    """
    Arbitrary build logic — override the do_* methods directly.
    Use when no standard build system applies.
    """
    pass


# ---------------------------------------------------------------------------
# Hierarchy 2: AssemblyDef — composes artifacts into environments or images
# ---------------------------------------------------------------------------

class AssemblyDef(KilnComponent):
    """
    Composes existing cached artifacts into a deployable environment or image.

    Does NOT compile anything.
    Does NOT use forge/chroot — operates on the host, manipulates artifacts.
    Output goes to the container registry, not the artifact cache.

    Lifecycle:
        deps → assemble → publish
    """

    # AssemblyDef has no source git — inputs are artifact cache keys.
    # Optional: config files or overlay content committed to the meta-build repo.
    config_dir: ClassVar[Path | None] = None

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({
            "kind":    "assembly",
            "builder": self.__class__.__name__,
        })
        return fields

    def do_assemble(
        self,
        artifact_inputs: dict[str, Path],    # name → unpacked BuildDef artifact path
        image_inputs:    dict[str, object],  # name → pulled AssemblyDef OCI image
        output_dir:      Path,
    ) -> None:
        """
        Compose inputs into output_dir.
        The executor will push output_dir to the registry after this returns.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete AssemblyDef subclasses
# ---------------------------------------------------------------------------

class ChrootAssembly(AssemblyDef):
    """
    Assembles the forge base SquashFS image.
    Output: base.sqsh → registry artifact consumed by all BuildDef builds.
    """
    build_weight: ClassVar[int] = 2


class SysrootAssembly(AssemblyDef):
    """Cross-compilation sysroot from buildtime packages."""
    pass


class ToolchainAssembly(AssemblyDef):
    """gcc/clang/binutils + sysroot composed into a coherent toolchain."""
    build_weight: ClassVar[int] = 3


class ContainerAssembly(AssemblyDef):
    """OCI/Docker image layer composition."""
    pass


class StackAssembly(AssemblyDef):
    """
    Top-level product assembly — e.g. a full ROCm stack.
    Pulls runtime artifacts from cache, composes final image, pushes to registry.
    """
    build_weight: ClassVar[int] = 2