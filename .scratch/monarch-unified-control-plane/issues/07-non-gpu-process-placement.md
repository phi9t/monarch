# Represent non-GPU process Placement honestly

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 02
Parent: ../map.md
Spec: ../spec/01-ginkgo-serving-workload-plane.md

## Outcome

Placement can produce a valid mesh plan for non-GPU actor processes without
assigning synthetic GPU ordinals or claiming exclusive CPU-core ownership.

## Requirements

- Replace the GPU-only rank representation with typed rank placements that may
  contain zero GPU IDs.
- Express non-GPU demand as process cardinality and produce
  `per_host={"processes": N}`.
- Preserve distinct GPU assignment and gang/incremental invariants for GPU
  demand.
- Reject mixed or infeasible shapes loudly.
- Keep Placement an in-process implementation rather than adding an interface.

## Exclusions

- CPU affinity, `proc_bind`, NUMA Placement, multi-host Placement, and resource
  reservation.
- Ginkgo lifecycle, supervision routing, or Control Store migration.

## Verification

- Focused tests first fail on zero-GPU demand under the current synthetic-token
  implementation.
- Unit tests prove non-GPU process shape, GPU behavior, and invalid mixed
  demand.
- Existing control-plane substrate tests remain green through `scripts/run`.

