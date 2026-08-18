# Insula Materialized Invocation

Status: ready-for-agent
Type: task
Blocked by: 02

## Objective

Convert portable Insula invocation specs into concrete, serializable
materialized invocations.

## Requirements

- Implement `ginkgo/insula/materialize.py`.
- Resolve every logical path ref through `InsulaLocalEnvironment`.
- Leave no unresolved refs in `MaterializedInsulaInvocation`.
- Preserve command cwd and argv.
- Resolve artifact paths.
- Do not create host directories in this task.

## Files

- Create `ginkgo/insula/materialize.py`
- Modify `python/tests/test_ginkgo_insula_materialize.py`

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_materialize.py -q
```

## Notes

Follow Task 3 in `.scratch/ginkgo-insula/implementation-plan.md`.
