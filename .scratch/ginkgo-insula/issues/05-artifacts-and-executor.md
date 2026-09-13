# Insula Artifacts And Executor

Status: ready-for-agent
Type: task
Blocked by: 04

## Objective

Write Insula invocation evidence artifacts and execute generated bwrap argv
through one executor interface.

## Requirements

- Implement `ginkgo/insula/artifacts.py`.
- Implement `ginkgo/insula/executor.py`.
- Write materialized invocation, argv, env, plan, validation, stdout, stderr,
  and result artifacts.
- Execute through injectable fake runner in tests.
- Mark nonzero return codes as failed.

## Files

- Create `ginkgo/insula/artifacts.py`
- Create `ginkgo/insula/executor.py`
- Modify `python/tests/test_ginkgo_insula_bwrap_plan.py`

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_bwrap_plan.py -q
```

## Notes

Follow Task 5 in `.scratch/ginkgo-insula/implementation-plan.md`.
