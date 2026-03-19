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

    # All forge operations run inside a user+mount+network namespace.
    # Re-exec with unshare if not already root.
    if os.geteuid() != 0:
        os.execvp("unshare", [
            "unshare", "--user", "--mount", "--map-root-user", "--net",
            "--", sys.executable, *sys.argv,
        ])
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
    cwd = Path(args.cwd) if args.cwd else Path.cwd()

    # Infer component path from cwd — must be inside components/<pkg>/
    try:
        rel = cwd.resolve().relative_to(config.build_root / "components")
        component_path = config.build_root / "components" / rel.parts[0]
    except (ValueError, IndexError):
        print(
            f"Error: must be run from inside a components/<pkg>/ directory\n"
            f"  cwd: {cwd}\n"
            f"  project root: {config.build_root}",
            file=sys.stderr,
        )
        return 1

    try:
        with ForgeInstance(config, component_path, verbose=args.verbose) as instance:
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
