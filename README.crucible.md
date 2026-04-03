# Crucible Orchestrator Tool


## Manifest / Change detection for tooling 
The following section is developed with ChatGPT as a design for a
deployment manifest generation / testing system.

The data is used in two ways:
1. Provide proof that the crucible toolset has not been accidentally modified
2. Provide manifest ready provenance for the toolset.

----

📘 Crucible Deployment & Provenance Model (CDM Design)
1. Overview

This document defines the Crucible Deployment Model (CDM) and the rules for validation, provenance tracking, and deployment behavior across the system.

The system is designed to ensure:

deterministic builds
accidental drift detection (not adversarial security)
reproducible deployments over long time horizons
a single authoritative source of truth for build validation
2. Core Principles
2.1 Single Authority Principle

Crucible is the only system component responsible for validation of build correctness and provenance consistency.

No other tool (kiln, cast, forge, etc.) may independently define or override build correctness.

2.2 Separation of Concerns

The system is divided into three conceptual layers:

Authority Layer → Crucible (validation, CDM generation)
Execution Layer → Kiln, Forge, Cast (deterministic operations)
Storage Layer → Coffer, Vault (non-authoritative persistence)
2.3 Drift Model Assumption

The system is designed to handle:

accidental drift
version mismatch
environment inconsistency

It is not designed for adversarial tampering resistance.

3. CDM (Crucible Deployment Metadata)

The CDM is the canonical record of system provenance and build validity.

There are two forms:

3.1 INSTALL CDM (System Authority)

Generated at installation / deployment time only

Location:

<install_root>/config/cdm.json
Purpose

Defines the immutable baseline of the installed system.

Contents
Git repository identity
Git commit hash
Canonical Python source tree hash (computed by Crucible)
Crucible version (global toolchain version)
Properties
Immutable after creation
Read-only in runtime
Used as the reference for drift detection
3.2 PROJECT CDM (Execution Snapshot)

Generated at every Crucible invocation

Location:

<project_root>/.crucible/cdm.json
Purpose

Represents the current execution context of a build or operation.

Contents
Reference to INSTALL CDM values
Runtime metadata (timestamp, mode, etc.)
Validation results for the current invocation
Observational data from execution
Properties
Regeneratable
Non-authoritative
Used by kiln, cast, and other execution tools
Must remain consistent with INSTALL CDM
4. CDM Field Rules (High-Level)
4.1 Authority Rule
INSTALL CDM defines canonical truth
PROJECT CDM must not redefine or override INSTALL CDM fields
4.2 Mutability Rule
Field Type	INSTALL CDM	PROJECT CDM
Source identity (git, hash)	Immutable	Copied / referenced
Python tree hash	Immutable	Must match exactly
Tool version (crucible)	Immutable	Copied
Runtime metadata	Not present	Mutable
4.3 Derived Fields Rule

PROJECT CDM may include additional derived fields such as:

timestamps
execution mode (dev / deploy)
validation status
runtime diagnostics

These fields must never affect install-level correctness.

5. Validation Model

Crucible performs validation by comparing PROJECT CDM against INSTALL CDM.

5.1 Validation Inputs
INSTALL CDM (authority baseline)
PROJECT CDM (current execution snapshot)
5.2 Validation Rules

A build is considered valid only if:

Python source tree hash matches
Git identity matches expected install state
Required toolchain version matches crucible version
No structural CDM corruption detected
6. Operating Modes

Crucible operates in two primary modes:

6.1 Development Mode
Behavior
Validation failures are non-fatal
Drift is reported as warnings
PROJECT CDM is always emitted when possible
Missing or incomplete metadata is tolerated
Purpose

Supports iterative development and testing of the build system itself.

6.2 Deployment Mode
Behavior
Full validation is enforced
Any mismatch between INSTALL CDM and PROJECT CDM results in failure
CDM must be fully valid and complete
Output is considered deployable only if validation passes
Purpose

Ensures strict reproducibility and system integrity for production artifacts.

7. Trust Boundaries
Crucible is the only authority for validation and CDM generation
Kiln, Cast, Forge:
may consume CDM
may extend runtime metadata
may NOT define or modify provenance truth
Coffer and Vault:
operate outside the provenance system
do not participate in validation logic
8. Summary

This system establishes a two-layer provenance model:

