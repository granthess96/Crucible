"""
cast/cast.py

Image generation engine (stub for now).
Consumes Kiln artifacts with FileSpec role annotations and generates images.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kiln.cache import LocalDiskCache, TieredCache


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
        self.staged_layers = {}
        self.staging_root = config.output_dir / "staging"

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
        """Fetch artifacts from cache and filter by role.
        
        For each layer:
        1. Initialize TieredCache
        2. Extract role rules from bootstrap.toml
        3. For each resolved artifact:
           - Fetch from cache
           - Load files.json.zst (role index)
           - Filter files by role rules
           - Extract filtered files from tarball
           - Stage to layer directory
        4. Build layer metadata for Phase 4
        """
        if self.config.verbose:
            print(f"[3/5] Fetching and filtering artifacts")

        self.staged_layers = {}
        self.staging_root.mkdir(parents=True, exist_ok=True)

        # Initialize cache once
        try:
            cache_root = Path.home() / ".kiln" / "cache"
            local_cache = LocalDiskCache(cache_root)
            tiered_cache = TieredCache(local=local_cache, coffer=None)
        except Exception as e:
            print(f"ERROR: Failed to initialize cache: {e}", file=sys.stderr)
            return False

        for layer in self.config.layers:
            artifacts = self.resolved_artifacts.get(layer, [])
            if not artifacts:
                print(f"WARNING: No artifacts for layer {layer}", file=sys.stderr)
                continue

            if self.config.verbose:
                print(f"      Fetching {len(artifacts)} artifacts for {layer}...")

            # Extract role rules for this layer
            try:
                layer_roles = self.bootstrap_config.get('roles', {}).get(layer, {})
                include_roles = set(layer_roles.get('include', []))
                exclude_roles = set(layer_roles.get('exclude', []))
            except (KeyError, TypeError) as e:
                print(f"ERROR: Invalid role rules in bootstrap.toml for {layer}: {e}", file=sys.stderr)
                return False

            if not include_roles:
                print(f"WARNING: No include roles defined for {layer}", file=sys.stderr)

            # Create layer staging directory
            layer_staging = self.staging_root / layer
            layer_staging.mkdir(parents=True, exist_ok=True)

            # Process each artifact
            layer_metadata = {'components': []}
            for artifact in artifacts:
                if not self.config.dry_run:
                    if not self._fetch_and_filter_artifact(
                        artifact, layer_staging, include_roles, exclude_roles, tiered_cache
                    ):
                        return False
                    layer_metadata['components'].append({
                        'name': artifact['component'],
                        'version': artifact['version'],
                    })
                elif self.config.verbose:
                    print(f"        DRY RUN: would fetch {artifact['component']} v{artifact['version']}")

            # Count files and compute size
            total_files = 0
            total_size = 0
            if not self.config.dry_run and layer_staging.exists():
                for item in layer_staging.rglob('*'):
                    if item.is_file():
                        total_files += 1
                        total_size += item.stat().st_size

            self.staged_layers[layer] = {
                'path': layer_staging,
                'components': layer_metadata['components'],
                'total_files': total_files,
                'total_size_bytes': total_size,
            }

            if self.config.verbose:
                if not self.config.dry_run:
                    size_mb = total_size / 1024 / 1024
                    print(f"        OK: {len(artifacts)} artifacts staged ({total_files} files, {size_mb:.1f} MB)")
                else:
                    print(f"        DRY RUN: would stage {len(artifacts)} artifacts")

        if self.config.dry_run and self.config.verbose:
            print(f"      DRY RUN: stopping before assembly")

        return True

    def _fetch_and_filter_artifact(self, artifact: dict, layer_staging: Path, 
                                   include_roles: set, exclude_roles: set,
                                   tiered_cache: TieredCache) -> bool:
        """Fetch a single artifact and stage filtered files.
        
        Returns True on success, False on error.
        """
        component = artifact['component']
        version = artifact['version']
        
        # Extract manifest hash from "sha256:abc123..." format
        full_hash = artifact['hash']
        manifest_hash = full_hash.split(':', 1)[1] if ':' in full_hash else full_hash
        
        temp_dir = None
        try:
            # Create temporary directory for extraction
            temp_dir = Path(tempfile.mkdtemp(prefix=f"cast-{component}-"))
            
            # Fetch artifact files from cache
            try:
                tiered_cache.fetch(manifest_hash, component, temp_dir)
            except Exception as e:
                print(f"ERROR: Failed to fetch {component}: {e}", file=sys.stderr)
                return False
            
            # Load files.json.zst
            files_index = self._load_files_index(temp_dir / f"{component}.files.json.zst")
            if files_index is None:
                return False
            
            # Filter files by role rules
            filtered_files = self._filter_by_roles(files_index.get('files', {}), 
                                                   include_roles, exclude_roles)
            
            if not filtered_files:
                if self.config.verbose:
                    print(f"        WARNING: No files matching roles for {component}")
                # Still return True - some components may have no matching files
                return True
            
            # Extract filtered files from tarball
            if not self._extract_filtered_tarball(temp_dir / f"{component}.tar.zst", 
                                                 filtered_files, temp_dir):
                return False
            
            # Stage extracted files to layer directory
            self._stage_files(temp_dir, filtered_files, layer_staging)
            
            return True
        
        except Exception as e:
            print(f"ERROR: Failed to process {component}: {e}", file=sys.stderr)
            return False
        
        finally:
            # Cleanup temporary directory
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    def _load_files_index(self, files_json_zst: Path) -> dict | None:
        """Decompress and parse files.json.zst.
        
        Returns the parsed JSON dict on success, None on error.
        """
        try:
            # Use zstd to decompress via stdin/stdout
            with open(files_json_zst, 'rb') as f:
                result = subprocess.run(
                    ['zstd', '-d'],
                    stdin=f,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            
            # Parse JSON
            data = json.loads(result.stdout)
            
            # Validate structure
            if not isinstance(data, dict) or 'files' not in data:
                print(f"ERROR: Invalid files.json.zst format: missing 'files' key", file=sys.stderr)
                return None
            
            return data
        
        except subprocess.CalledProcessError as e:
            print(f"ERROR: zstd decompression failed: {e.stderr}", file=sys.stderr)
            return None
        except json.JSONDecodeError as e:
            print(f"ERROR: JSON parse error in files.json.zst: {e}", file=sys.stderr)
            return None
        except FileNotFoundError:
            print(f"ERROR: zstd not found in PATH", file=sys.stderr)
            return None
        except Exception as e:
            print(f"ERROR: Failed to load files.json.zst: {e}", file=sys.stderr)
            return None

    def _filter_by_roles(self, files: dict[str, str], 
                        include_roles: set, exclude_roles: set) -> dict[str, str]:
        """Filter files by role rules.
        
        Include a file if its role is in include_roles AND NOT in exclude_roles.
        """
        filtered = {}
        for path, role in files.items():
            if role in include_roles and role not in exclude_roles:
                filtered[path] = role
        return filtered

    def _extract_filtered_tarball(self, tar_path: Path, filtered_files: dict, 
                                 temp_dir: Path) -> bool:
        """Extract filtered files from tarball.
        
        Uses tar -T (read patterns from file) to extract only necessary paths,
        avoiding memory bloat from large compressed archives.
        """
        if not filtered_files:
            return True
        
        try:
            # Write file list to temporary patterns file
            patterns_file = temp_dir / ".patterns.txt"
            patterns_file.write_text('\n'.join(filtered_files.keys()))
            
            # Extract only specified files
            result = subprocess.run(
                ['tar', '--use-compress-program=zstd', '--extract', '-f', str(tar_path),
                 '-T', str(patterns_file)],
                capture_output=True,
                text=True,
                cwd=str(temp_dir),
                check=True,
            )
            
            return True
        
        except subprocess.CalledProcessError as e:
            print(f"ERROR: tar extraction failed: {e.stderr}", file=sys.stderr)
            return False
        except FileNotFoundError:
            print(f"ERROR: tar not found in PATH", file=sys.stderr)
            return False
        except Exception as e:
            print(f"ERROR: Failed to extract tarball: {e}", file=sys.stderr)
            return False

    def _stage_files(self, src_root: Path, filtered_files: dict, dst_root: Path) -> None:
        """Copy extracted files from temp to layer staging, preserving directory structure."""
        for path in filtered_files.keys():
            src = src_root / path
            dst = dst_root / path
            
            # Create parent directories if needed
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file (or symlink)
            if src.is_symlink():
                # Preserve symlink
                link_target = src.readlink()
                try:
                    dst.symlink_to(link_target)
                except FileExistsError:
                    pass  # Already exists, skip
            elif src.is_file():
                # Copy file, preserving metadata
                try:
                    shutil.copy2(src, dst, follow_symlinks=True)
                except Exception as e:
                    # Log but continue - some files may be inaccessible
                    if self.config.verbose:
                        print(f"        WARNING: Failed to copy {path}: {e}")


    def _assemble_images(self) -> bool:
        """Create squashfs images from staged file trees.
        
        For each layer:
        1. Call mksquashfs on staging/<layer>/
        2. Compute manifest hash
        3. Store metadata
        """
        if self.config.verbose:
            print(f"[4/5] Assembling squashfs images")

        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        for layer in self.config.layers:
            layer_staging = self.staging_root / layer
            output_file = self.config.output_dir / f"{layer}.sqsh"
            
            if self.config.verbose:
                print(f"      Creating {layer}.sqsh...")
            
            # Check if staging directory exists
            if not layer_staging.exists():
                if self.config.verbose:
                    print(f"        WARNING: No staging data for {layer}")
                continue
            
            # Call mksquashfs
            try:
                result = subprocess.run(
                    ['mksquashfs', str(layer_staging), str(output_file),
                     '-quiet', '-comp', 'zstd'],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                
                # Verify output file
                if not output_file.exists():
                    print(f"ERROR: mksquashfs failed to create {output_file}", file=sys.stderr)
                    return False
                
                # Get file size and compute metadata
                file_size = output_file.stat().st_size
                size_mb = file_size / 1024 / 1024
                
                # Compute manifest hash for the image
                manifest_hash = self._compute_image_manifest_hash(layer, output_file)
                
                if self.config.verbose:
                    print(f"        OK: {output_file} ({size_mb:.1f} MB)")
                    if manifest_hash:
                        print(f"        Manifest: {manifest_hash[:12]}...")
            
            except subprocess.CalledProcessError as e:
                print(f"ERROR: mksquashfs failed: {e.stderr}", file=sys.stderr)
                return False
            except FileNotFoundError:
                print(f"ERROR: mksquashfs not found in PATH", file=sys.stderr)
                return False
            except Exception as e:
                print(f"ERROR: Failed to create {layer}.sqsh: {e}", file=sys.stderr)
                return False
        
        # Cleanup staging directories if not keeping them
        if not self.config.keep_staging:
            try:
                shutil.rmtree(self.staging_root, ignore_errors=True)
                if self.config.verbose:
                    print(f"      Cleaned up staging directories")
            except Exception as e:
                if self.config.verbose:
                    print(f"        WARNING: Failed to clean staging: {e}")

        return True

    def _compute_image_manifest_hash(self, layer: str, image_file: Path) -> str | None:
        """Compute manifest hash for squashfs image.
        
        Hash includes: layer name, image file hash, component list.
        """
        try:
            from kiln.manifest import hash_file
            
            # Get file hash
            image_hash = hash_file(image_file)
            
            # Build simple manifest text for reproducibility
            layer_info = self.staged_layers.get(layer, {})
            components = layer_info.get('components', [])
            component_names = sorted([c['name'] for c in components])
            
            manifest_text = f"""layer: {layer}
