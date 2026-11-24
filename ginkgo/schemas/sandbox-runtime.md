# Sandbox Runtime Schema

The sandbox runtime schema describes how a machine-local host environment is
projected into the bwrap rootfs. It is materialized before launch and validated
against the plan emitted by `scripts/rootfs/enter_rootfs.sh`.

## Inputs

- Portable declared config: logical refs only.
- Local environment config: concrete host paths for repo, run, temp, cache,
  results, shared memory, and rootfs.
- Profile: sandbox-only, CUDA-kernel, dense smoke, MoE smoke, or GLM.

## Required Contract

- `repo://` resolves to the Monarch checkout and is mounted read-only at
  `/workspace/monarch`.
- `run://` resolves to the run root and is mounted read-write at `/run/glm52`.
- `temp://` resolves to the temp root and is mounted read-write at `/tmp/glm52`.
- `cache://` resolves to the cache root and is mounted read-write at
  `/cache/glm52`.
- `rootfs://monarch-default` resolves to the selected bwrap rootfs.
- Shared memory is declared explicitly and validated as part of the bwrap plan.
- GPU projection is declared explicitly and validated as part of the bwrap plan.
- The emitted inner argv, cwd, environment, mounts, and mount modes must match
  the materialized config before launch.

## Failure Rules

No host fallback is allowed. Missing roots, mismatched mount modes, unexpected
cwd, missing GPU projection, missing shared memory projection, and environment
drift fail before the serving process starts.