INSTALL CDM → immutable system baseline (source of truth)
PROJECT CDM → runtime execution snapshot (observational)

Crucible acts as the sole validator ensuring consistency between the two, enabling deterministic builds and long-term reproducibility while allowing safe development flexibility.


### Crucible CDM Schema (v1)
📘 Crucible CDM Schema (v1)
1. Design goals

This schema enforces:

single authority provenance (Crucible)
strict separation of install vs runtime state
read-only consumption by downstream tools
deterministic validation inputs
long-term reproducibility
🧱 2. Top-level schema structure

Both INSTALL and PROJECT CDM share the same top-level envelope:

{
  "cdm_version": "1.0",
  "cdm_type": "install | project",
  "install": {},
  "runtime": {},
  "validation": {}
}
🧠 3. INSTALL block (immutable authority anchor)

This block exists in BOTH CDMs, but is:

fully authoritative in INSTALL CDM
copied verbatim into PROJECT CDM (read-only mirror)
"install": {
  "git": {
    "repo_url": "string",
    "commit_hash": "string"
  },
  "source": {
    "python_tree_hash": "string"
  },
  "toolchain": {
    "crucible_version": "string"
  }
}
🔒 INSTALL invariants

These fields are:

immutable after generation
used as the sole validation anchor
must match exactly between INSTALL and PROJECT CDM
🧪 4. RUNTIME block (PROJECT CDM only meaningful content)

Only present in PROJECT CDM (or optionally empty in INSTALL CDM for schema symmetry).

"runtime": {
  "timestamp": "ISO-8601 string",
  "mode": "dev | deploy",
  "execution_id": "string",
  "environment": {
    "hostname": "string",
    "user": "string"
  }
}
🧪 RUNTIME rules
MAY vary per invocation
MUST NOT influence install-level correctness
IS safe for kiln/cast to consume
IS purely observational
🔍 5. VALIDATION block (PROJECT CDM only authoritative)

This block is:

computed by Crucible during runtime
informational in INSTALL CDM (usually empty or absent)
"validation": {
  "status": "pass | fail | unverified",
  "python_tree_match": true,
  "git_match": true,
  "toolchain_match": true,
  "mismatch_reasons": [
    "string"
  ]
}
🔐 VALIDATION rules
computed ONLY by Crucible
never written or modified by downstream tools
may be used by kiln/cast for behavior adaptation, but not correctness decisions
⚖️ 6. INSTALL vs PROJECT CDM formal distinction
🏗 INSTALL CDM
{
  "cdm_type": "install",
  "install": { ... },
  "runtime": {},
  "validation": {}
}
Meaning:

“This is the canonical installed system fingerprint”

🧪 PROJECT CDM
{
  "cdm_type": "project",
  "install": { ... copied exactly ... },
  "runtime": { ... varies ... },
  "validation": { ... computed ... }
}
Meaning:

“This is what the system observed during this execution, compared against install truth”

🔒 7. HARD CONSTRAINTS (schema-level invariants)

These are critical for preventing drift.

7.1 Install immutability rule
INSTALL CDM must never change after creation.
7.2 Install copy rule
PROJECT CDM.install MUST be an exact deep copy of INSTALL CDM.install.
7.3 Validation authority rule
Only Crucible may write the validation block.
7.4 Read-only consumption rule
Kiln, Cast, Forge:
- MAY read CDM
- MAY embed CDM into artifacts
- MUST NOT modify CDM on disk
🧠 8. How kiln/cast use this (important behavioral contract)

They are now pure consumers of truth.

Allowed behavior:
read INSTALL/CDM
read validation status
embed CDM into outputs
adjust behavior based on runtime.mode
Forbidden behavior:
recomputing hashes
interpreting git state
overriding validation
writing CDM files
🧊 9. Why this schema works well

This design gives you:

✔ Strong reproducibility anchor

INSTALL CDM is immutable

✔ Safe runtime variability

PROJECT CDM captures real execution

✔ Single validation authority

Crucible is the only evaluator

✔ No toolchain drift risk

No tool recomputes provenance

✔ Clean separation of concerns
install = truth
runtime = observation
validation = judgment

### Crucible Validation Specification (CDM v1)

📘 Crucible Validation Specification (CDM v1)
1. Purpose

