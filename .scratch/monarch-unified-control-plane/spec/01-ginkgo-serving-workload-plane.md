# Spec: Ginkgo serving as a Job-owned Workload Plane

Status: approved design; written-spec review pending (2026-09-08)
Parent: ../map.md
Resolves: ../issues/02-actor-control-evidence-gap.md
Builds on: 00-shared-substrate.md and
`docs/adr/0003-shared-core-three-thin-planes.md`

## Goal

Join Ginkgo's first serving vertical slice to Monarch's shared coordination
core. `JobTrait` remains the authoritative lifecycle interface. Ginkgo supplies
serving topology, health, and a Reallocation Policy; a shared implementation
owns Placement, durable state transitions, supervision routing, replacement,
and reattachment.

The first slice is CPU-local and proves real behavior on an actor mesh without
requiring SGLang performance or a GPU. Existing Ginkgo command lines and
Contract Artifact schemas remain usable, but all launchers call one runtime
path.

This is a gated change: it adds a public JobTrait interface, replaces a durable
record schema, and changes supervision and external-process lifecycle
semantics. Implementation is limited to the blocker-linked tickets below. It
does not authorize a GPU run, a Git commit, a push, a pull request, or deletion
of user data.

## Non-goals

- GPU serving, throughput, latency, or model-quality qualification.
- Dynamo, Responses, benchmark, or evaluation topology.
- Multi-host Placement or multi-tenant resource arbitration.
- Training and data-analysis Workload Plane implementations.
- Compatibility for `ControlPlaneCoordinator`, `GinkgoControlPlaneActor`, or
  their prepare/launch/probe/teardown interface.
- A general scheduler, event bus, or pluggable Placement algorithm.

## External interface

The caller configures one Workload Plane after constructing a job, following
the existing telemetry/admin idiom, then enters the existing `state()`
lifecycle:

```python
job = LocalJob().enable_workload(
    GinkgoServingWorkload(
        run=run,
        local_environment=local_environment,
    )
)

state = job.state()
serving = state.workload
try:
    print(serving.status().outputs["openai_base_url"])
finally:
    serving.close()
```

`job.kill()` also closes the workload before releasing the job allocation.
There is no caller-selected start-versus-attach mode: `state()` reconciles the
declared workload with durable and live state. `JobTrait.__init__()` remains
argument-free.

The first slice permits exactly one configured Workload Plane. A second
`enable_workload()` call is a configuration error. Supporting multiple
workloads in one job is deferred until a real caller requires it.

`JobState.workload` is `None` when no Workload Plane is configured; otherwise,
it is a `WorkloadHandle` with two operations:

```python
class WorkloadHandle:
    def status(self) -> WorkloadStatus: ...
    def close(self) -> WorkloadResult: ...
```

`state()` returns only after the workload is healthy. `status()` reports the
latest durable generation, Placement, health, outputs, Contract Artifacts, and
terminal error. `close()` is idempotent, performs owned teardown, verifies
Ginkgo's closed-port contract, and persists the terminal result.

## Workload Plane interface

The shared module defines the integration interface used by Ginkgo. Ordinary
callers construct `GinkgoServingWorkload`; they do not drive this interface
directly.

```python
class WorkloadPlane(Protocol):
    def declaration(self) -> WorkloadDeclaration: ...
    def topology(self) -> WorkloadTopology: ...
    def health(self, runtime: RuntimeView) -> Health: ...
    def on_failure(self, failure: FailureContext) -> Decision: ...
```

`WorkloadDeclaration` is JSON-safe and immutable for one `workload_id`. It
contains:

- `workload_id`, equal to Ginkgo's existing `run_id`;
- a plane name and schema version;
- portable declared-config and local-environment references;
- a resource demand and maximum reallocation count; and
- a digest over every immutable field.

Ginkgo run IDs are unique execution identities. Reusing a run ID for a new
allocation is a declaration conflict, even when the portable configuration is
otherwise identical.

`WorkloadTopology` owns plane-specific process and actor operations:

```python
class WorkloadTopology(Protocol):
    def start(self, context: RuntimeContext) -> RuntimeAttachment: ...
    def attach(
        self, context: RuntimeContext, recorded: RuntimeAttachment
    ) -> RuntimeAttachment: ...
    def replace(
        self,
        context: RuntimeContext,
        current: RuntimeAttachment,
        target: ReplicaKey,
    ) -> RuntimeAttachment: ...
    def stop(
        self, context: RuntimeContext, current: RuntimeAttachment
    ) -> WorkloadResult: ...
```

These methods express Ginkgo's ownership of serving topology without giving it
the coordination state machine. The shared reconciler decides which method may
run, records intent before side effects, checks ownership, runs health, and
commits the result.

