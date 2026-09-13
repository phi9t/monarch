# Insula Schema And Serialization

Status: ready-for-agent
Type: task
Blocked by:

## Objective

Create the source-backed Insula invocation schema and serialization layer.

## Requirements

- Implement frozen dataclasses in `ginkgo/insula/schema.py`.
- Reject unknown fields.
- Reject absolute host paths in portable invocation specs.
- Reject relative sandbox paths.
- Reject empty command argv.
- Reject non-allowlisted bind modes.
- Serialize and load YAML without losing information.

## Files

- Create `ginkgo/insula/__init__.py`
- Create `ginkgo/insula/schema.py`
- Create `python/tests/test_ginkgo_insula_schema.py`

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_schema.py -q
```

## Notes

Follow Task 1 in `.scratch/ginkgo-insula/implementation-plan.md`.
