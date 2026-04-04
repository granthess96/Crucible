"""
cast/__main__.py

Cast entry point and command line interface.
Image generation and projection tool for Crucible.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from cast.cast import Cast, CastConfig


def find_bootstrap_toml(start_dir: Path = None) -> Path | None:
    """
    Walk up from start_dir looking for bootstrap.toml.
    Returns first match or None if not found.
    """
    if start_dir is None:
        start_dir = Path.cwd()

    for d in [start_dir, *start_dir.parents]:
        candidate = d / "bootstrap.toml"
        if candidate.exists():
            return candidate

    return None


def find_forge_toml(start_dir: Path = None) -> Path | None:
    """
    Walk up from start_dir looking for forge.toml (project root marker).
    Returns first match or None if not found.
    """
    if start_dir is None:
        start_dir = Path.cwd()

    for d in [start_dir, *start_dir.parents]:
        candidate = d / "forge.toml"
        if candidate.exists():
            return candidate

    return None


def main(argv: Sequence[str] | None = None) -> int:
    """
    Main entry point for Cast CLI.
    
    Returns:
      0 on success
      1 on error
      2 on invalid arguments
    """
    parser = argparse.ArgumentParser(
        prog="cast",
        description="Image generation and projection tool for Crucible",
        epilog=(
            "Examples:\n"
            "  cast                                    # Build base and tools\n"
            "  cast base                               # Build only base\n"
            "  cast base tools --verbose               # Verbose output\n"
            "  cast --spec custom-bootstrap.toml       # Custom spec file\n"
            "  cast --push --vault http://vault:7777   # Push to Vault\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional arguments
    parser.add_argument(
        "layers",
        nargs="*",
        default=["base", "tools"],
        metavar="LAYER",
        help="Image layers to build: base, tools (default: base tools)",
    )

    # Configuration
    config_group = parser.add_argument_group("configuration")
    config_group.add_argument(
        "--spec",
        "--source",
        dest="spec_file",
        type=Path,
        default=None,
        help="Path to bootstrap.toml (default: auto-discover from cwd)",
    )

    # Output
    output_group = parser.add_argument_group("output")
    output_group.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for generated images (default: <project_root>/images)",
    )

    # Vault
    vault_group = parser.add_argument_group("vault")
    vault_group.add_argument(
        "--vault",
        dest="vault_url",
        default=None,
        help="Vault server URL (default: from forge.toml [vault].url)",
    )
    vault_group.add_argument(
        "--push",
        action="store_true",
        help="Push generated images to Vault",
    )

    # Debug
    debug_group = parser.add_argument_group("debug")
    debug_group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output (show each step)",
    )
    debug_group.add_argument(
        "--bootstrap-stage",
        default=None,
        help="Bootstrap environment stage (stage0, stage1, stage2) - passed to kiln",
    )
    debug_group.add_argument(
        "--debug",
        action="store_true",
        help="Include debug symbols in images (overrides bootstrap.toml)",
    )
    debug_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without building",
    )
    debug_group.add_argument(
        "--keep-staging",
        action="store_true",
        help="Keep staging directories for inspection",
    )
    debug_group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )

    # Parse arguments
    args = parser.parse_args(argv)

    # Validate layers
    valid_layers = {"base", "tools", "stage1", "stage2"}
    invalid = [l for l in args.layers if l not in valid_layers]
    if invalid:
        parser.error(f"Invalid layer(s): {', '.join(invalid)}. Valid: base, tools, stage1, stage2")
        return 2

    if not args.layers:
        parser.error("At least one layer must be specified")
        return 2

    # Find bootstrap.toml
    if args.spec_file is None:
        found = find_bootstrap_toml()
        if found is None:
            print(
                "ERROR: bootstrap.toml not found\n"
                "       Searched in: ./, ../,  ../../, ... (up to git root)\n"
                "       Use --spec PATH to specify location",
                file=sys.stderr,
            )
            return 1
        args.spec_file = found
    else:
        # Resolve relative path
        args.spec_file = args.spec_file.resolve()

    # Find forge.toml (for default Vault URL and output directory)
    forge_toml = find_forge_toml()
    project_root = forge_toml.parent if forge_toml else Path.cwd()

    # Resolve output directory relative to project root
    if args.output_dir is None:
        args.output_dir = project_root / "images"
    elif not args.output_dir.is_absolute():
        # If relative path given, still make it relative to project root
        args.output_dir = project_root / args.output_dir

    # Determine Vault URL
    if args.vault_url is None and args.push:
        if forge_toml:
            try:
                sys.path.insert(0, str(forge_toml.parent))
                from crucible.config import load_config
                cfg = load_config(forge_toml.parent)
                args.vault_url = cfg.vault.url
            except Exception:
                pass

        if args.vault_url is None:
            print(
                "ERROR: Vault URL required for --push\n"
                "       Specify --vault URL or set [vault].url in forge.toml",
                file=sys.stderr,
            )
            return 1

    # Check for conflicting options
    if args.quiet and args.verbose:
        parser.error("--quiet and --verbose are mutually exclusive")
        return 2

    # Create config
    config = CastConfig(
        spec_file=args.spec_file,
        layers=args.layers,
        output_dir=args.output_dir.resolve(),
        vault_url=args.vault_url,
        push=args.push,
        verbose=args.verbose,
        debug=args.debug,
        dry_run=args.dry_run,
        keep_staging=args.keep_staging,
        quiet=args.quiet,
        bootstrap_stage=args.bootstrap_stage,
    )

    # Run Cast
    cast = Cast(config)
    success = cast.run()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
