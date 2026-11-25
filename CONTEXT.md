# Monarch Local Run

The language for running Monarch on one developer-controlled host while still
exercising real runtime behavior.

## Language

**Local Run**:
A single-host, developer-invoked execution path that exercises Monarch's real
runtime behavior without remote infrastructure.
_Avoid_: Local test, mock run, CI run

**Hermetic Rootfs**:
The bubblewrap-mounted filesystem used to run Monarch with a controlled Python,
glibc, compiler, CUDA, and Rust toolchain baseline.
_Avoid_: Sandbox, container, chroot

**Control-Plane Suite**:
The Python crash-recovery tests and Rust coordination tests that exercise host,
proc, and actor mesh behavior plus supervision on the local host.
_Avoid_: Integration tests, control tests

**Local Run Ladder**:
The standard validation sequence for a Local Run: environment, build,
unit-level smoke, integration, and failure classification.
_Avoid_: Test stages, validation steps

**Capacity Verifier**:
A local run that proves a host satisfies a specific Monarch runtime capacity,
such as exercising all eight local GPUs through the tensor engine.
_Avoid_: Smoke test, benchmark

**8-GPU Capacity Verifier**:
The Capacity Verifier that proves all eight local GPUs are visible to Monarch
and shardable through the tensor engine; it is not a performance benchmark.
_Avoid_: 8-GPU benchmark, capacity benchmark

**Tensor-Engine Smoke**:
The unit-level runtime check that requires the tensor engine, verifies visible
CUDA devices, spawns a local proc mesh, and fetches one shard rank per GPU.
_Avoid_: CUDA check, GPU smoke

**Contract Artifact**:
An output file whose presence and contents are part of a Local Run's validation
contract rather than an incidental build cache or log.
_Avoid_: Result file, output artifact

**Failure Classification**:
The verifier stage that decides whether a failed full-suite run is a real
capacity failure or a known suite-ordering issue; unknown or unmappable results
are failures, not accepted states.
_Avoid_: Failure handling, retry logic

**Suite-Ordering Fragility**:
A full-suite Python failure caused by shared cross-test state that passes when
the same pytest node is rerun in isolation inside the same Hermetic Rootfs.
_Avoid_: Flake, known failure

**Workload Plane**:
A thin, workload-specific library over the shared coordination core that owns one
class of work — training, serving, or data analysis — supplying only its actor
topology, health signal, and reallocation-policy callback.
_Avoid_: Control plane, service, subsystem

**Placement**:
The single decision that maps a workload's requested actors onto host, proc, and
actor meshes, shared by all Workload Planes; training gang-schedules a worker
group, serving sizes replica pools, analysis places partitions.
_Avoid_: Scheduling, allocation, binpacking

**Reallocation Policy**:
The callback a Workload Plane registers in place of the default fail-fast
`unhandled_fault_hook`, deciding what a `MeshFailure` does — resume from
checkpoint, replace a replica, or re-execute a stage — instead of exiting.
_Avoid_: Retry, fault handler, recovery hook

**Control Store**:
The durable record of workload specs and current placement that lets a
control-actor restart re-attach to running work rather than restart it from zero.
_Avoid_: Database, state cache, metadata store