image_hash: {image_hash}
components: {len(component_names)}
component_list:
"""
            for comp in component_names:
                manifest_text += f"  - {comp}\n"
            
            # Compute hash of manifest
            from hashlib import sha256
            return sha256(manifest_text.encode('utf-8')).hexdigest()
        
        except Exception as e:
            if self.config.verbose:
                print(f"        WARNING: Failed to compute manifest hash: {e}")
            return None

    def _push_to_vault(self) -> bool:
        """Push images to Vault.
        
        For each created image:
        1. Upload blob to Vault
        2. Create manifest entry
        3. Tag for easy reference
        """
        if self.config.verbose:
            print(f"[5/5] Pushing images to Vault")
        
        if not self.config.vault_url:
            print("ERROR: --vault-url required for --push", file=sys.stderr)
            return False
        
        # Try to import httpx for uploads
        try:
            import httpx
        except ImportError:
            print("ERROR: httpx required for Vault uploads (install with: pip install httpx)", file=sys.stderr)
            return False
        
        for layer in self.config.layers:
            image_file = self.config.output_dir / f"{layer}.sqsh"
            if not image_file.exists():
                if self.config.verbose:
                    print(f"        WARNING: {layer}.sqsh not found, skipping")
                continue
            
            if self.config.verbose:
                print(f"      Pushing {layer}.sqsh to {self.config.vault_url}...")
            
            try:
                # Compute blob digest (sha256)
                blob_digest = self._compute_file_digest(image_file)
                
                # Upload blob to Vault
                blob_url = f"{self.config.vault_url.rstrip('/')}/blob/{blob_digest}"
                
                with open(image_file, 'rb') as f:
                    # Use PUT for blob upload
                    response = httpx.put(blob_url, content=f.read(), timeout=300)
                    response.raise_for_status()
                
                # Create manifest tag
                manifest_tag = f"{layer}-latest"
                tag_url = f"{self.config.vault_url.rstrip('/')}/tag/{manifest_tag}"
                
                manifest_data = {
                    "blob_digest": f"sha256:{blob_digest}",
                    "layer": layer,
                    "created": str(image_file.stat().st_mtime),
                    "size_bytes": image_file.stat().st_size,
                }
                
                # Use POST for tag creation
                response = httpx.post(tag_url, json=manifest_data, timeout=60)
                response.raise_for_status()
                
                if self.config.verbose:
                    print(f"        Digest: sha256:{blob_digest[:12]}...")
                    print(f"        Tag: {manifest_tag}")
                    print(f"        Status: OK")
            
            except httpx.HTTPError as e:
                print(f"ERROR: Failed to push {layer} to Vault: {e}", file=sys.stderr)
                return False
            except Exception as e:
                print(f"ERROR: Push failed for {layer}: {e}", file=sys.stderr)
                return False
        
        return True

    def _compute_file_digest(self, file_path: Path) -> str:
        """Compute SHA256 digest of file."""
        from hashlib import sha256
        sha = sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(1024 * 1024):
                sha.update(chunk)
        return sha.hexdigest()

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
