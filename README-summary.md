Crucible Compute Software Lifecycle Platform – Project Summary

The Crucible Compute Software Lifecycle platform is designed to ensure the stability, reproducibility, and auditability of the ROCm software stack. Its primary focus is provenance tracking: every build and test is fully traceable, capturing the exact sources, dependencies, toolchains, and base images used, enabling deterministic builds and rigorous software lifecycle management.

Platform Workflow

Change Detection and Build Trigger (Crucible)
Crucible monitors upstream sources for new releases. When a change is detected, it generates build definitions for affected components and triggers the build process.

Provenance-Aware Builds (Kiln & Forge)
Kiln performs dependency analysis using a DAG to determine which components require rebuilding. Each component is built in Forge, a hermetic environment with pinned base images and toolchains. This ensures that builds are reproducible and isolated from external variability.

Artifact Storage and Versioning (Coffer & Vault)
Individual component artifacts are stored in Coffer and versioned by provenance hash, guaranteeing that the same inputs always produce the same outputs. Vault serves as a WORM container and image store, archiving images, manifests, deployed file lists, and build logs for auditability.

Test Orchestration and Data Capture (Anvil & Ledger)
Anvil deploys the operating system onto test fixtures and assembles the containers under test along with their test harnesses. Ledger captures test logs and telemetry, supporting long-running tests of up to 72 hours, and providing comprehensive insight into system behavior.

Reporting and Audit (Aegis)
Aegis generates detailed test reports using telemetry from Ledger and metadata from Vault, enabling fully auditable review of the build and test lifecycle.

Key Benefits

Provenance and Reproducibility: Every build can be traced to its exact sources, dependencies, and toolchain, ensuring determinism across the ROCm stack.

Auditability: Purpose-built in-house to avoid the opacity and feature bloat of third-party or open-source CI tools.

Reliability and Rigor: Addresses ABI drift, unrigorous build processes, and unnecessary container bloat, supporting weekly builds with multi-day test cycles to ensure stability over time.

Efficiency: Builds and tests are managed intelligently, rebuilding only what is necessary based on dependency analysis, while caching intermediate artifacts for speed.

By integrating these components, Crucible Compute delivers a deterministic, auditable, and highly reliable software lifecycle platform for the ROCm ecosystem, ensuring both developer confidence and downstream stability.