For this serving slice, `Decision` is `Replace(ReplicaKey)` or
`Escalate(reason)`. The existing training- and analysis-named variants remain
out of the runtime path until those planes exist. Retry accounting is durable
shared state, not mutable state inside the callback.

## Shared implementation

A private `CoordinationComponent` joins the existing `JobComponents` phase
ordering. It has high depth: callers and Ginkgo do not see Placement calls,
Control Store transactions, revisions, generations, fault-route leases, mesh
membership refreshes, or restart ordering.

It owns a per-workload reconciler and three internal dependency interfaces:

- `WorkloadStatePort`: load and compare-and-swap a workload record. The
  production adapter is the filesystem Control Store; tests use an in-memory
  adapter. This dependency is local-substitutable.
- `MeshRuntimePort`: observe host capacity, materialize or reattach mesh
  identities, and install a supervised workload controller. The production
  adapter is Monarch actor/mesh machinery; tests use the in-process actor
  runtime. This dependency is remote but owned.
- `FaultSourcePort`: register exact current-generation ownership routes and
  serialize delivered failures. The production adapter is Monarch
  supervision; tests use a deterministic source. This dependency is remote but
  owned.

SGLang, HTTP probes, and Insula remain true external dependencies behind
Ginkgo's `WorkloadTopology`. Insula stays the only implementation that builds
or executes bwrap plans.

Placement remains an in-process decision, and record transitions remain
in-process logic. They do not gain interfaces until a second implementation
exists.

## CPU process Placement correction

The current substrate treats a CPU actor as if it consumed one synthetic GPU
ordinal because `MeshPlan` forbids an empty GPU list. That cannot prove a
CPU-local serving path.

The resource model must represent non-GPU processes directly:

```python
@dataclass(frozen=True)
class ResourceRequest:
    processes_per_actor: int = 1
    gpus_per_actor: int = 0

@dataclass(frozen=True)
class RankPlacement:
    host_mesh: str
    rank: int
    gpu_ids: tuple[int, ...]
```

A CPU-local rank owns one unreserved process and may own zero GPUs. A GPU rank
owns the requested distinct GPU ordinals. `MeshPlan` validates the request that
created it and produces `per_host={"processes": N}` for non-GPU actors or the
appropriate GPU process shape for GPU actors. The first slice proves process
cardinality, not exclusive CPU-core reservation or non-overlap. Explicit CPU
affinity through `proc_bind` is deferred. Infeasible or mixed requests fail
loudly; there is no implicit GPU token or degraded plan.

## Durable record

Replace the Control Store's arbitrary `spec` and `placement` mappings with a
versioned `WorkloadRecord` containing:

- `workload_id` and current `allocation_id` (`JobTrait.apply_id`);
- immutable declaration digest and portable declaration;
- monotonic compare-and-swap revision;
- lifecycle phase;
- Placement generation and logical replica assignments;
- JSON-safe actor/process ownership identities and ProcessRecord references;
- reallocation budget and consumed count;
- health, outputs, and Contract Artifact references; and
- last failure and secondary teardown errors.

The record is keyed by `workload_id`. Reattachment requires both the declaration
digest and `allocation_id` to match. A record from another allocation is a
conflict, not permission to adopt or overwrite it.

Lifecycle phases are:

```text
declared -> planned -> starting -> running
                                -> failed
running  -> recovering -> running (next generation)
running  -> stopping -> stopped
```

Every state-changing side effect is preceded by a durable intent phase and
followed by a compare-and-swap commit. A revision conflict fails loudly so two
clients cannot both launch or replace the same workload.

The filesystem adapter enforces those claims with one exclusive lock file per
workload. The active controller holds the lease and is the sole writer and
failure-route owner. Fresh client handles are observers: they attach to the
deterministic live controller, but do not acquire the lease, install routes, or
mutate the record. A new writer can acquire the lease only after the old owner
releases it or dies; controller-owner handoff is not part of this slice.
Acquiring a writer lease increments a durable fencing epoch. Every later
compare-and-swap requires both the expected revision and epoch. Record writes
use a unique temporary name, fsync the file, replace atomically, and fsync the
parent directory.

Crash recovery is phase-specific:

- `declared` or `planned`: planning may continue because no runtime side effect
  has begun.
- `starting`: attach only if the deterministic operation ID has a matching live
  ProcessRecord; otherwise persist an ownership failure and stop. Never launch
  again from this phase.
- `running`: attach to the exact recorded runtime and re-run health.
- `recovering`: attach only to the recorded replacement operation and expected
  next generation; missing evidence is terminal.
- `stopping`: resume idempotent owned teardown and closed-port verification.
- `failed` or `stopped`: return the terminal result; never restart implicitly.

