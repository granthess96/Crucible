"""
forge/__main__.py
forge — interactive shell and command runner for the Crucible build environment.
Usage:
    forge                        # interactive shell in build environment
    forge -- <cmd>               # run command in build environment
    forge --cwd <path>           # set working directory inside chroot
    forge --verbose              # show mount commands
Image paths are read from forge.toml [forge] section.
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from crucible.config import load_config, ConfigError
from forge.instance import ForgeInstance, create_dev_nodes


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "forge",
        description = __doc__,
        formatter_class = argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--verbose', '-v', action='store_true',
        help='Show mount commands and chroot invocation')
    parser.add_argument('--cwd', metavar='PATH', default=None,
        help='Working directory for the command (host path, translated to chroot path)')
    parser.add_argument('cmd', nargs=argparse.REMAINDER,
        help='Command to run (default: interactive shell)')
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = make_parser()
    args   = parser.parse_args(argv)

    # All forge operations run inside a user+mount namespace.
    # Re-exec with unshare if not already root.
    if os.geteuid() != 0:
        os.execvp("unshare", [
            "unshare", "--user", "--mount", "--map-root-user",
            "--", sys.executable, *sys.argv,
        ])
        # execvp replaces this process — never reached on success
        print("Error: unshare failed", file=sys.stderr)
        return 1

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Strip leading '--' separator if present
    cmd = args.cmd
    if cmd and cmd[0] == '--':
        cmd = cmd[1:]

    # Resolve --cwd to a Path, falling back to host cwd
    if args.cwd:
        cwd = Path(args.cwd)
    else:
        cwd = Path.cwd()

    try:
        with ForgeInstance(config, verbose=args.verbose) as instance:
            rc = instance.run(cmd, cwd=cwd)
        return rc
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Error: mount failed: {exc}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())