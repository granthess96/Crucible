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
import shutil
import subprocess
import tempfile
from pathlib import Path

from crucible.config import CrucibleConfig

INSTANCES_DIR  = "/opt/forge/instances"
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

    def __init__(self, config: CrucibleConfig, verbose: bool = False):
        self.config       = config
        self.verbose      = verbose
        self._instance_dir: Path | None = None
        self._merged:       Path | None = None
        self._mounted:      list[Path]  = []

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
            cmd_str    = ' '.join(str(c) for c in command)
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

        result = subprocess.run(chroot_cmd, check=False)
        return result.returncode

    def run_checked(self, command: list[str], cwd: Path | None = None):
        """Run command inside chroot, raise on non-zero exit."""
        rc = self.run(command, cwd)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, command)

    # --- Mount lifecycle ---

    def _setup(self):
        os.makedirs(INSTANCES_DIR, exist_ok=True)
        self._instance_dir = Path(tempfile.mkdtemp(
            dir=INSTANCES_DIR, prefix="forge-"
        ))

        base_mount  = self._instance_dir / "base"
        tools_mount = self._instance_dir / "tools"
        rw_dir      = self._instance_dir / "rw"
        self._merged = self._instance_dir / "merged"

        for d in (base_mount, tools_mount, rw_dir, self._merged):
            d.mkdir()

        base_sqsh  = self.config.base_image_path
        tools_sqsh = self.config.toolchain_path

        # Validate images exist before attempting mounts
        for img in (base_sqsh, tools_sqsh):
            if not img.exists():
                raise RuntimeError(
                    f"Image not found: {img}\n"
                    f"Check forge.toml [forge] settings or run 'forge --create'."
                )

        # 1. Base squashfs (read-only)
        _run(['mount', '-t', 'squashfs', '-o', 'loop,ro',
              str(base_sqsh), str(base_mount)], self.verbose)
        self._mounted.append(base_mount)

        # 2. Tools squashfs (read-only)
        _run(['mount', '-t', 'squashfs', '-o', 'loop,ro',
              str(tools_sqsh), str(tools_mount)], self.verbose)
        self._mounted.append(tools_mount)

        # 3. tmpfs — upper and work must be siblings on the same filesystem
        _run(['mount', '-t', 'tmpfs', 'tmpfs', str(rw_dir)], self.verbose)
        self._mounted.append(rw_dir)

        upper = rw_dir / "upper"
        work  = rw_dir / "work"
        upper.mkdir()
        work.mkdir()

        # 4. OverlayFS — tools over base, tmpfs as rw layer
        #    lowerdir: leftmost = highest priority
        lowerdir = f"{tools_mount}:{base_mount}"
        _run(['mount', '-t', 'overlay', 'overlay',
              '-o', f'lowerdir={lowerdir},upperdir={upper},workdir={work}',
              str(self._merged)], self.verbose)
        self._mounted.append(self._merged)

        # 5. proc and sys — fresh mounts (not bind)
        for stub in ('proc', 'sys', 'dev', WORKSPACE_PATH.lstrip('/')):
            (self._merged / stub).mkdir(exist_ok=True)

        _run(['mount', '-t', 'proc',  'proc',  str(self._merged / 'proc')],
             self.verbose)
        self._mounted.append(self._merged / 'proc')

        _run(['mount', '-t', 'sysfs', 'sysfs', str(self._merged / 'sys')],
             self.verbose)
        self._mounted.append(self._merged / 'sys')

        # 6. Dev nodes — written into upper layer via merged view
        create_dev_nodes(self._merged / 'dev')

        # 7. Project root → /workspace
        workspace = self._merged / WORKSPACE_PATH.lstrip('/')
        _run(['mount', '--bind',
              str(self.config.build_root), str(workspace)], self.verbose)
        self._mounted.append(workspace)

    def _teardown(self):
        """Unmount in reverse order. Best-effort — always runs."""
        for mount_point in reversed(self._mounted):
            subprocess.run(
                ['umount', str(mount_point)],
                check=False,
                capture_output=not self.verbose,
            )
        if self._instance_dir and self._instance_dir.exists():
            shutil.rmtree(self._instance_dir, ignore_errors=True)

    def _chroot_path(self, host_path: Path) -> str:
        """
        Translate a host-side path to its equivalent inside the chroot.
        host: <project_root>/components/zlib
        chroot: /workspace/components/zlib
        """
        try:
            rel = host_path.resolve().relative_to(
                self.config.build_root.resolve()
            )
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
