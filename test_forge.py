#!/usr/bin/env python3
import shutil
from pathlib import Path
from forge.instance import ForgeInstance
from crucible.config import CrucibleConfig

# ---------------------------
# Setup config for test
# ---------------------------
# Make sure these paths exist
config = CrucibleConfig(
    base_image_path=Path("base.sqsh"),
    toolchain_path=Path("tools.sqsh"),
    build_root=Path.cwd(),  # can be current directory
)

print("Starting ForgeInstance smoke test...")

with ForgeInstance(config, verbose=True) as instance:
    print(f"Merged overlay mounted at: {instance.merged}")

    # Run a simple command
    rc = instance.run(["ls", "/"])
    print(f"ls / returned: {rc}")

    rc = instance.run(["echo", "Hello from ForgeInstance!"])
    print(f"echo returned: {rc}")

print("ForgeInstance cleaned up successfully.")
