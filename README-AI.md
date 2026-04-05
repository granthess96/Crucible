Crucible System – Deep Context Document (v0.1)
1. System Purpose

Crucible is an internal software supply chain system designed to produce fully provenance-attested software artifacts.

It ensures that every build artifact can be traced—not only to its source code—but to the complete toolchain and environment used to produce it, forming a recursively explorable chain back to defined genesis records.

The system prioritizes auditability, determinism of process, and provenance integrity over performance, flexibility, or ease of use.

2. Core Axioms
Manifest Identity is Canonical
The hash of a manifest.json defines the identity of an artifact.
An artifact without a manifest is not addressable and is considered non-existent.
Recursive Provenance is Required
Every manifest may reference other manifests, forming a complete, traversable chain back to genesis.
Vault is the Source of Truth
Vault stores all artifacts, manifests, and metadata under WORM constraints.
All audit operations resolve through Vault.

Functional Identity over Bitwise Identity
Correctness is defined as:

Passing functional and integration tests (via Anvil / Ledger / Aegis)
Matching declared provenance (source + toolchain + environment)

Bit-for-bit reproducibility is not required; functional equivalence is.

Everything is Built from Source
All upstream software, tooling, and environments are built from source within the system.
3. Genesis Trust Roots

Two axiomatic starting points exist:

Stage0 Forge image (constructed from Fedora 43 via dnf, with all packages recorded)
Crucible suite version 1.0

All subsequent artifacts must trace provenance back to one or both.

4. System Components
Orchestration
Crucible
Coordinates the system:
Monitors upstream releases (not commits)
Applies recipe-defined targets
Configures build and projection steps
Initiates testing workflows
Build System
Kiln
Owns build definitions and scripting
Resolves dependency DAGs
Provides:
ensure: materialize artifacts into Coffer
resolve: produce full dependency graph with manifest identities
Forge
Hermetic build environment:
unshare-based chroot
Read-only base image
Ephemeral overlay
Bind-mounted source
No network access
All inputs must be explicitly provided and provenance-tracked
Artifact Projection
Cast
Ensures all required components exist (via Kiln)
Resolves full dependency graph
Retrieves artifacts from Coffer
Projects them into OCI container layers
Emits final artifacts and associated metadata
Storage
Coffer
Content-addressable working set
Stores intermediate and reusable artifacts
Vault
Immutable long-term storage
Indexed by:
Manifest hash (provenance identity)
Artifact hash (content identity)
Stores:
Artifacts
Manifests
Build logs
Test results
Validation & Analysis
Anvil – executes test suites
Ledger – records results
Aegis – generates reports

Failures are preserved as first-class data.

5. Provenance Model
Each artifact is described by a manifest.json
The hash of the manifest is the artifact’s canonical identity

A manifest includes:

Source identity (git commit or tarball hash)
Applied patches
Toolchain components (Crucible, Kiln, Cast, etc.)
Forge base image hash
Dependency manifest hashes

This forms a recursive DAG:

Artifact → Manifest → Dependencies → Manifests → … → Genesis

6. Execution Model
Build Flow
Crucible detects upstream release
Applies recipe (defines required components, not DAG)
Configures Kiln with pinned versions
Cast:
ensure all components (via Kiln → Coffer)
resolve dependency graph
assembles OCI layers
Outputs stored in Vault
Testing executed via Anvil
Results recorded and linked via manifest chain
7. Policy Model
Recipes define what to build (component set)
Kiln defines how to build (scripts + dependency resolution)

Design direction:

Version selection will move to Crucible
Dependency modeling may also shift to Crucible
Kiln will remain responsible for execution logic
8. Failure Model

Failures are first-class artifacts.

Build failures (Kiln-level)
Tactical failures
Prevent artifact creation
Propagate upward
Projection failures (Cast-level)
May produce manifests with empty artifact hashes
Test failures (Anvil-level)
Strategic failures
High-value signals for integration and stability
Fully recorded and queryable

All failure modes are retained for audit and analysis.

9. Invariants
No network access within Forge
All inputs must be explicitly declared and pinned
All meaningful artifacts must have manifests
Vault is immutable (WORM)
Provenance must be recursively traceable
System favors transparency over abstraction
10. Definition of Correctness

A build is considered correct if:

It produces artifacts derived from fully declared and traceable provenance
It passes defined functional and integration tests

Correctness is not defined by bitwise reproducibility, but by:

Functional equivalence
Provenance integrity
