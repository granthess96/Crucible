"""
forge/__main__.py

forge — interactive shell and command runner for the Crucible build environment.

Usage:
    forge                        # interactive shell in build environment
    forge -- <cmd>               # run command in build environment
    forge --create               # create base.sqsh from DNF
    forge --verbose              # show mount commands

Image paths are read from forge.toml [forge] section.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_here = Path(__file__).parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from crucible.config import load_config, ConfigError, FORGE_TOML_TEMPLATE
from forge.instance import ForgeInstance, create_dev_nodes

BASE_PACKAGES = [
    "coreutils", "bash", "util-linux", "shadow-utils",
    "filesystem", "glibc", "gcc-c++", "make", "cmake",
    "autoconf", "automake", "libtool", "ninja-build",
    "git", "pkgconfig", "bison", "flex", "gawk", "m4",
    "texinfo", "gettext", "file", "findutils",
    "tar", "gzip", "xz", "bzip2", "zlib", "zstd",
    "perl", "python3", "python3-pip",
    "squashfs-tools", "diffutils", "e2fsprogs", "patch",
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "forge",
        description = __doc__,
        formatter_class = argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--create', action='store_true',
        help='Create base.sqsh from DNF packages')
    parser.add_argument('--verbose', '-v', action='store_true',
        help='Show mount commands and chroot invocation')
    parser.add_argument('cmd', nargs=argparse.REMAINDER,
        help='Command to run (default: interactive shell)')
    return parser


# ---------------------------------------------------------------------------
# --create: DNF populate → squash
# ---------------------------------------------------------------------------

def create_base_image(config, verbose: bool):
    """Populate a temp rootfs via DNF and squash it to base.sqsh."""
    base_sqsh = config.base_image_path

    if base_sqsh.exists():
        print(f"Error: {base_sqsh} already exists.", file=sys.stderr)
        print(f"       Delete it first to recreate.", file=sys.stderr)
        return 1

    base_sqsh.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="forge-create-") as tmp:
        rootfs = Path(tmp) / "rootfs"
        rootfs.mkdir()

        print(f"Populating rootfs via DNF ...")
        cmd = [
            'dnf', '--use-host-config',
            '--installroot', str(rootfs),
            '--releasever', '43',
            '-y', 'install',
        ] + BASE_PACKAGES
        if verbose:
            print(f"+ {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

        # Create mount point stubs — these must exist in the image
        for stub in ('proc', 'sys', 'dev', 'workspace', 'toolchain'):
            (rootfs / stub).mkdir(exist_ok=True)

        create_dev_nodes(rootfs / "dev")

        print(f"Squashing → {base_sqsh} ...")
        squash_cmd = [
            'mksquashfs', str(rootfs), str(base_sqsh),
            '-comp', 'zstd',
            '-e', 'proc', 'sys', 'dev',
            '-noappend',
        ]
        if verbose:
            print(f"+ {' '.join(squash_cmd)}")
        subprocess.run(squash_cmd, check=True)

    size_mb = base_sqsh.stat().st_size / 1024 / 1024
    print(f"Base image created: {base_sqsh}  ({size_mb:.1f} MB)")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = make_parser()
    args   = parser.parse_args(argv)

    if os.geteuid() != 0:
        print("Error: forge must be run as root.", file=sys.stderr)
        return 1

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.create:
        return create_base_image(config, args.verbose)

    # Strip leading '--' separator if present
    cmd = args.cmd
    if cmd and cmd[0] == '--':
        cmd = cmd[1:]

    try:
        with ForgeInstance(config, verbose=args.verbose) as instance:
            rc = instance.run(cmd, cwd=Path.cwd())
        return rc
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Error: mount failed: {exc}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
