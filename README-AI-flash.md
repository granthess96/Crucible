Crucible is a provenance-first software supply chain system that rebuilds all artifacts from source in a hermetic environment and assigns identity based on a manifest hash describing the full build inputs (source, toolchain, and environment).

All artifacts are recursively traceable back to fixed genesis records, and correctness is defined by functional test validation plus provenance integrity—not bitwise reproducibility.

The system prioritizes auditability, determinism of process, and transparency over performance or convenience, and treats both successful and failed builds as first-class, queryable artifacts.
