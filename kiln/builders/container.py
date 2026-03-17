"""
kiln/builders/container.py

ContainerDef — assembles runtime artifacts into an OCI/podman container image
"""

from __future__ import annotations

from pathlib import Path

from kiln.builders.base import AssemblyDef


class ContainerDef(AssemblyDef):
    """
    Assembles dep runtime artifacts into an OCI/podman container image.
    TBD — subclass AssemblyDef when container support is needed.
    """

    def assemble_command(self, artifact_inputs: dict[str, Path],
                         output_dir: Path) -> None:
        raise NotImplementedError(
            f"{self.name}: ContainerDef.assemble_command not yet implemented"
        )
