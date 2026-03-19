"""
kiln/registry.py

Filesystem-based component discovery and build.py loader.

Discovery rule:
  components/<name>/build.py  must contain exactly one class that is a
  subclass of KilnComponent.  The directory name is the canonical component
  name and must match the class's `name` attribute.

The registry lazily loads component build.py files on demand — a component
is discovered by scanning the components/ directory but not imported until
it is actually needed by the current build target's transitive dep tree.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Type

from kiln.builders.base import KilnComponent, BuildDef, AssemblyDef


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RegistryError(Exception):
    """Raised when a build.py cannot be loaded or is malformed."""
    def __init__(self, component_dir: Path, reason: str):
        self.component_dir = component_dir
        self.reason = reason
        super().__init__(f"{component_dir.name}: {reason}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ComponentRegistry:
    """
    Immutable map of component name → KilnComponent subclass.
    Components are discovered eagerly by scanning the components/ directory
    but loaded lazily on first access.
    """

    def __init__(self, components_root: Path):
        self._root = components_root
        self._classes: dict[str, Type[KilnComponent]] = {}
        self._build_py_paths: dict[str, Path] = {}
        self._patches_dirs: dict[str, Path | None] = {}
        self._discovered: dict[str, Path] = {}  # name → build.py path, unloaded
        self._scan()

    def _scan(self) -> None:
        """Discover available components without loading them."""
        if not self._root.is_dir():
            raise RegistryError(self._root, "components/ directory not found")

        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir():
                continue
            build_py = entry / "build.py"
            if not build_py.exists():
                continue
            self._discovered[entry.name] = build_py

    def _ensure_loaded(self, name: str) -> None:
        """Load a component's build.py if not already loaded."""
        if name in self._classes:
            return
        if name not in self._discovered:
            raise KeyError(name)
        self._load_one(
            self._discovered[name].parent,
            self._discovered[name],
        )

    def _load_one(self, component_dir: Path, build_py: Path) -> None:
        name = component_dir.name
        module_name = f"_kiln_component_{name}"

        spec = importlib.util.spec_from_file_location(module_name, build_py)
        if spec is None or spec.loader is None:
            raise RegistryError(component_dir, "could not create module spec")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise RegistryError(component_dir, f"error executing build.py: {exc}") from exc

        # Find the one concrete KilnComponent subclass defined in this file
        candidates = [
            obj for obj in vars(module).values()
            if (
                inspect.isclass(obj)
                and issubclass(obj, KilnComponent)
                and obj is not KilnComponent
                and obj.__module__ == module_name
                # Skip abstract intermediates that don't declare name+version
                and hasattr(obj, "name")
                and hasattr(obj, "version")
                and not inspect.isabstract(obj)
            )
        ]

        if len(candidates) == 0:
            raise RegistryError(
                component_dir,
                "build.py contains no concrete KilnComponent subclass"
            )
        if len(candidates) > 1:
            names = [c.__name__ for c in candidates]
            raise RegistryError(
                component_dir,
                f"build.py contains multiple KilnComponent subclasses: {names}. "
                f"Only one is permitted per build.py."
            )

        cls = candidates[0]

        # Validate: class name attribute must match directory name
        if cls.name != name:
            raise RegistryError(
                component_dir,
                f"class attribute name='{cls.name}' does not match "
                f"directory name '{name}'"
            )

        # Detect patches directory
        patches_dir = component_dir / "patches"

        self._classes[name]        = cls
        self._build_py_paths[name] = build_py
        self._patches_dirs[name]   = patches_dir if patches_dir.is_dir() else None

    # --- Public API ---

    def __contains__(self, name: str) -> bool:
        return name in self._discovered

    def __len__(self) -> int:
        return len(self._discovered)

    def get(self, name: str) -> Type[KilnComponent]:
        """
        Return the class for a component name.
        Raises KeyError if not found — callers convert to ResolveError.
        """
        self._ensure_loaded(name)
        return self._classes[name]

    def instantiate(self, name: str) -> KilnComponent:
        """Return a fresh instance of the component class."""
        self._ensure_loaded(name)
        return self._classes[name]()

    def build_py_path(self, name: str) -> Path:
        return self._discovered[name]

    def patches_dir(self, name: str) -> Path | None:
        self._ensure_loaded(name)
        return self._patches_dirs.get(name)

    def all_names(self) -> list[str]:
        return sorted(self._discovered.keys())

    def is_build_def(self, name: str) -> bool:
        self._ensure_loaded(name)
        return issubclass(self._classes[name], BuildDef)

    def is_assembly_def(self, name: str) -> bool:
        self._ensure_loaded(name)
        return issubclass(self._classes[name], AssemblyDef)