The topology writes deterministic ownership intent before starting an external
process. If a process exists without a matching ProcessRecord, the reconciler
cannot prove ownership and fails loudly rather than risking a duplicate.

## Start and reattachment

On first `state()`:

1. `JobTrait` applies or reconnects the job and materializes final host meshes.
2. The reconciler validates the declaration and writes `declared`.
3. It observes current CPU/host capacity, computes Placement, and writes
   `planned` then `starting`.
4. The shared implementation starts the supervised workload-controller actor
   and registers the deterministic identities expected for generation zero.
   The controller then asks Ginkgo's topology to start its actor/process
   identities through Monarch and Insula.
5. The reconciler persists the returned attachment, replaces the expected
   routes with exact generation-scoped ownership routes, and runs Ginkgo
   health.
6. It commits `running` and exposes `JobState.workload`.

On a fresh client handle:

1. The same live `JobTrait` allocation and host meshes remain active; the test
   discards its local `WorkloadHandle` and CoordinationComponent runtime handle.
2. The new observer loads the record by `workload_id`, asserts the unchanged
   `JobTrait.apply_id`, and verifies allocation,
   declaration digest, phase, and current mesh membership.
3. It resolves the recorded deterministic workload-controller identity in the
   existing actor system and asks that controller to validate its current
   ProcessRecord ownership and health.
4. It returns an observer `WorkloadHandle` for the same controller and
   generation. The live controller retains its writer lease and existing fault
   routes throughout.

Missing identities, stale generations, mismatched configuration, ambiguous
ownership, or unhealthy attached work raises `ReattachmentError`. Reattachment
never calls `start()` and never silently replaces the whole workload.

This slice proves attachment of a fresh client handle to an existing live
controller inside the same live JobTrait allocation. It does not
claim that a fresh OS process can reconnect a `LocalJob`: `LocalJob.can_run()`
currently rejects its pickle cache. It also does not promise that an actor's
owned child meshes survive the fatal loss of their supervision parent. Those
broader restart guarantees require a scheduler-backed allocation or a separate
LocalJob attachment design; if ownership itself is gone, reattachment fails
loudly.

## Failure replacement

A private supervised workload-controller actor owns the current serving
topology. Its `__supervise__` handles only failures whose stored actor,
reporting-controller, crashed-rank, mesh, and generation identity match exactly.

Rust already carries `event.actor_id`, `crashed_ranks`, and
`reporting_controller`, but Python's `MeshFailure` exposes only `mesh_name` and
a prose report. Before replacement is enabled, the Python binding adds typed
read-only access to the subject actor, crashed ranks, optional reporting
controller, and optional actor-mesh name. The existing string `mesh_name`
property may remain for compatibility, but the Workload Plane router never uses
its `"<none>"` sentinel as an identity.

1. The controller serializes a known failure and persists it with the consumed
   reallocation count.
2. The Reallocation Policy returns `Replace(ReplicaKey)` or `Escalate`.
3. For replacement, the reconciler refreshes current membership, computes
   Placement, and persists `recovering` before acting.
4. Ginkgo replaces only the named replica, returns new ownership evidence, and
   passes health.
5. The reconciler commits the next generation as `running` and replaces the
   fault routes atomically.

One structured failure must map to exactly one stored replica in the current
generation. `None`, a whole-mesh event, multiple crashed ranks, an unknown
subject/controller, a stale generation, or an ambiguous mapping is not eligible
for replica replacement. The current `default_rank` fallback is removed. Such
failures return unhandled and reach Monarch's existing fail-fast root behavior.
Policy exceptions, an exhausted budget, replacement failure, and failed health
persist `failed` before escalating. Cleanup errors supplement rather than
replace the primary error.

The implementation must not replace the process-global
`monarch.actor.unhandled_fault_hook`.

## Ginkgo migration

`ControlPlaneCoordinator` and `GinkgoControlPlaneActor` currently duplicate
lifecycle state and leave Placement, Control Store, and Reallocation Policy
outside production serving. Replace them with `GinkgoServingWorkload` and one
topology implementation over the existing Ginkgo/Insula launch and probe code.

`SglangLocalRun.run()` currently launches, probes, tears down, and only then
returns. The topology cannot adapt that completed result into a live workload.
It first extracts a stateful `prepare -> start -> health -> attach -> replace ->
stop` lifecycle. `start()` returns a live, ProcessRecord-backed attachment;
`stop()` alone emits the final manifest and closed-port proof. The existing
`run()` becomes a convenience wrapper over that lifecycle.

Because SGLang is an external process, one supervised watchdog actor owns each
replica's ProcessRecord and observes its exact process identity. Unexpected
process exit fails that watchdog, producing the structured `MeshFailure` that
the workload controller routes. The design does not assume that an operating-
system process exit automatically enters Monarch supervision.

