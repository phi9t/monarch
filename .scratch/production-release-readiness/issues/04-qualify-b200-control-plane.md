# Qualify Monarch's B200 control-plane seam

Type: task
Status: ready-for-agent
Blocked by: 03, 07
Parent: ../spec.md

## Requirements

- Run the exact human-approved B200 control-plane contract from ticket 07
  inside bwrap without changing its inputs or thresholds.
- Verify device/driver projection, native behavior, and sanitized receipt.

## Verification

- The signed exact-commit B200 receipt verifies independently against the
  federation trust root and schema; incompatible GPU state fails closed.

## Comments
