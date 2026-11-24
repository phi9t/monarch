# Blocker Triage and One-Variable Retry

Type: task
Status: ready-for-agent
Blocked by: 02

## Goal

If the live parent run fails, classify the blocker from artifacts and prepare at
most one reviewed one-variable retry without weakening the GLM workload
contract.

## Requirements

- Start only after ticket 02 records a nonzero live run or incomplete evidence.
- Preserve the failed run directory and do not overwrite it.
- Classify the failure as one of:
  - host-resource blocker;
  - rootfs or Insula plan blocker;
  - SGLang launch blocker;
  - SGLang generation blocker;
  - Dynamo dependency or launch blocker;
  - Dynamo inference blocker;
  - Responses launch or inference blocker;
  - teardown or orphan blocker;
  - unknown.
- Cite exact artifact paths and exact error strings in this ticket.
- For known SGLang generation failures, include crash dump path, stderr
  excerpt, scheduler exception excerpt if present, request payload, timeout,
  and teardown proof.
- For GPU occupancy failures, include the full blocked GPU list and owning
  process names. Do not kill them.
- Propose only one variable for the next retry. Examples of acceptable
  variables are one schema-owned SGLang runtime flag, one timeout value, or one
  dependency refresh. Device count, model identity, fallback backend, ports,
  and fake endpoints are not acceptable variables.
- If two retries fail with the same signature, stop patching that path and send
  a clean-context diagnosis slice before resuming.

## Exclusions

- Do not edit the parent workload contract in this ticket unless the diagnosis
  proves the existing contract is wrong and a separate implementation ticket is
  opened.
- Do not batch multiple flag changes into a single retry.
- Do not reinterpret a blocker artifact as readiness or completion evidence.

## Verification Evidence

- Failed run path and run id are recorded.
- Failure class is recorded with artifact paths.
- Teardown state is recorded, including port closure and GPU audit.
- Retry proposal names exactly one variable and the expected observable change.
- If a retry is run, the new run id is recorded and compared against the
  previous failure signature.

## Comments
