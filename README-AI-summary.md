Crucible is an internal software supply chain system focused on full provenance attestation. Every artifact is built from source in a hermetic, network-isolated environment and is identified by the hash of a manifest that describes all inputs, including source, dependencies, toolchain, and build environment.

The system is designed so that any artifact can be recursively traced back through its dependency manifests to fixed genesis records. Provenance is the primary identity model—artifacts without manifests are not considered to meaningfully exist.

Crucible orchestrates the process by monitoring upstream releases (not commits), selecting version wavefronts, and coordinating builds. Kiln handles dependency resolution and build execution, while Cast materializes resolved components into OCI images. All intermediate and final artifacts are stored in a content-addressable cache and then persisted in an immutable archive with both provenance and content addressing.

Correctness is defined as functional equivalence (validated via automated testing) plus provenance integrity. Bit-for-bit reproducibility is not required, but the full build process must be transparent and reproducible in terms of inputs and behavior.

The system prioritizes auditability, simplicity, and determinism over performance or flexibility. Failures—including build and integration failures—are preserved as first-class artifacts for analysis rather than discarded.
