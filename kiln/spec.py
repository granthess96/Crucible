"""
kiln/spec.py
FileSpec — explicit role annotation for files that path inference gets wrong.

Default behaviour: every file under __install__/ gets a role assigned by
path_role() in kiln/verbs/packaging.py.  FileSpec is only needed for the
three exception cases:

  1. The path heuristic would infer the wrong role.
  2. The file needs a non-obvious role (e.g. a .so that is 'dev'-only).
  3. The file should be excluded from the package entirely (role='exclude').

Globs use pathlib.PurePosixPath.full_match() semantics:
  *   matches any single name segment (no separator crossing)
  **  matches zero or more segments (crosses separators)

All paths are relative to __install__/ (no leading slash).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Role = Literal['runtime', 'tool', 'dev', 'doc', 'config', 'debug', 'exclude']

@dataclass(frozen=True)
class FileSpec:
    path: str   # glob ok: usr/lib/libfoo.so*
    role: Role
