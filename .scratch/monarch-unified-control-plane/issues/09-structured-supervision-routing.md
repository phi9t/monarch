# Expose structured supervision identity and route exactly

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 08
Parent: ../map.md
Spec: ../spec/01-ginkgo-serving-workload-plane.md

## Outcome

Python can route one eligible `MeshFailure` to exactly one current-generation
replica without parsing prose, relying on a mesh-name sentinel, or guessing a
rank.

## Requirements

- Add read-only Python access to the Rust failure subject actor, crashed ranks,
  optional reporting controller, and optional actor-mesh name.
- Preserve the existing string `mesh_name` behavior for unrelated callers.
- Define a generation-scoped route key over stored ownership identities.
- Accept only a single-rank failure that maps uniquely to the current
  generation; return all other failures unhandled.
- Remove `ReplacePolicy.default_rank` from the Workload Plane runtime path.

## Exclusions

- Process-global hook replacement, policy execution, Ginkgo process watching,
  and replica replacement.

## Verification

- Rust/PyO3 tests prove every new field, including absent controller/mesh name
  and whole-/multi-rank failures.
- Python tests first fail because structured fields are unavailable, then prove
  exact, stale, unknown, absent, and ambiguous routing behavior.
- A local actor-mesh test kills a named rank and proves only its route is
  consumed.