`ginkgo/local_run.py` and both Qwen3 launch scripts become thin callers of the
same JobTrait path. Existing command names and accepted arguments remain.
Legacy mode values are accepted as aliases, but they must not select another
runtime implementation. `execution_mode` records the actual canonical
`monarch-actor-control` path. Existing manifest fields, ProcessRecord ownership,
generated-text evidence, failure context, teardown errors, and closed-port proof
remain Contract Artifacts.

Running state does not claim final evidence. Before `close()`, status exposes
the materialized configuration, ProcessRecord, health evidence, and Control
Store record. The existing success/failure evidence manifest is written only
after teardown and closed-port verification, preserving its meaning. Legacy
mode inputs normalize explicitly to the canonical path; artifact validators
accept the canonical output and continue to reject a label that misstates the
runtime that executed.

Internal coordinator classes and endpoint compatibility are intentionally
removed. Documentation that calls the host-control adapter the production path
is updated when the new Local Run passes.

## Error model

All shared lifecycle errors derive from `WorkloadError` and carry
`workload_id`, phase, and cause. Named failures include declaration conflict,
Placement failure, ownership failure, reattachment failure, health failure,
replacement failure, revision conflict, and teardown failure.

Before re-raising, the reconciler writes the durable failed phase when it still
owns the record. Teardown failures never replace the primary exception. No
failure activates another launcher, relaxes Placement, changes device type, or
uses a host-process fallback.

## Acceptance ladder

The first slice follows the Local Run Ladder through `scripts/run`:

1. **Environment:** require the Hermetic Rootfs and checkout Python. Do not
   require a tensor engine or GPU.
2. **Build:** install or use the actors-only editable build with test
   dependencies.
3. **Unit-level smoke:** prove non-GPU process Placement, locked record
   transitions, revision/epoch conflicts, phase-specific crash decisions,
   declaration/allocation conflicts, durable budget accounting, exact
   structured failure routing, and terminal escalation.
4. **Integration:** on `this_host()`, configure a LocalJob with one deterministic
   CPU Ginkgo test topology; reach healthy; discard the local workload/runtime
   handles and attach a fresh observer to the live controller in the unchanged
   allocation; assert the same `apply_id`, controller identity, and generation;
   kill one replica;
   prove exactly one structured route and replacement, next-generation health,
   and no call to the global fault hook; then prove owned teardown.
5. **Contract Artifacts:** emit the Placement, versioned control record,
   failure-to-decision event, replacement generation, reattachment evidence,
   Ginkgo parent manifest, and teardown/closed-port evidence. The verifier exits
   zero only if every rung passes.

The Ginkgo CLI compatibility tests additionally prove that existing arguments
reach the canonical path and that existing manifest consumers still validate.
GPU and performance checks remain deferred.

## Expected code shape

- Consolidate the duplicate `JobState` definitions in
  `python/monarch/_src/job/job.py` and `job_state.py`.
- Extend `job.py` and `job_components.py` with the singular workload
  configuration, state hook, and teardown ordering.
- Add focused shared modules under `python/monarch/_src/control_plane/` for the
  workload types, reconciler, runtime adapter, and supervision routing.
- Evolve `placement.py`, `store.py`, and `policy.py`; keep public exports narrow.
- Replace Ginkgo's parallel coordinator/actor with its serving Workload Plane
  and topology implementation.
- Convert the substrate verifier from a GPU tracer into the CPU-local behavioral
  proof and update its Contract Artifacts.
- Replace coordinator-shaped tests and extend JobTrait, substrate, Ginkgo CLI,
  verifier, and documentation coverage.

## Implementation order

1. Correct non-GPU process Placement without claiming CPU-core ownership.
2. Define the typed, locked, revisioned Control Store and its crash table.
3. Expose structured failure identity to Python and prove exact routing.
4. Split Ginkgo into a live ProcessRecord-backed lifecycle with supervised
   external-process watchdogs.
5. Add the JobTrait workload seam and shared reconciler, then prove same-
   allocation observer attachment, replacement, and teardown.
6. Collapse both CLIs onto the canonical path, emit the full CPU-local Contract
   Artifact set, and update runtime documentation.

Each step is implemented test-first. The implementation plan must preserve a
green, independently reviewable result after every step.

## Implementation tickets

- `../issues/07-non-gpu-process-placement.md`
- `../issues/08-transactional-control-store.md`
- `../issues/09-structured-supervision-routing.md`
- `../issues/10-live-ginkgo-topology.md`
- `../issues/11-job-owned-workload-reconciler.md`
- `../issues/12-canonical-ginkgo-local-run.md`

Each ticket is a separate reviewed tracer bullet. Later tickets consume only
the tested interfaces of resolved blockers.
