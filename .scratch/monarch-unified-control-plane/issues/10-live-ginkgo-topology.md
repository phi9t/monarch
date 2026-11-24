# Split Ginkgo into a live supervised topology

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 09
Parent: ../map.md
Spec: ../spec/01-ginkgo-serving-workload-plane.md

## Outcome

Ginkgo exposes a live ProcessRecord-backed serving topology that can start,
attach, report health, replace one replica, and stop without using its current
completed one-shot run as a live handle.

## Requirements

- Extract `prepare`, `start`, `health`, `attach`, `replace`, and `stop` from
  `SglangLocalRun.run()`; retain `run()` as a convenience composition.
- Return JSON-safe, deterministic ProcessRecord ownership from start/attach.
- Emit the existing final evidence manifest only after stop and closed-port
  proof.
- Add one Monarch watchdog actor per external replica. It validates the exact
  ProcessRecord/process identity and fails on unexpected exit so supervision
  receives a structured failure.
- Replacement stops only the proven failed replica, launches its next
  generation, and passes health before returning.

## Exclusions

- Dynamo, Responses, GLM runtime extraction, GPU validation, and shared
  reconciliation policy.

## Verification

- A wished-for `start()` test first fails because today's runner exposes only
  the completed `run()` operation.
- Stateful fake-runtime tests prove start remains live, attach adopts the same
  process, replace changes only one replica generation, and stop preserves the
  existing final manifest meaning.
- A CPU-local actor test proves unexpected external-process exit fails the
  matching watchdog.
