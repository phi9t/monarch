# Insula Rootfs Entrypoint Compatibility

Status: ready-for-agent
Type: task
Blocked by: 06

## Objective

Route `scripts/run` and `scripts/rootfs/enter_rootfs.sh` through Insula while
preserving documented behavior.

## Requirements

- Implement `ginkgo/insula/compatibility.py`.
- Convert `scripts/run` into a compatibility adapter over Insula.
- Convert `scripts/rootfs/enter_rootfs.sh` into a compatibility adapter over
  Insula.
- Preserve `MONARCH_ROOTFS`, `MONARCH_ROOTFS_EMIT_PLAN`, `--chdir`,
  `--repo-readonly`, `--bind-rw`, `--emit-plan`, and `--rootfs` behavior.
- Preserve exit codes.
- Run live `scripts/run` and legacy `enter_rootfs.sh` smokes.

## Files

- Create or modify `ginkgo/insula/compatibility.py`
- Modify `ginkgo/insula/cli.py`
- Modify `scripts/run`
- Modify `scripts/rootfs/enter_rootfs.sh`
- Modify `python/tests/test_ginkgo_insula_compatibility.py`
- Modify `scripts/rootfs/tests/test_run_gateway.py`
- Modify `scripts/rootfs/tests/test_guarded_entrypoints.py`

## Verification

```sh
scripts/run python -m pytest python/tests/test_ginkgo_insula_compatibility.py scripts/rootfs/tests/test_run_gateway.py scripts/rootfs/tests/test_guarded_entrypoints.py -q
scripts/run python -c "print('insula-run-ok')"
tmp_plan="$(mktemp)"
scripts/rootfs/enter_rootfs.sh --emit-plan "$tmp_plan" -- python3 -c "print('insula-enter-ok')"
test -s "$tmp_plan"
```

## Notes

Follow Task 7 in `.scratch/ginkgo-insula/implementation-plan.md`.
