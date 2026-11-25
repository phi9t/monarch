# Prove Monarch's self-contained rootfs adaptation

Type: task
Status: needs-info
Blocked by: 01
Parent: ../spec.md

## Requirements

- Remain `needs-info` until Ultron's parent ticket records the resolved Vaso
  `02-freeze-rootfs-spec-v1` digest and changes this ticket's status.

- Map Vaso v1 behavior to Insula and `scripts/run` without importing Vaso code.
- Close gaps in identity, selection, mounts, environment, network, B200
  projection, evidence, and clean bootstrap.

## Verification

- Red-green conformance and negative-path tests pass against repository-owned
  behavior.

## Comments
