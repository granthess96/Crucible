"""
kiln/manifest.py
Canonical manifest generation and hashing.

A manifest is a deterministic text representation of every input that could
affect a build's output.  SHA256(manifest.txt) is the cache/registry address.

Rules for canonical format (violating these breaks cache correctness):
  - Fields in a fixed defined order (component type defines the order)
  - One "key: value" per line, UTF-8, Unix line endings
  - Lists are emitted one item per line, indented 2 spaces
  - Empty lists are omitted entirely
  - None values are omitted entirely
  - No trailing whitespace
  - Exactly one trailing newline
  - String values are stripped of leading/trailing whitespace
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Canonical serialisation
# ---------------------------------------------------------------------------

def _serialise_value(value: Any) -> list[str]:
    """
    Convert a single field value to one or more output lines (without the key).
    Returns [] if the value should be omitted.
    """
    if value is None:
        return []
    if isinstance(value, bool):
        return ["true" if value else "false"]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, (list, tuple)):
        items = [str(i).strip() for i in value if str(i).strip()]
        return items   # caller handles multi-line formatting
    if isinstance(value, dict):
        lines = []
        for k, v in sorted(value.items()):
            sub = _serialise_value(v)
            if sub:
                lines.append(f"{k}: {sub[0]}")
        return lines
    return [str(value).strip()]


def render_manifest(fields: dict[str, Any]) -> str:
    """
    Render a fields dict to canonical manifest text.
    fields must already be in the correct order (use an ordered dict or
    pass fields from manifest_fields() which guarantees order).
    """
    lines: list[str] = []
    for key, value in fields.items():
        serialised = _serialise_value(value)
        if not serialised:
            continue
        if isinstance(value, (list, tuple)) and len(serialised) > 1:
            lines.append(f"{key}:")
            for item in serialised:
                lines.append(f"  {item}")
        elif isinstance(value, (list, tuple)) and len(serialised) == 1:
            lines.append(f"{key}: {serialised[0]}")
        else:
            lines.append(f"{key}: {serialised[0]}")
    return "\n".join(lines) + "\n"


def hash_manifest(manifest_text: str) -> str:
    """Return the SHA256 hex digest of the canonical manifest text."""
    return hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Manifest dataclass — carries both the text and the hash
# ---------------------------------------------------------------------------

@dataclass
class Manifest:
    component:     str
    version:       str
    fields:        dict[str, Any]
    text:          str = field(init=False)
    hash:          str = field(init=False)

    # Resolver-populated fields — exactly one of source_commit or source_sha256
    # will be set for any given component, depending on source type.
    source_commit:  str | None = None    # git: resolved commit SHA from kiln.lock
    source_sha256:  str | None = None    # tarball: sha256 from kiln.lock
    builder_hash:   str | None = None    # SHA256 of the build.py file itself
    patches_hash:   str | None = None    # SHA256 of the patches/ dir tree (if any)
    forge_base:     str | None = None    # registry hash of forge base image
    bootstrap_stage: str | None = None   # bootstrap environment stage (stage0, stage1, etc.)

    def __post_init__(self):
        self._finalise()

    def _finalise(self):
        """Render text and compute hash from current field state."""
        resolved = dict(self.fields)

        # Source identity — only one will be set per component
        if self.source_commit:
            resolved["source_commit"] = self.source_commit
        if self.source_sha256:
            resolved["source_sha256"] = self.source_sha256

        if self.builder_hash:
            resolved["builder_hash"]  = self.builder_hash
        if self.patches_hash:
            resolved["patches_hash"]  = self.patches_hash
        if self.forge_base:
            resolved["forge_base"]    = self.forge_base
        if self.bootstrap_stage:
            resolved["bootstrap_stage"] = self.bootstrap_stage

        self.text = render_manifest(resolved)
        self.hash = hash_manifest(self.text)

    def with_resolved(
        self,
        source_commit:  str | None = None,
        source_sha256:  str | None = None,
        builder_hash:   str | None = None,
        patches_hash:   str | None = None,
        forge_base:     str | None = None,
        bootstrap_stage: str | None = None,
    ) -> "Manifest":
        """
        Return a new Manifest with resolver-populated fields added.
        The hash changes when any of these are set — that is intentional.
        Exactly one of source_commit / source_sha256 should be provided.
        """
        return Manifest(
            component       = self.component,
            version         = self.version,
            fields          = self.fields,
            source_commit   = source_commit or self.source_commit,
            source_sha256   = source_sha256 or self.source_sha256,
            builder_hash    = builder_hash  or self.builder_hash,
            patches_hash    = patches_hash  or self.patches_hash,
            forge_base      = forge_base    or self.forge_base,
            bootstrap_stage = bootstrap_stage or self.bootstrap_stage,
        )

    def write(self, path: Path) -> None:
        """Write canonical manifest text to path."""
        path.write_text(self.text, encoding="utf-8")

    def __repr__(self) -> str:
        return f"<Manifest {self.component}=={self.version} sha256:{self.hash[:12]}>"


# ---------------------------------------------------------------------------
# Helpers for hashing filesystem content (used by resolver)
# ---------------------------------------------------------------------------

def hash_file(path: Path) -> str:
    """SHA256 of a single file's contents."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_directory_tree(path: Path) -> str:
    """
    Deterministic SHA256 of a directory tree.
    Hashes file paths (relative) and contents in sorted order.
    Used for patches/ directory and build.py hashing.
    """
    h = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_file():
            rel = child.relative_to(path)
            h.update(str(rel).encode("utf-8"))
            h.update(hash_file(child).encode("utf-8"))
    return h.hexdigest()