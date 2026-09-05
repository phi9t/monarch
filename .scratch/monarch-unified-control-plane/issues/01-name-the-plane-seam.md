# Name the unified control-plane seam

Type: grilling
Status: resolved
Blocked by:
Parent: ../map.md

## Question

What is shared vs plane-specific across training, serving, and data analysis?

Monarch today has two disjoint control surfaces:

- **Job/mesh coordination** (`python/monarch/_src/job/job.py:350` `JobTrait`,
  `host_mesh.py:67`, `proc_mesh.py:422`, supervision at `supervision.py:25`) —
  declarative job spec, mesh spawn, fail-fast supervision. Backends: Local,
  Slurm, Kubernetes, SSH, MAST, SPMD/torchrun bridge.
- **Ginkgo serving control plane** (`ginkgo/control_plane.py`,
  `ginkgo/schemas/monarch-control-plane.md`) — a separate coordinator + actor +
  host-control adapter that orders prepare/launch/probe/teardown/status for
  inference components on Insula.

These do not share a control-plane abstraction. The core decision this map
turns on: **is there one control-plane interface that all three planes
implement, or three planes that only share the mesh core + Insula + telemetry?**

Resolve, using `/grilling` and `/domain-modeling`:

- Name the shared control-plane vocabulary in `CONTEXT.md` terms (Local Run,
  Capacity Verifier already exist). Do the three planes share a "Workload",
  "Plane", "Component", "Verifier ladder"?
- Decide whether Ginkgo's coordinator/actor is the seam every plane launches
  through, or whether `JobTrait` is, or whether they merge.
- Decide the boundary: what MUST be shared (Insula, `scripts/run`, supervision,
  telemetry, no-fallback) vs what is legitimately plane-specific.
- Record the decision as an ADR under `docs/adr/` (this is a hard-to-reverse
  architectural choice).

This ticket gates the API-shape, scheduler, and per-plane tracer-bullet
decisions, so resolve it first.

## Answer

Decision (user-confirmed 2026-09-05): **shared coordination core + three thin
workload planes**, not three independent control planes and not one merged API.

Shared (must be shared): the landed mesh + supervision + Insula (`scripts/run`
gateway, sole bwrap owner) + telemetry substrate, plus three new shared
primitives every plane needs equally — one **Placement** decision over meshes,
one **Reallocation Policy** on the supervision tree (replacing
`supervision.py:54` `sys.exit(1)`), and one durable **Control Store** for specs
and placement so a control-actor restart re-attaches. `JobTrait`
(`job.py:350`) stays the placement/lifecycle seam.

Plane-specific (legitimately): actor topology, health signal, reallocation-
policy callback, and the thin per-plane API. Ginkgo's coordinator/actor becomes
the **serving** Workload Plane over `JobTrait`, not a parallel control plane —
they do not merge into one API; they share the core.

Recorded as `docs/adr/0003-shared-core-three-thin-planes.md`. New domain terms
to add to `CONTEXT.md`: Workload Plane, Placement, Reallocation Policy, Control
Store (done in the follow-on substrate spec).
