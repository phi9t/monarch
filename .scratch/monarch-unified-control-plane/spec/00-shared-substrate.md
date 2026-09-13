# Spec: shared coordination-core substrate for the unified control plane

Status: tracer-bullet built + verified (2026-09-05)
Parent: ../map.md
Decides: the shared substrate all three Workload Planes call (map "Not yet
specified" items: unified API shape, scheduler/placement, control store).
Grounded in: `docs/adr/0003-shared-core-three-thin-planes.md`,
`research/comparable-control-planes.md`.

## Goal

Add the three primitives every Workload Plane needs equally — **Placement**, a
**Reallocation Policy** seam, and a durable **Control Store** — to Monarch's
landed mesh + supervision + Insula + telemetry core, without forking any of it
and without building a plane yet. Success is a single local tracer bullet: a
control actor places a mesh through Placement, persists the spec to the Control
Store, kills one rank, and a Reallocation Policy re-places the mesh — all on
`this_host()`, inside `scripts/run`, failing loud if the environment is wrong.

Non-goals: the per-plane APIs (training/serving/analysis), multi-host placement,
GPU-pool multi-tenancy beyond one-rootfs-per-run, and any packaging/publication
(owned by `.scratch/production-release-readiness/`).

## Landed primitives this builds on

- `JobTrait` (`python/monarch/_src/job/job.py:350`): declarative spec →
  `apply()` (`:477`) → `state()` (`:556`) polling hook returning `JobState` with
  the host meshes; already caches state to `.monarch/job_state.pkl`
  (`:557`) and reloads it (`_load_cached` `:564`) so a fresh process re-attaches
  to a running job. This is the Control Store seed and the Placement input.
- Supervision: `MeshMonitor` → `MeshFailure` naming the failed rank
  (`hyperactor_mesh/src/monitor.rs:9`), surfaced as
  `unhandled_fault_hook(MeshFailure)` defaulting to `sys.exit(1)`
  (`python/monarch/_src/actor/supervision.py:25,54`). This is the Reallocation
  Policy seam.
- Mesh spawn: `this_host().spawn_procs(per_host=...)` and actor spawn — the
  thing Placement targets.
- Telemetry: `monarch_distributed_telemetry` (Arrow/DataFusion) — where
  placement/reallocation events are recorded, reused later by the analysis plane.

## The three additions

### 1. Placement

One decision that maps a workload's requested actors onto meshes. Model it as a
pure function over declared demand plus observed host capacity, not a scheduler
daemon:

    Placement.plan(demand: WorkloadDemand, capacity: HostCapacity) -> MeshPlan

- `WorkloadDemand`: per-plane request expressed uniformly — count + shape of
  worker actors, per-actor resource needs (gpus, cpus, labels), and a gang
  constraint (all-or-nothing vs incremental). Training sets gang=all; serving
  sets a replica range; analysis sets one bundle per partition.
- `HostCapacity`: derived from `JobState` host meshes + local GPU inventory
  (the 8-GPU verifier already enumerates visible CUDA devices).
- `MeshPlan`: the concrete `per_host`/rank assignment fed to `spawn_procs`.

First setting is single-host, so `plan` degenerates to "fit N gang actors onto
the local GPUs or fail loud" — but the signature is the seam the three planes
share. Do not add a general bin-packer yet; make illegal states unrepresentable
(a `MeshPlan` that does not satisfy the gang constraint cannot be constructed).

### 2. Reallocation Policy

Replace the process-global default hook with a per-workload registered policy.
Keep `unhandled_fault_hook` as the last-resort default (still `sys.exit(1)` for
unmanaged clients), but let a Workload Plane install a policy the supervision
event routes to first:

    ReallocationPolicy.on_failure(failure: MeshFailure, job: JobTrait) -> Decision

`Decision` is a closed enum — `Resume(from_checkpoint)`, `Replace(rank)`,
`ReExecute(stage)`, `Escalate` — so the three planes differ only by which
variant they return. The policy re-derives topology from the *current*
`JobState` after reallocation (never a cached world size — research: torch-
elastic reassigns RANK/WORLD_SIZE on every restart). Bound retries with a
counter on the workload spec (`max_reallocations`), escalating to the default
hook when exhausted. This is the single seam tickets 04 (training resume) and
02/03 (serving replica replace) and 05 (stage re-exec) all specialize.

### 3. Control Store

Promote the existing pickle cache into an explicit, durable record so a control-
actor restart re-attaches rather than restarts. First implementation reuses the
landed mechanism (a directory of specs + current placement, the
`.monarch/job_state.pkl` pattern) behind a named interface:

    ControlStore.put(workload_id, spec, placement)
    ControlStore.get(workload_id) -> (spec, placement) | None
    ControlStore.list() -> [workload_id]

Keyed on a stable `workload_id` (research: Ray Train resumes a whole run from
`(storage_path, run_name)`; recovery must key on identity, not live state). Not
a database yet — a filesystem record under the checkout, atomic-write + reload,
matching `dump`/`_load_cached`. The interface is what lets us swap in a real
store later without touching the planes.

## Tracer bullet (the acceptance ladder)

Following the Local Run Ladder in `CONTEXT.md`, one script
`scripts/run_local_substrate_verifier.sh` (via `scripts/run`, fail-loud
preflight, no fallback):

1. **Environment**: rootfs active, tensor engine present, >=1 local GPU, else
   abort in preflight (not skip).
2. **Build**: editable install with tensor engine (reuse the 8-GPU verifier's
   build steps).
3. **Smoke**: `Placement.plan` fits a 2-actor gang onto local GPUs; spawn the
   mesh; `ControlStore.put` the spec+placement; assert `ControlStore.get`
   round-trips after a fresh process load.
4. **Integration**: kill one rank; assert the registered `ReallocationPolicy`
   receives the `MeshFailure`, returns `Replace(rank)`, and the mesh is
   re-placed with ranks re-derived from current `JobState` — not `sys.exit(1)`.
5. **Contract Artifacts**: emit `substrate-results/placement.json`,
   `substrate-results/reallocation.jsonl` (one line per `MeshFailure→Decision`),
   and the round-tripped control-store record; the verifier exits zero only when
   the reallocation line shows `Replace` and the re-placed ranks match demand.

## Open decisions this spec still defers to tickets

- Checkpoint transport (RDMA vs filesystem) and cadence ownership — ticket 04.
- Serving replica registry + router shape — tickets 02/03.
- DataFusion exchange operator + partition placement — ticket 05.
- Multi-host Placement and GPU-pool multi-tenancy — later, once single-host
  tracer lands.

## Built + verified (2026-09-05)

The tracer bullet landed and passed on 2 local B200s through the rootfs
(`scripts/run scripts/run_local_substrate_verifier.sh --gpus 2`).

- Package `python/monarch/_src/control_plane/` (public `monarch.control_plane`):
  `placement.py` (`Placement.plan`, `WorkloadDemand`, `HostCapacity`, `MeshPlan`,
  `GangConstraint`, `PlacementError`), `policy.py` (`ReallocationPolicy`,
  `Decision = Resume|Replace|ReExecute|Escalate`, `ReplacePolicy`, bounded
  retry), `store.py` (`ControlStore` atomic JSON put/get/list/delete).
- Unit tests `python/tests/test_control_plane_substrate.py` — 23 passed
  (placement gang fit, decision/budget accounting, control-store round-trip).
- Mesh tracer `scripts/local_substrate_verifier.py` +
  `scripts/run_local_substrate_verifier.sh` (Local Run Ladder, fail-loud,
  ladder exit codes 21-24).
- Contract Artifacts under `substrate-results/`: `placement.json`,
  `control-store/substrate-tracer.json`, `reallocation.jsonl` (two `replace`
  decisions observed, not `sys.exit(1)`), `replan.json`.

Proven seam: a `MeshFailure` now routes through a registered
`ReallocationPolicy` returning `Replace` instead of the default `sys.exit(1)`,
placement round-trips through the control store across a fresh instance, and the
mesh re-places from current membership. This is the shared substrate the three
Workload Planes specialize.
