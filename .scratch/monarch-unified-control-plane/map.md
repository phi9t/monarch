# Wayfinder: Monarch as a unified control plane for training, serving, and data analysis

Label: wayfinder:map

## Destination

A repo-local decision spec for adapting Monarch into **one** control plane that
launches, supervises, and observes three workload classes — model training,
model serving, and data analysis — over a shared coordination core (actor/proc/
host meshes + supervision), a shared execution envelope (Insula bwrap rootfs +
`scripts/run`), and a shared telemetry substrate (Arrow/DataFusion). The
destination is the set of resolved decisions that let a future spec + tickets
build the plane; it is not the plane itself.

Reaching the end looks like: every frontier decision below is closed, the
unified-plane seam (what is shared vs plane-specific) is named, and each plane
has a chosen first tracer bullet that reuses landed work rather than forking it.

## Notes

Domain: Monarch is a Rust actor core (`hyperactor`, `hyperactor_mesh`) with a
thin Python API (`python/monarch/`), plus a landed local-serving adaptation
(Ginkgo + Insula) and a landed telemetry stack (`monarch_distributed_telemetry`).

Skills every session should consult: `subagent-exploration` (broad reads),
`grilling` + `domain-modeling` (decision tickets), `research` (external facts),
`code-review` before any landing. Follow `AGENTS.md`, `CONSTITUTION.md`, and
`docs/agents/skill-orchestration.md`. Clean-context subagents are the default
for non-trivial slices.

Standing preferences: extend existing work, do not fork (user chose "Extend
existing"). Keep `scripts/run` as the sole execution gateway and Insula as the
sole bwrap owner. No-fallback / fail-loud is a repo invariant. Local landing
only unless explicitly asked to push. This is a **planning** map: produce
decisions, not deliverables, until it hands off to `/to-spec`.

Related existing efforts (do not duplicate): `.scratch/glm53-flash-local-serving/`
(serving), `.scratch/production-release-readiness/` (release qualification),
`ginkgo/schemas/monarch-control-plane.md` (actor control-plane schema).

## Decisions so far

<!-- one line per closed ticket: gist + link -->

- Plane seam (01, resolved): **shared coordination core + three thin workload
  planes**. Shared = mesh+supervision+Insula+telemetry plus 3 new primitives
  (Placement over meshes, Reallocation Policy replacing `sys.exit(1)`, durable
  Control Store); `JobTrait` stays the lifecycle seam; Ginkgo becomes the
  serving plane, not a parallel control plane. → `docs/adr/0003-shared-core-three-thin-planes.md`,
  `issues/01-name-the-plane-seam.md`

- Research (06, resolved): comparable planes (Ray/torch-elastic/SGLang/Dynamo/
  DataFusion) converge — one actor core hosts all three planes as thin libraries;
  the only shared gaps are (a) one scheduler/placement over meshes and (b) a
  restart/reallocation policy replacing `unhandled_fault_hook`'s `sys.exit(1)`,
  plus a durable control store. Favors "shared core + three thin planes".
  → `research/comparable-control-planes.md`, `issues/06-research-comparable-planes.md`

## Not yet specified

<!-- in-scope fog, graduates as the frontier advances -->

- Shared substrate (Placement + Reallocation Policy + Control Store): **spec
  drafted** at `spec/00-shared-substrate.md` with a single-host tracer bullet.
  Still fog: whether the tracer bullet is approved to build (needs GPU run
  authorization), and the concrete `Decision` enum wiring in Rust supervision.
- Unified control-plane API shape: resolved in principle by 01 (three thin
  plane APIs over the shared core, not one merged API); per-plane API shapes
  still fog (hang on 02/03/04/05).
- Scheduler / placement across meshes: single-host degenerate form specced;
  multi-host gang scheduling, GPU pool allocation, multi-tenant isolation still
  fog.
- Checkpoint/restart + elastic reconfiguration transport (RDMA vs filesystem):
  still open — ticket 04, now unblocked by 01.
- Whether GLM-5.3-Flash bringup should wait for the de-GLM runtime refactor
  (ticket 03) or proceed model-scoped as its current spec proposes.
- Telemetry-as-analytics: promoting `monarch_record_batch` + DataFusion from
  internal telemetry to a user-facing dataset/dataframe API. (Hangs on 05.)
- Multi-host / multi-GPU actor-control proof beyond the single-host 8-GPU
  verifier and the CPU/Qwen3 actor smoke.
- Observability seam: training curves (loss/throughput/MFU) vs the current
  actor/message health dashboard.

## Out of scope

<!-- ruled beyond the destination -->

- Building the plane itself (this is a planning map; execution is a later
  spec/tickets phase).
- Kubernetes/KubeRay/cluster-native scheduling for the first setting (serving
  spec already rules this out for the initial path).
- Publishing packages/containers or qualifying non-B200 hardware (owned by
  `.scratch/production-release-readiness/`).
- Replacing Insula as the bwrap owner.
