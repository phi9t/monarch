# Accept Python isolation reruns for local run classification

The 8-GPU Capacity Verifier may convert a failed Python full-suite result into
an accepted Local Run only when Rust nextest is green, every failed or errored
pytest node ID is parsed from JUnit, and every one passes in isolation inside
the same Hermetic Rootfs. This preserves signal from the crash-recovery suite
without treating known cross-test state leaks as tensor-engine or 8-GPU capacity
failures.
