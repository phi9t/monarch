# Make the Control Store transactional and typed

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 07
Parent: ../map.md
Spec: ../spec/01-ginkgo-serving-workload-plane.md

## Outcome

The filesystem Control Store persists a typed workload lifecycle and prevents
two controllers from launching or replacing the same workload.

## Requirements

- Replace arbitrary spec/placement mappings with the versioned WorkloadRecord
  defined by the spec.
- Implement one exclusive workload lease, a monotonic fencing epoch, and
  compare-and-swap over expected revision plus epoch.
- Use unique temporary names, file fsync, atomic replace, and parent-directory
  fsync.
- Encode and test the phase-specific crash table for declared, planned,
  starting, running, recovering, stopping, failed, and stopped.
- Persist reallocation consumption and primary/secondary failure evidence.

## Exclusions

- Network databases, distributed consensus, multiple hosts, and automatic
  recovery without ownership evidence.
- JobTrait or Ginkgo integration.

## Verification

- Focused tests first fail because the current store accepts unconditional
  last-writer-wins updates.
- Tests prove lease exclusion, stale revision/epoch rejection, durable reload,
  directory durability calls, phase decisions, and JSON round trips.
- Tests use a real temporary filesystem for locking and persistence behavior.

