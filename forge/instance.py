"""
forge/instance.py

ForgeInstance — manages the SquashFS + OverlayFS mount stack for one
forge invocation.

Stack (bottom to top):
  base.sqsh    → base_mount/   (squashfs, ro)  — base OS
  tools.sqsh   → tools_mount/  (squashfs, ro)  — toolchain layer
  tmpfs        → rw/           (tmpfs)          — ephemeral rw
                 rw/upper/     (overlayfs upper)
                 rw/work/      (overlayfs work)
  overlayfs    → merged/       (chroot root)   — unified view

Plus inside merged/:
  proc/        fresh procfs mount
  sys/         fresh sysfs mount
  dev/         mknod minimum device nodes
  workspace/   bind mount of project root (forge.toml directory)

Usage:
  from forge.instance import ForgeInstance

  with ForgeInstance(config) as instance:
      instance.run(['cmake', '--version'])
      instance.run(['bash'])   # interactive shell
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import shlex
from crucible.config import CrucibleConfig

INSTANCES_DIR  = Path.home() / ".kiln" / "instances"
WORKSPACE_PATH = "/workspace"     # project root appears here inside chroot


# ---------------------------------------------------------------------------
# Device nodes
# ---------------------------------------------------------------------------

def create_dev_nodes(dev_dir: Path):
    """Create minimal device nodes inside the chroot dev directory."""
    dev_dir.mkdir(parents=True, exist_ok=True)
    nodes = [
        ('null',    'c', 1, 3),
        ('zero',    'c', 1, 5),
        ('urandom', 'c', 1, 9),
        ('random',  'c', 1, 8),
        ('tty',     'c', 5, 0),
    ]
    for name, kind, major, minor in nodes:
        path = dev_dir / name
        if not path.exists():
            _run(['mknod', str(path), kind, str(major), str(minor)])
            path.chmod(0o666)


# ---------------------------------------------------------------------------
# ForgeInstance
# ---------------------------------------------------------------------------

class ForgeInstance:
    """
    Context manager for one forge build environment.
    Always cleans up mounts on exit, even on error.
    """

    def __init__(self, config: CrucibleConfig, component_path: Path, verbose: bool = False):
        self.config         = config
        self.component_path = component_path  # e.g. <project_root>/components/zlib
        self.verbose        = verbose
        self._instance_dir: Path | None = None
        self._merged:       Path | None = None
        self._mounted:      list[tuple] = []  # (Path, "fuse"|"kernel")

    # --- Context manager ---

    def __enter__(self) -> ForgeInstance:
        self._setup()
        return self

    def __exit__(self, *_):
        self._teardown()

    # --- Public interface ---

    @property
    def merged(self) -> Path:
        """The chroot root — overlayfs merged view."""
        if self._merged is None:
            raise RuntimeError("ForgeInstance not yet set up — use as context manager")
        return self._merged

    def run(self, command: list[str], cwd: Path | None = None) -> int:
        """
        Run command inside the chroot.
        cwd: host-side path inside the project tree — translated to chroot path.
        Returns the process return code.
        """
        target_dir = self._chroot_path(cwd or self.config.build_root)
        if command:
            cmd_parts = []
            for c in command:
                s = str(c)
                if '=' in s and not s.startswith('-'):
                    key, val = s.split('=', 1)
                    cmd_parts.append(f"{key}={shlex.quote(val)}")
                else:
                    cmd_parts.append(shlex.quote(s))
            cmd_str = ' '.join(cmd_parts)
            
            chroot_cmd = [
                'chroot', str(self.merged),
                '/bin/bash', '-c', f'cd {target_dir} && {cmd_str}'
            ]
        else:
            chroot_cmd = [
                'chroot', str(self.merged),
                '/bin/bash', '-c', f'cd {target_dir} && exec /bin/bash'
            ]

        if self.verbose:
            print(f"+ {' '.join(chroot_cmd)}")

        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": WORKSPACE_PATH,
            "TERM": os.environ.get("TERM", "xterm"),
        }

        result = subprocess.run(chroot_cmd, check=False, env=env)
        return result.returncode

    def run_checked(self, command: list[str], cwd: Path | None = None):
        """Run command inside chroot, raise on non-zero exit."""
        rc = self.run(command, cwd)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, command)

    # --- Mount lifecycle ---

    def _setup(self):
        INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
        self._instance_dir = Path(tempfile.mkdtemp(
            dir=INSTANCES_DIR, prefix="forge-"
        ))

        base_mount = self._instance_dir / "base"
        rw_dir     = self._instance_dir / "rw"
        self._merged = self._instance_dir / "merged"

        for d in (base_mount, rw_dir, self._merged):
            d.mkdir()

        base_sqsh = self.config.base_image_path

        # Validate base image exists before attempting mount
        if not base_sqsh.exists():
            raise RuntimeError(
                f"Image not found: {base_sqsh}\n"
                f"Check forge.toml [forge] settings or run 'forge --create'."
            )

        # 1. Base squashfs — squashfuse (FUSE, no loop device, works in user namespace)
        _run(['squashfuse', str(base_sqsh), str(base_mount)], self.verbose)
        self._mounted.append((base_mount, 'fuse'))

        # 2. tmpfs — upper and work must be siblings on the same filesystem
        _run(['mount', '-t', 'tmpfs', 'tmpfs', str(rw_dir)], self.verbose)
        self._mounted.append((rw_dir, 'kernel'))

        upper = rw_dir / "upper"
        work  = rw_dir / "work"
        upper.mkdir()
        work.mkdir()

        # 3. OverlayFS — tmpfs as rw layer over base
        lowerdir = str(base_mount)
        _run(['mount', '-t', 'overlay', 'overlay',
              '-o', f'lowerdir={lowerdir},upperdir={upper},workdir={work}',
              str(self._merged)], self.verbose)
        self._mounted.append((self._merged, 'kernel'))

        # 4. Create mount point stubs — squashfs has no /dev /proc /sys /workspace
        for stub in ('tmp', 'proc', 'sys', 'dev', WORKSPACE_PATH.lstrip('/')):
            (self._merged / stub).mkdir(exist_ok=True)

        # 5. Bind mount essential device nodes from host.
        #    mknod requires real root — not available in user namespaces.
        #    Bind mounting host devices gives fully functional nodes.
        dev_nodes = ['null', 'zero', 'urandom', 'random', 'tty']
        for node in dev_nodes:
            host_node   = Path('/dev') / node
            chroot_node = self._merged / 'dev' / node
            chroot_node.touch()   # bind mount requires existing target
            _run(['mount', '--bind', str(host_node), str(chroot_node)],
                 self.verbose)
            self._mounted.append((chroot_node, 'kernel'))

        # 6. Component directory → /workspace
        workspace = self._merged / WORKSPACE_PATH.lstrip('/')
        _run(['mount', '--bind', str(self.component_path), str(workspace)], self.verbose)
        self._mounted.append((workspace, 'kernel'))
                   
    def _teardown(self):
    # Kill any processes still using the chroot before attempting umounts
        if self._merged and self._merged.exists():
            subprocess.run(
                ['fuser', '-km', str(self._merged)],
                check=False,
                capture_output=not self.verbose,
            )

        # Unmount in reverse order
        for mount_point, kind in reversed(self._mounted):
            if kind == 'fuse':
                result = subprocess.run(
                    ['fusermount', '-u', str(mount_point)],
                    check=False,
                    capture_output=not self.verbose,
                )
                if result.returncode != 0:
                    print(
                        f"WARNING: fusermount failed for {mount_point}: "
                        f"{result.stderr.decode().strip()}",
                        file=sys.stderr,
                    )
            else:
                result = subprocess.run(
                    ['umount', str(mount_point)],
                    check=False,
                    capture_output=not self.verbose,
                )
                if result.returncode != 0:
                    print(
                        f"WARNING: umount failed for {mount_point}: "
                        f"{result.stderr.decode().strip()}",
                        file=sys.stderr,
                    )

        # ------------------------------------------------------------------
        # SAFE CLEANUP: only remove instance dir if NO mounts remain
        # ------------------------------------------------------------------
        if self._instance_dir and self._instance_dir.exists():
            remaining = subprocess.run(
                ['findmnt', '--json', '--submounts', str(self._instance_dir)],
                capture_output=True,
                text=True,
            )

            safe_to_delete = False

            if remaining.returncode == 0:
                try:
                    data = json.loads(remaining.stdout)
                    mounts = data.get("filesystems", [])

                    # ONLY safe if explicitly empty
                    if not mounts:
                        safe_to_delete = True
                except json.JSONDecodeError:
                    # Parsing failed → treat as unsafe
                    pass

            # If we are absolutely certain no mounts remain → delete
            if safe_to_delete:
                shutil.rmtree(self._instance_dir, ignore_errors=True)
            else:
                print(
                    f"WARNING: skipping cleanup of {self._instance_dir} — mounts may still be active",
                    file=sys.stderr,
                )
            
    def _chroot_path(self, host_path: Path) -> str:
        try:
            rel = host_path.resolve().relative_to(self.component_path.resolve())
            return str(Path(WORKSPACE_PATH) / rel)
        except ValueError:
            return WORKSPACE_PATH


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _run(cmd: list[str], verbose: bool = False):
    if verbose:
        print(f"+ {' '.join(str(c) for c in cmd)}")
    subprocess.run([str(c) for c in cmd], check=True)
