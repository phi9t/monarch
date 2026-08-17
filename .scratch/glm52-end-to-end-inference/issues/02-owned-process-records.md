# Owned Process Records

Status: ready-for-agent

Type: task

Blocked by: 01

## Goal

Create a shared process ownership and teardown contract for SGLang, Dynamo, and
the Responses adapter.

## Requirements

- Represent each owned component with a process record that includes run ID,
  component name, PID, process group ID, argv digest, env digest, endpoint URL,
  stdout path, stderr path, and creation timestamp.
- Write a process record only after the child process starts.
- Refuse to tear down a PID unless the record proves ownership and the live
  process still matches the expected command fingerprint.
- Tear down process groups, not only parent PIDs.
- Treat missing records, stale records, PID reuse, command drift, and process
  group mismatch as loud failures.
- Prove post-teardown port closure for every allocated port.
- Prove no owned process orphans remain after each cycle.
- Preserve artifacts on failure.

## Exclusions

- Do not implement Dynamo-specific launch behavior.
- Do not alter the generic Hermetic Rootfs process model unless this contract
  exposes a concrete bug.

## Verification Evidence

- Unit tests for valid process record parsing.
- Unit tests for stale PID, command drift, missing record, and PID reuse
  rejection.
- Unit tests for reverse-order teardown summaries.
- Unit tests for port-closure and orphan-scan failure reporting.

## Comments
