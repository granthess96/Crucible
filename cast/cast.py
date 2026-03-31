"""
cast/cast.py

Image generation engine (stub for now).
Consumes Kiln artifacts with FileSpec role annotations and generates images.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class CastConfig:
    """Cast configuration from CLI arguments."""
    spec_file: Path
    layers: list[str]
    output_dir: Path
    vault_url: str | None
    push: bool
    verbose: bool
    debug: bool
    dry_run: bool
    keep_staging: bool
    quiet: bool


class Cast:
    """
    Image generation engine.
    
    Workflow:
    0. Load bootstrap.toml (component lists, role filters)
    1. Build all components to ensure artifacts are in cache
    2. Resolve component manifests via kiln resolve
    3. Fetch artifacts from cache and filter by role
    4. Assemble squashfs images
    5. Optionally push to Vault
    """

    def __init__(self, config: CastConfig):
        self.config = config
        self.bootstrap_config = {}
        self.component_lists = {}

    def run(self) -> bool:
        """
        Execute the image generation workflow.
        Returns True on success, False on error.
        """
        try:
            if self.config.verbose:
                print(f"Cast v1 (stub)")
                print(f"  Spec: {self.config.spec_file}")
                print(f"  Layers: {', '.join(self.config.layers)}")
                print(f"  Output: {self.config.output_dir}")
                if self.config.vault_url:
                    print(f"  Vault: {self.config.vault_url}")
                if self.config.dry_run:
                    print(f"  Mode: DRY RUN")
                if self.config.debug:
                    print(f"  Mode: DEBUG (include symbols)")
                print()

            # Phase 0: Load configuration
            if not self._load_bootstrap():
                return False

            # Phase 1: Ensure all components are built
            if not self._ensure_components_built():
                return False

            # Phase 2: Resolve components for each layer
            if not self._resolve_components():
                return False

            # Phase 3: Fetch and filter (or dry-run)
            if not self._fetch_and_filter():
                return False

            # Phase 4: Assemble images (or skip for dry-run)
            if not self.config.dry_run:
                if not self._assemble_images():
                    return False

            # Phase 5: Push to Vault (optional)
            if self.config.push and not self.config.dry_run:
                if not self._push_to_vault():
                    return False

            if not self.config.quiet:
                self._print_summary()

            return True

        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return False

    def _load_bootstrap(self) -> bool:
        """Load and validate bootstrap.toml."""
        if self.config.verbose:
            print(f"[0/5] Loading bootstrap configuration from {self.config.spec_file}")

        if not self.config.spec_file.exists():
            print(
                f"ERROR: {self.config.spec_file} not found\n"
                f"       Use --spec PATH to specify location",
                file=sys.stderr,
            )
            return False

        try:
            with self.config.spec_file.open("rb") as f:
                self.bootstrap_config = tomllib.load(f)
            
            # Validate structure
            if "image" not in self.bootstrap_config:
                print("ERROR: bootstrap.toml missing [image] section", file=sys.stderr)
                return False
            
            # Store component lists for each requested layer
            for layer in self.config.layers:
                if layer not in self.bootstrap_config.get("image", {}):
                    print(f"ERROR: [image.{layer}] not found in bootstrap.toml", file=sys.stderr)
                    return False
                components = self.bootstrap_config["image"][layer].get("components", [])
                self.component_lists[layer] = components
            
            if self.config.verbose:
                print(f"      OK: bootstrap.toml loaded")
                for layer, components in self.component_lists.items():
                    print(f"        {layer}: {len(components)} components")
            
            return True
        except Exception as e:
            print(f"ERROR: Failed to load bootstrap.toml: {e}", file=sys.stderr)
            return False

    def _ensure_components_built(self) -> bool:
        """
        Ensure all components are built and in cache.
        
        For each component in all layers, run:
          kiln --target=<component> purge fetch checkout configure build install test package --push
        
        If not --keep-staging, append 'purge' to clean up after.
        """
        if self.config.verbose:
            print(f"[1/5] Ensuring components are built")

        # Collect all unique components across all layers
        all_components = set()
        for components in self.component_lists.values():
            all_components.update(components)

        if self.config.dry_run:
            if self.config.verbose:
                print(f"      DRY RUN: would build {len(all_components)} components")
                for comp in sorted(all_components):
                    print(f"        - {comp}")
            return True

        # Build each component
        for component in sorted(all_components):
            if self.config.verbose:
                print(f"      Building {component}...")

            # Build verbs: purge first, then fetch through package, then optional final purge
            verbs = ["purge", "fetch", "checkout", "configure", "build", "install", "test", "package", "--push"]
            if not self.config.keep_staging:
                verbs.append("purge")

            cmd = ["kiln", "--target", component] + verbs
            
            try:
                if self.config.verbose:
                    print(f"        Running: {' '.join(cmd)}")
                
                result = subprocess.run(
                    cmd,
                    capture_output=not self.config.verbose,
                    check=False,
                )
                
                if result.returncode != 0:
                    print(f"ERROR: kiln failed for {component}", file=sys.stderr)
                    if not self.config.verbose:
                        print(f"       Run with --verbose to see details", file=sys.stderr)
                    return False
                
                if self.config.verbose:
                    print(f"        OK: {component} built")
            
            except FileNotFoundError:
                print("ERROR: kiln not found in PATH", file=sys.stderr)
                return False

        if self.config.verbose:
            print(f"      All components built and cached")

        return True

    def _resolve_components(self) -> bool:
        """Resolve component manifests via kiln resolve."""
        if self.config.verbose:
            print(f"[2/5] Resolving components for layers: {', '.join(self.config.layers)}")

        for layer in self.config.layers:
            components = self.component_lists[layer]
            if self.config.verbose:
                print(f"      Resolving {layer} layer ({len(components)} components)...")
            
            # TODO: Call kiln resolve <components> and parse JSON
            # For now, just stub
            if self.config.verbose:
                print(f"        {len(components)} components, ~120 total files per component")

        return True

    def _fetch_and_filter(self) -> bool:
        """Fetch artifacts from cache and filter by role."""
        if self.config.verbose:
            print(f"[3/5] Fetching and filtering artifacts")

        for layer in self.config.layers:
            if self.config.verbose:
                print(f"      Fetching {layer} layer artifacts...")
            
            # TODO: Fetch .tar.zst + .files.json.zst from cache
            # Filter by role specification
            # For now, just stub
            if self.config.verbose:
                print(f"        1247 files, 145.2 MB ({layer} layer)")

        if self.config.dry_run and self.config.verbose:
            print(f"      DRY RUN: stopping before assembly")

        return True

    def _assemble_images(self) -> bool:
        """Create squashfs images."""
        if self.config.verbose:
            print(f"[4/5] Assembling squashfs images")

        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        for layer in self.config.layers:
            if self.config.verbose:
                print(f"      Creating {layer}.sqsh...")
            
            # TODO: Call mksquashfs
            # Compute manifest hash
            # For now, just stub
            output_file = self.config.output_dir / f"{layer}.sqsh"
            if self.config.verbose:
                print(f"        Created: {output_file} (87 MB)")

        if not self.config.keep_staging and self.config.verbose:
            print(f"      Cleaned up staging directories")

        return True

    def _push_to_vault(self) -> bool:
        """Push images to Vault."""
        if self.config.verbose:
            print(f"[5/5] Pushing images to Vault")

        # TODO: Connect to Vault, create blobs, tag
        # For now, just stub
        for layer in self.config.layers:
            if self.config.verbose:
                print(f"      Pushing {layer}.sqsh to {self.config.vault_url}")
                print(f"        Digest: sha256:xyz789...")
                print(f"        Tag: {layer}-latest")
                print(f"        Status: OK")

        return True

    def _print_summary(self) -> bool:
        """Print summary of what was done."""
        print("\n" + "=" * 60)
        print("Cast Summary")
        print("=" * 60)
        for layer in self.config.layers:
            output_file = self.config.output_dir / f"{layer}.sqsh"
            if output_file.exists():
                size_mb = output_file.stat().st_size / 1024 / 1024
                print(f"{layer:10} {output_file} ({size_mb:.1f} MB)")
        if self.config.push:
            print("\nImages pushed to Vault.")
        print()
        return True