Validation is the process by which Crucible determines whether a given execution context is:

consistent with the installed system (INSTALL CDM)
safe to proceed (dev or deploy mode dependent)

Validation produces a binary correctness decision + structured diagnostics.

🧭 2. Inputs to validation

Crucible validation takes exactly two inputs:

2.1 INSTALL CDM (authority baseline)
<install_root>/config/cdm.json

Represents:

immutable system state
canonical Python source hash
git identity
toolchain version
2.2 PROJECT CDM (runtime snapshot)
<project_root>/.crucible/cdm.json

Represents:

observed execution environment
runtime metadata
validation results (preliminary or partial)
⚙️ 3. Validation algorithm (canonical form)

Crucible executes validation in this exact order:

STEP 0 — Load CDMs
install = load_install_cdm()
project = load_project_cdm()

If either fails:

return fail
STEP 1 — Schema compatibility check
if install.cdm_version != project.cdm_version:
    fail("schema_version_mismatch")
STEP 2 — Install identity integrity check

These must match exactly:

if install.install.git.repo_url != project.install.git.repo_url:
    fail("git_repo_mismatch")

if install.install.git.commit_hash != project.install.git.commit_hash:
    fail("git_commit_mismatch")

if install.install.source.python_tree_hash != project.install.source.python_tree_hash:
    fail("python_tree_hash_mismatch")

if install.install.toolchain.crucible_version != project.install.toolchain.crucible_version:
    fail("toolchain_version_mismatch")
STEP 3 — Structural immutability check

Ensure INSTALL block has not been altered:

if hash(install.install) != hash(project.install):
    fail("install_block_tampered")

This is your anti-drift invariant.

STEP 4 — Runtime consistency check (non-fatal in dev)

Validate runtime expectations:

if project.runtime.mode not in ["dev", "deploy"]:
    fail("invalid_runtime_mode")

Optional checks:

timestamp present in project mode
execution_id present
environment fields valid if present
STEP 5 — Mode-dependent validation policy

This is where dev vs deploy diverges.

🧪 4. DEV MODE behavior

If:

project.runtime.mode == "dev"

Then:

On mismatch:
do NOT fail immediately
record diagnostic
set status = "unverified"
Output:
validation = {
  "status": "unverified",
  "errors": [...],
  "warnings": [...]
}
Exit code:
0 (success with warnings allowed)
🚀 5. DEPLOY MODE behavior

If:

project.runtime.mode == "deploy"

Then:

On ANY mismatch:
fail immediately
emit diagnostics
prevent artifact publication
Output:
validation = {
  "status": "fail",
  "errors": [...]
}
Exit code:
non-zero (hard failure)
🔐 6. Final validation decision function
function validate(install, project):

    run steps 0–4

    if any fatal error:
        return FAIL

    if mode == dev:
        return PASS_WITH_WARNINGS

    if mode == deploy:
        return PASS only if no errors
🧠 7. Key invariants (system truth rules)

These are the non-negotiable properties:

7.1 Install CDM immutability

INSTALL CDM must never change after creation.

If it does → system is invalid.

7.2 Single source of truth

All validation derives exclusively from INSTALL CDM + PROJECT CDM comparison.

No tool is allowed to recompute provenance independently.

7.3 Project CDM is observational only

PROJECT CDM cannot influence correctness decisions except via comparison.

7.4 Mode governs strictness, not truth
dev = relaxed enforcement
deploy = strict enforcement

But:

the underlying truth rules never change

🧩 8. Kiln / Cast interaction rule

They may:

read validation.status
adjust behavior (e.g. caching, optimization)
embed validation into artifacts

They may NOT:

override validation results
recompute install CDM fields
modify CDM on disk
⚠️ 9. Failure taxonomy (important for debugging later)

Validation failures fall into explicit categories:

Type	Meaning
schema_version_mismatch	incompatible CDM versions
git_repo_mismatch	wrong source repo
git_commit_mismatch	wrong build state
python_tree_hash_mismatch	code drift detected
toolchain_version_mismatch	environment drift
install_block_tampered	CDM corruption
invalid_runtime_mode	malformed execution context
📌 10. Summary

Crucible validation is:

a deterministic comparison engine between immutable install state and observed runtime state, with strict enforcement in deploy mode and observational tolerance in dev mode.