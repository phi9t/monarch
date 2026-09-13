# Insula Bwrap Plan And Argv

Status: ready-for-agent
Type: task
Blocked by: 03

## Objective

Generate bwrap argv from materialized Insula invocations and validate structured
plans against those invocations.

## Requirements

- Implement `ginkgo/insula/bwrap_plan.py`.
- Generate argv with rootfs ro-bind, proc/tmp/dev/home setup, repo bind, extra
  binds, clearenv, setenv, cwd, and payload command.
- Emit `InsulaPlan`.
- Validate rootfs, cwd, env, command, mounts, and bwrap argv digest.
- Reject drift loudly.

## Files

- Create `ginkgo/insula/bwrap_plan.py`
- Create `python/tests/test_ginkgo_insula_bwrap_plan.py`
- Modify `ginkgo/insula/materialize.py` if needed

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_schema.py python/tests/test_ginkgo_insula_materialize.py python/tests/test_ginkgo_insula_bwrap_plan.py -q
```

## Notes

Follow Task 4 in `.scratch/ginkgo-insula/implementation-plan.md`.
