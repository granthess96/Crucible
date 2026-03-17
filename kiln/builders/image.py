"""
kiln/builders/image.py

ImageDef — assembles runtime artifacts into a squashfs image
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar

from kiln.builders.base import AssemblyDef


class ImageDef(AssemblyDef):
    """
    Assembles dep runtime artifacts into a squashfs image.
    Subclasses declare deps and optionally override squashfs_args
    or post_install() for image-specific fixups.

    Output: <output_dir>/image.sqsh
    """

    squashfs_args: ClassVar[list[str]] = [
        "-comp", "zstd",
        "-noappend",
        "-force-uid", "0",
        "-force-gid", "0",
    ]

    def manifest_fields(self) -> dict[str, object]:
        fields = super().manifest_fields()
        fields.update({
            "kind":          "image",
            "squashfs_args": self.squashfs_args,
        })
        return fields

    def post_install(self, rootfs: Path) -> None:
        """
        Override to perform image-specific fixups after all runtime
        tarballs have been extracted but before mksquashfs runs.
        Examples: create symlinks, write /etc files, add device nodes.
        """
        pass

    def assemble_command(self, artifact_inputs: dict[str, Path],
                         output_dir: Path) -> None:
        rootfs = output_dir / "rootfs"
        rootfs.mkdir(parents=True, exist_ok=True)

        for name, artifact_dir in artifact_inputs.items():
            runtime = artifact_dir / f"{name}.runtime.tar.zst"
            if not runtime.exists():
                raise RuntimeError(
                    f"{name}: missing runtime tarball — "
                    f"was it built with kiln package?"
                )
            result = subprocess.run(
                ["tar", "--use-compress-program=zstd", "-xf", str(runtime),
                 "-C", str(rootfs)],
            )
            if result.returncode != 0:
                raise RuntimeError(f"{name}: failed to extract runtime tarball")

        self.post_install(rootfs)

        sqsh = output_dir / "image.sqsh"
        result = subprocess.run(
            ["mksquashfs", str(rootfs), str(sqsh)] + self.squashfs_args,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{self.name}: mksquashfs failed")
