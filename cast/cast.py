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
        self.resolved_artifacts = {}

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
          kiln --target=<component> deps ensure --push
        
        This ensures the component and all its dependencies are in the cache.
        Kiln handles cache checking and only rebuilds missing artifacts.
        """
        if self.config.verbose:
            print(f"[1/5] Ensuring components are built")

        # Collect all unique components across all layers
        all_components = set()
        for components in self.component_lists.values():
            all_components.update(components)

        if self.config.dry_run:
            if self.config.verbose:
                print(f"      DRY RUN: would ensure {len(all_components)} components are built")
                for comp in sorted(all_components):
                    print(f"        - {comp}")
            return True

        # Build each component with deps
        for component in sorted(all_components):
            if self.config.verbose:
                print(f"      Ensuring {component} is built...")

            # Use 'deps ensure' to ensure the component and all its dependencies are built.
            # 'deps' will build any missing dependencies, then 'ensure' ensures the target itself.
            cmd = ["kiln", "--target", component, "deps", "ensure", "--push"]
            
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
                    print(f"        OK: {component} built and cached")
            
            except FileNotFoundError:
                print("ERROR: kiln not found in PATH", file=sys.stderr)
                return False

        if self.config.verbose:
            print(f"      All components verified in cache")

        return True

    def _resolve_components(self) -> bool:
        """Resolve component manifests via kiln resolve.
        
        For each layer, calls: kiln resolve with component list via stdin.
        Parses JSON output and stores resolved artifacts (including transitive deps).
        Returns True on success, False on error.
        """
        if self.config.verbose:
            print(f"[2/5] Resolving components for layers: {', '.join(self.config.layers)}")

        self.resolved_artifacts = {}

        for layer in self.config.layers:
            components = self.component_lists[layer]

            if self.config.verbose:
                print(f"      Resolving {layer} layer ({len(components)} components)...")

            # For dry-run, skip subprocess call
            if self.config.dry_run:
                if self.config.verbose:
                    print(f"        DRY RUN: would call kiln resolve with {len(components)} components")
                self.resolved_artifacts[layer] = []
                continue

            # Subprocess: kiln resolve (reads JSON from stdin)
            json_input = json.dumps(components)

            try:
                result = subprocess.run(
                    ['kiln', 'resolve'],
                    input=json_input.encode('utf-8'),
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
            except FileNotFoundError:
                print("ERROR: kiln not found in PATH", file=sys.stderr)
                return False
            except subprocess.TimeoutExpired:
                print("ERROR: kiln resolve timed out", file=sys.stderr)
                return False

            # Check subprocess return code
            if result.returncode != 0:
                print(f"ERROR: kiln resolve failed for {layer}", file=sys.stderr)
                stderr_msg = result.stderr.decode('utf-8', errors='replace')
                if stderr_msg:
                    print(f"       {stderr_msg[:300]}", file=sys.stderr)
                return False

            # Parse JSON output
            try:
                data = json.loads(result.stdout.decode('utf-8'))
            except json.JSONDecodeError as e:
                print(f"ERROR: kiln resolve output is not valid JSON: {e}", file=sys.stderr)
                return False
            except UnicodeDecodeError as e:
                print(f"ERROR: kiln resolve output is not valid UTF-8: {e}", file=sys.stderr)
                return False

            # Validate schema and content
            if not self._validate_resolve_output(data, layer):
                return False

            # Store resolved artifacts
            self.resolved_artifacts[layer] = data['artifacts']

            if self.config.verbose:
                total_artifacts = len(data['artifacts'])
                requested_artifacts = sum(1 for a in data['artifacts'] if a['requested'])
                print(f"        Resolved {total_artifacts} artifacts "
                      f"({requested_artifacts} requested, "
                      f"{total_artifacts - requested_artifacts} dependencies)")

        return True

    def _validate_resolve_output(self, data: dict, layer: str) -> bool:
        """Validate kiln resolve JSON output schema.
        
        Checks:
        - schema_version is 1
        - artifacts is a non-empty list
        - all required fields present and correct types
        - no duplicate component names
        - all requested components present
        
        Returns True if valid, False if any check fails (error already printed).
        """
        # Check schema_version
        if data.get('schema_version') != 1:
            print(f"ERROR: unexpected schema_version in kiln output for {layer}: "
                  f"{data.get('schema_version')}", file=sys.stderr)
            return False

        # Check artifacts key exists and is a list
        artifacts = data.get('artifacts')
        if not isinstance(artifacts, list):
            print(f"ERROR: 'artifacts' is not a list in kiln output for {layer}",
                  file=sys.stderr)
            return False

        if not artifacts:
            print(f"ERROR: empty artifacts list from kiln resolve for {layer}",
                  file=sys.stderr)
            return False

        # Validate each artifact
        seen_names = set()
        requested_names = set()

        for idx, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                print(f"ERROR: artifact[{idx}] is not a dict in kiln output for {layer}",
                      file=sys.stderr)
                return False

            # Check required fields
            required_fields = {'component', 'version', 'hash', 'requested'}
            missing = required_fields - set(artifact.keys())
            if missing:
                print(f"ERROR: artifact[{idx}] missing fields in kiln output for {layer}: "
                      f"{', '.join(sorted(missing))}", file=sys.stderr)
                return False

            # Check field types
            if not isinstance(artifact.get('component'), str):
                print(f"ERROR: artifact[{idx}] 'component' is not a string",
                      file=sys.stderr)
                return False
            if not isinstance(artifact.get('version'), str):
                print(f"ERROR: artifact[{idx}] 'version' is not a string",
                      file=sys.stderr)
                return False
            if not isinstance(artifact.get('hash'), str):
                print(f"ERROR: artifact[{idx}] 'hash' is not a string",
                      file=sys.stderr)
                return False
            if not isinstance(artifact.get('requested'), bool):
                print(f"ERROR: artifact[{idx}] 'requested' is not a boolean",
                      file=sys.stderr)
                return False

            comp_name = artifact['component']

            # Check for duplicates
            if comp_name in seen_names:
                print(f"ERROR: duplicate component '{comp_name}' in kiln output for {layer}",
                      file=sys.stderr)
                return False

            seen_names.add(comp_name)
            if artifact['requested']:
                requested_names.add(comp_name)

        # Verify all requested components are in result
        components = self.component_lists[layer]
        missing = set(components) - seen_names
        if missing:
            print(f"ERROR: kiln resolve missing components for {layer}: "
                  f"{', '.join(sorted(missing))}", file=sys.stderr)
            return False

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
