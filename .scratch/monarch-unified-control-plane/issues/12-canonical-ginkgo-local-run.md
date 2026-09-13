# Make Ginkgo use one canonical Job-owned Local Run

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 11
Parent: ../map.md
Spec: ../spec/01-ginkgo-serving-workload-plane.md

## Outcome

Every Qwen3 Ginkgo launcher reaches the Job-owned Workload Plane, and a CPU
Local Run Ladder produces truthful, verifier-checked Contract Artifacts for
placement, persistence, attachment, replacement, and teardown.

## Requirements

- Replace Ginkgo's parallel coordinator/actor runtime path with
  `GinkgoServingWorkload` over the live topology.
- Preserve existing command names and accepted arguments. Normalize legacy
  mode values to the canonical implementation and record the actual
  `monarch-actor-control` execution mode.
- Preserve final manifest field meanings, generated-text evidence,
  ProcessRecord ownership, failure context, secondary teardown errors, and
  closed-port proof.
- Distinguish running-state artifacts from the final evidence manifest.
- Convert the substrate verifier to an actors-only CPU Local Run Ladder and
  emit every Contract Artifact required by the spec.
- Update Ginkgo schema/operator documentation only after the canonical Local
  Run passes.

## Exclusions

- CUDA dense, GLM, Dynamo, Responses, benchmark/eval, and performance claims.
- Compatibility for internal coordinator classes or lifecycle endpoints.

## Verification

- CLI tests prove every legacy input reaches one implementation and validators
  reject false execution labels.
- The CPU Local Run proves environment, actors-only build, focused tests, live
  start/health, same-allocation attachment, one replacement, final teardown,
  and all Contract Artifacts.
- No GPU command runs under this ticket.

