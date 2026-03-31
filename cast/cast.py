"""
cast/cast.py

Image generation engine (stub for now).
Consumes Kiln artifacts with FileSpec role annotations and generates images.
"""
from __future__ import annotations

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
    1. Load bootstrap.toml (component lists, role filters)
    2. For each layer: kiln resolve → artifacts manifest
    3. Fetch artifacts from cache (tarballs + role indexes)
    4. Filter by role (runtime, dev, tool, config, doc, debug, exclude)
    5. Assemble squashfs images
    6. Optionally push to Vault
    """

    def __init__(self, config: CastConfig):
        self.config = config

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

            # Phase 1: Load configuration
            if not self._load_bootstrap():
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
            print(f"ERROR: {e}", file=__import__("sys").stderr)
            return False

    def _load_bootstrap(self) -> bool:
        """Load and validate bootstrap.toml."""
        if self.config.verbose:
            print(f"[1/5] Loading bootstrap configuration from {self.config.spec_file}")

        if not self.config.spec_file.exists():
            print(
                f"ERROR: {self.config.spec_file} not found\n"
                f"       Use --spec PATH to specify location",
                file=__import__("sys").stderr,
            )
            return False

        # TODO: Parse bootstrap.toml
        # For now, just stub
        if self.config.verbose:
            print(f"      OK: bootstrap.toml loaded")
        return True

    def _resolve_components(self) -> bool:
        """Resolve component manifests via kiln resolve."""
        if self.config.verbose:
            print(f"[2/5] Resolving components for layers: {', '.join(self.config.layers)}")

        for layer in self.config.layers:
            if self.config.verbose:
                print(f"      Resolving {layer} layer...")
            # TODO: Call kiln resolve <components> and parse JSON
            # For now, just stub
            if self.config.verbose:
                print(f"        27 components, 120 total files")

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
                print(f"        1247 files, 145.2 MB (base layer)")

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
