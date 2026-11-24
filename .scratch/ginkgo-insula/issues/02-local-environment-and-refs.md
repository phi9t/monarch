# Insula Local Environment And Ref Resolution

Status: ready-for-agent
Type: task
Blocked by: 01

## Objective

Parse machine-local host roots and resolve Insula logical path refs.

## Requirements

- Implement `ginkgo/insula/local_environment.py`.
- Implement `ginkgo/insula/refs.py`.
- Support `repo://`, `cache://`, `temp://`, `run://`, `results://`, and
  `rootfs://`.
- Require local environment host paths to be absolute.
- Reject unknown refs.

## Files

- Create `ginkgo/insula/local_environment.py`
- Create `ginkgo/insula/refs.py`
- Create `python/tests/test_ginkgo_insula_materialize.py`

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_materialize.py python/tests/test_ginkgo_insula_schema.py -q
```

## Notes

Follow Task 2 in `.scratch/ginkgo-insula/implementation-plan.md`.
