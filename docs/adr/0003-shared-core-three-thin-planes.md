# Shared coordination core with three thin workload planes

Monarch adapts into one control plane for training, serving, and data analysis
by keeping a single shared coordination core and adding three thin,
plane-specific libraries on top — not three independent control planes.

The shared core is the landed mesh + supervision + Insula + telemetry substrate
plus three additions every plane needs equally: one **Placement** decision over
meshes, one **Reallocation Policy** on the supervision tree (replacing the
`unhandled_fault_hook` default `sys.exit(1)`), and one durable **Control Store**
for workload specs and placement so a control-actor restart re-attaches rather
than restarting from zero. Comparable systems converge here: Ray hosts Train,
Serve, and Data as libraries over one actor/task core (placement groups, GCS,
per-actor restart); torch-elastic, Dynamo's Planner, and Ballista's
stage scheduler are the same placement + restart abstractions specialized per
workload. See `.scratch/monarch-unified-control-plane/research/comparable-control-planes.md`.

Each **Workload Plane** owns only its actor topology, health signal, and policy
callback:

- Training: gang-schedule a worker group; on failure resume the group from the
  last checkpoint (torch DCP), re-deriving rank/topology from current mesh
  membership.
- Serving: size replica pools to an SLA; on failure replace a replica; front
  workers with a model registry and router.
- Data analysis: place partitions across a stage; on failure re-execute the
  stage; move Arrow buffers over the mesh (RDMA/PortRef) rather than a separate
  data runtime.

`JobTrait` remains the placement/lifecycle seam and Ginkgo's coordinator/actor
becomes one Workload Plane (serving) over that seam, not a parallel control
plane. What must stay shared: Insula as the sole bwrap owner, `scripts/run` as
the sole execution gateway, the supervision tree, the telemetry substrate, and
the no-fallback / fail-loud invariant. What is legitimately plane-specific: the
health signal, the reallocation-policy callback, and the thin per-plane API.

The first concrete serving interface was approved on 2026-09-08. A caller
configures one Ginkgo Workload Plane through
`JobTrait.enable_workload(...).state()`. A shared reconciliation implementation
owns typed durable generations, Placement, exact supervision routing,
replacement, and strict reattachment; Ginkgo owns serving topology, health,
and its Reallocation Policy. Reattachment requires matching allocation,
declaration, and deterministic actor/ProcessRecord ownership evidence. It never
silently launches a duplicate. See
`.scratch/monarch-unified-control-plane/spec/01-ginkgo-serving-workload-plane.md`.
That first slice proves attachment of a fresh observer handle to the same live
controller and JobTrait allocation. The controller remains the sole writer and
failure-route owner. A fresh OS process cannot presently reconnect a
`LocalJob`, and writer handoff or reconstitution of a fatally lost owner actor
is a later step toward the broader control-actor restart objective above.
