"""
kiln/verbs/build.py
Build verbs: configure, build, test, install.
All four follow the same pattern:
  - load builder instance
  - resolve script or command
  - run inside forge
"""
from __future__ import annotations
import sys
from pathlib import Path
from kiln.output import Reporter, Status
from kiln.executor import get_builder, resolve_verb
from kiln.executor import forge_run, forge_run_script


def verb_configure(target: str, config, reporter: Reporter) -> bool:
    """Run build system configure step inside forge."""
    from kiln.builders.base import BuildPaths

    reg, instance = get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = resolve_verb(instance, "configure", paths)
    build_dir   = config.components_dir / target / "__build__"
    extra_env   = instance._resolve_env(paths)

    if script:
        ok = forge_run_script(config, target, script, "configure",
                              reporter, Status.CONFIG, cwd=build_dir,
                              extra_env=extra_env)
    elif cmd:
        ok = forge_run(config, target, cmd, reporter, Status.CONFIG,
                       cwd=build_dir, extra_env=extra_env)
    else:
        print(f"  {target}: no configure step -- skipping")
        reporter.update(target, Status.OK)
        return True

    if ok:
        reporter.update(target, Status.OK)
    return ok


def verb_build(target: str, config, reporter: Reporter) -> bool:
    """Compile inside forge."""
    from kiln.builders.base import BuildPaths

    reg, instance = get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = resolve_verb(instance, "build", paths)
    build_dir   = config.components_dir / target / "__build__"
    extra_env   = instance._resolve_env(paths)

    if script:
        ok = forge_run_script(config, target, script, "build",
                              reporter, Status.BUILD, cwd=build_dir,
                              extra_env=extra_env)
    elif cmd:
        ok = forge_run(config, target, cmd, reporter, Status.BUILD,
                       cwd=build_dir, extra_env=extra_env)
    else:
        print(f"  {target}: no build step -- skipping")
        reporter.update(target, Status.OK)
        return True

    if ok:
        reporter.update(target, Status.OK)
    return ok


def verb_test(target: str, config, reporter: Reporter) -> bool:
    """Run test suite inside forge."""
    from kiln.builders.base import BuildPaths

    reg, instance = get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = resolve_verb(instance, "test", paths)
    build_dir   = config.components_dir / target / "__build__"
    extra_env   = instance._resolve_env(paths)

    if script:
        ok = forge_run_script(config, target, script, "test",
                              reporter, Status.TEST, cwd=build_dir,
                              extra_env=extra_env)
    elif cmd:
        ok = forge_run(config, target, cmd, reporter, Status.TEST,
                       cwd=build_dir, extra_env=extra_env)
    else:
        print(f"  {target}: no test suite defined -- skipping")
        reporter.update(target, Status.OK)
        return True

    if ok:
        reporter.update(target, Status.OK)
    return ok


def verb_install(target: str, config, reporter: Reporter) -> bool:
    """DESTDIR install into __install__/ inside forge."""
    from kiln.builders.base import BuildPaths

    reg, instance = get_builder(target, config)
    if instance is None:
        return False

    paths       = BuildPaths.for_component(target)
    script, cmd = resolve_verb(instance, "install", paths)
    build_dir   = config.components_dir / target / "__build__"
    extra_env   = instance._resolve_env(paths)

    if script:
        ok = forge_run_script(config, target, script, "install",
                              reporter, Status.INSTALL, cwd=build_dir,
                              extra_env=extra_env)
    elif cmd:
        ok = forge_run(config, target, cmd, reporter, Status.INSTALL,
                       cwd=build_dir, extra_env=extra_env)
    else:
        print(f"  {target}: no install step -- skipping")
        reporter.update(target, Status.OK)
        return True

    if ok:
        reporter.update(target, Status.OK)
    return ok