# Close the actor-control-plane evidence gap

Type: grilling
Status: resolved
Blocked by: 01
Parent: ../map.md

## Question

What is the smallest live proof that converts Monarch's actor-control path from
PLANNED to LANDED, and is that proof a shared prerequisite for all three planes?

Evidence: `ginkgo/schemas/monarch-control-plane.md` Required Checks 3-5 are
open — the Monarch-actor mode is fake-runtime tested for GLM and only
CPU/Qwen3-proven live (`live_qwen3_in_process_actor_smoke`). The host-control
adapter is the production path today; GLM live serving is proven only through
the subprocess adapter, not through `GinkgoControlPlaneActor` endpoints.

Meanwhile the training side has the 8-GPU Capacity Verifier
(`scripts/run_local_8gpu_capacity.sh`, acceptance ladder in `AGENTS.md:209-230`)
which proves proc-mesh + shard fetch over 8 GPUs but does not exercise the
serving actor control plane.

Decide:

- Which single live check (CPU actor run of `serving-smoke-cpu` via
  `--mode in-process-actor`, then CUDA dense on one GPU) is the ordered proof.
- Whether the actor-control path is the shared launch seam decided in ticket 01,
  and therefore a hard prerequisite for the serving AND training tracer bullets.
- Whether the 8-GPU Capacity Verifier ladder + Contract Artifacts pattern
  becomes the reusable template for a per-plane verifier.

Decision, not execution: name the proof and its ordering; do not run GPUs here.
Any GPU run is separately human-approved (see production-release-readiness spec).

## Answer

Decision (user-approved 2026-09-08): the first serving proof is a CPU-local
Ginkgo Workload Plane configured through `JobTrait.enable_workload(...).state()`.
It replaces the parallel Ginkgo coordinator/actor lifecycle and joins
Placement, Control Store, and supervision-driven replacement in one runtime
path. The proof starts a healthy workload, persists its typed record, attaches
a fresh observer to the live controller inside the unchanged allocation,
replaces one failed replica through structured failure identity, and verifies
owned teardown plus
the existing Ginkgo Contract Artifacts. It models non-GPU processes directly
without claiming CPU-core reservation and requires no GPU; CUDA dense remains
the next ordered proof.

The approved interface and acceptance ladder are specified in
`../spec/01-ginkgo-serving-workload-plane.md`.
