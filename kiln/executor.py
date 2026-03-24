"""
kiln/executor.py
Forge execution primitives shared by all build verbs.
Handles subprocess dispatch into the forge environment,
script generation, and builder instantiation helpers.
"""
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
_here = Path(__file__).parent.parent
# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------
def get_builder(target: str, config):
    """
    Load component registry and instantiate the builder for target.
    Returns (registry, instance) on success, (None, None) on failure
    with error already printed.
    """
    from kiln.registry import ComponentRegistry, RegistryError
    try:
        reg = ComponentRegistry(config.components_dir)
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None, None
    if target not in reg:
        print(f"ERROR: component '{target}' not found", file=sys.stderr)
        return None, None
    return reg, reg.instantiate(target)


def check_sentinel(config, target: str, sentinel: str, missing_verb: str) -> bool:
    """Return True if sentinel file exists, print clear error if not."""
    sentinel_file = config.build_root / ".kiln" / "state" / target / sentinel
    if not sentinel_file.exists():
        print(
            f"ERROR: {target} has not been {sentinel.replace('_', ' ')}.\n"
            f"       Run 'kiln {missing_verb}' first.",
            file=sys.stderr,
        )
        return False
    return True


def resolve_verb(instance, verb: str, paths):
    """
    Return (script_body_or_None, cmd_or_None) for a given verb.
    Script takes precedence -- command_method is never called if script is set.
    """
    script_method = getattr(instance, f"{verb}_script", None)
    script        = script_method(paths) if script_method else None
    if script:
        return script, []
    command_method = getattr(instance, f"{verb}_command", None)
    cmd            = command_method(paths) if command_method else []
    return None, cmd


# ---------------------------------------------------------------------------
# Forge execution
# ---------------------------------------------------------------------------
def forge_run(config, target: str, cmd: list[str],
              reporter, status,
              cwd: Path | None = None,
              extra_env: dict[str, str] | None = None) -> bool:
    """
    Run cmd inside a forge environment via the forge CLI subprocess.
    forge handles its own unshare -- kiln stays in user context throughout.
    extra_env: additional environment variables merged into the forge env.
    Returns True on success.
    """
    reporter.update(target, status)
    effective_cwd = cwd or config.components_dir / target

    env = os.environ.copy()
    env['PYTHONPATH'] = str(_here)
    if extra_env:
        env.update(extra_env)

    forge_cmd = [
        sys.executable, '-m', 'forge',
        '--cwd', str(effective_cwd),
        '--',
    ] + [str(c) for c in cmd]

    try:
        result = subprocess.run(forge_cmd, check=False, env=env)
        if result.returncode != 0:
            reporter.update(target, status.__class__.ERROR)
            print(f"ERROR: {target}: command exited {result.returncode}",
                  file=sys.stderr)
            return False
        return True
    except FileNotFoundError:
        reporter.update(target, status.__class__.ERROR)
        print(f"ERROR: forge not found -- is it installed?", file=sys.stderr)
        return False
    except Exception as exc:
        reporter.update(target, status.__class__.ERROR)
        print(f"ERROR: forge failed for {target}: {exc}", file=sys.stderr)
        return False


def forge_run_script(config, target: str, script_body: str,
                     verb: str, reporter, status,
                     cwd: Path | None = None,
                     extra_env: dict[str, str] | None = None) -> bool:
    """
    Write script_body to __build__/kiln-<verb>.sh on the host,
    then run it inside forge via the forge CLI subprocess.
    extra_env: additional environment variables merged into the forge env.
    """
    from kiln.builders.base import BuildPaths

    build_dir   = config.components_dir / target / "__build__"
    script_path = build_dir / f"kiln-{verb}.sh"

    full_script = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + script_body
    script_path.write_text(full_script, encoding="utf-8")
    script_path.chmod(0o755)

    paths         = BuildPaths.for_component(target)
    chroot_script = f"{paths.build}/kiln-{verb}.sh"

    effective_cwd = cwd or build_dir

    env = os.environ.copy()
    env['PYTHONPATH'] = str(_here)
    if extra_env:
        env.update(extra_env)

    forge_cmd = [
        sys.executable, '-m', 'forge',
        '--cwd', str(effective_cwd),
        '--', 'bash', chroot_script,
    ]

    reporter.update(target, status)
    try:
        result = subprocess.run(forge_cmd, check=False, env=env)
        if result.returncode != 0:
            reporter.update(target, status.__class__.ERROR)
            print(
                f"ERROR: {target}: script exited {result.returncode}\n"
                f"       Script left at: {script_path}",
                file=sys.stderr,
            )
            return False
        return True
    except FileNotFoundError:
        reporter.update(target, status.__class__.ERROR)
        print(f"ERROR: forge not found -- is it installed?", file=sys.stderr)
        return False
    except Exception as exc:
        reporter.update(target, status.__class__.ERROR)
        print(f"ERROR: forge failed for {target}: {exc}", file=sys.stderr)
        return False