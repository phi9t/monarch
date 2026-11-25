# Join the Workload Plane to JobTrait reconciliation

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 07, 08, 09, 10
Parent: ../map.md
Spec: ../spec/01-ginkgo-serving-workload-plane.md

## Outcome

`JobTrait.enable_workload(...).state()` becomes the single deep interface for
starting or strictly reattaching one healthy Workload Plane and for replacing a
failed replica under durable policy.

## Requirements

- Add singular workload configuration without changing the argument-free
  `JobTrait.__init__()` contract.
- Consolidate the duplicate JobState definitions and expose
  `JobState.workload: WorkloadHandle | None`.
- Add the private CoordinationComponent and reconciler with exact lifecycle
  ordering, error normalization, and teardown before job allocation release.
- Keep retry consumption in the Control Store and the plane callback pure.
- Attach only a fresh observer handle inside the same live allocation for this
  slice; assert an unchanged `apply_id`, controller identity, and generation.
- Keep the live controller as the sole writer, lease holder, and failure-route
  owner. Observer attachment must not acquire the lease, reinstall routes, or
  mutate the record.
- Attach only to matching deterministic ownership evidence. Never launch from
  starting, recovering, failed, or stopped records.
- Route unknown or ineligible failures to the existing root fail-fast behavior
  and never replace the process-global hook.

## Exclusions

- Writer handoff, fresh-process LocalJob reattachment, fatal controller-owner
  reconstruction, multiple workloads per job, training/data planes, and GPU
  behavior.

## Verification

- Job tests first fail on the wished-for configuration and state interface.
- Scripted Workload Plane tests prove configuration ordering, start-to-running,
  declaration/allocation conflicts, strict attach, idempotent close, and
  primary-versus-cleanup errors.
- CPU actor-mesh behavior proves same-allocation fresh-observer attachment to
  the identical controller, one structured failure, one replacement,
  next-generation health, durable budget use, and no global-hook call.
