# Insula Rootfs Lifecycle And CLI

Status: ready-for-agent
Type: task
Blocked by: 05

## Objective

Expose Insula through a CLI and wrap existing rootfs build/verification checks
behind an Insula lifecycle interface.

## Requirements

- Implement `ginkgo/insula/rootfs_lifecycle.py`.
- Implement `ginkgo/insula/cli.py`.
- Preserve rootfs build and verification by delegating to existing scripts.
- Provide CLI subcommands `run`, `emit-plan`, `monarch-run`, and
  `enter-rootfs-compat`.
- Keep compatibility subcommands loud and incomplete until Task 7.

## Files

- Create `ginkgo/insula/rootfs_lifecycle.py`
- Create `ginkgo/insula/cli.py`
- Create `python/tests/test_ginkgo_insula_compatibility.py`

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_compatibility.py -q
```

## Notes

Follow Task 6 in `.scratch/ginkgo-insula/implementation-plan.md`.
