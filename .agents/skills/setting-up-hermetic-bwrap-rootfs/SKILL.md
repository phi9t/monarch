---
name: setting-up-hermetic-bwrap-rootfs
description: Use when building, relocating, repairing, or validating a hermetic bubblewrap rootfs for Monarch or a similar repo-local Linux execution sandbox, especially after disk pressure, toolchain drift, CUDA linker failures, stale native artifacts, or bwrap mount problems.
---

# Setting Up a Hermetic bwrap Rootfs

## Core Contract

The rootfs is an execution protocol, not a convenience shell. It must fail fast
when the expected image, mounts, toolchain, cache roots, or virtual environment
are not concrete and current. Do not fall back to the host toolchain, host
Python packages, ambient ports, or implicit downloads unless the user explicitly
asks to bypass the sandbox.

For Monarch, use `.agents/skills/run-monarch-single-machine/SKILL.md` for normal
development commands. Use this skill when the rootfs itself needs setup,
relocation, repair, or proof.

## Stop Conditions

Stop before mutating state when any of these are true:

- you have not read the current rootfs scripts in this checkout;
- the proposed rootfs or cache path is relative, empty, a placeholder, or copied
  from a prior transcript without live verification;
- the path to delete is not proven generated, rebuildable, outside active use,
  and unrelated to user work;
- disk pressure exists but you have not identified which filesystem receives
  rootfs export, caches, and `CARGO_TARGET_DIR`;
- the only proof of sandbox entry is `MONARCH_IN_ROOTFS=1`. The marker is not
  sufficient without `identify-controlled` or the contract checks.

## Expected Shape

Inside the sandbox:

- checkout mounted at `/workspace/monarch`;
- active venv at `/workspace/monarch/.venv-rootfs`;
- rootfs contract at `/etc/monarch-rootfs-contract`;
- `MONARCH_IN_ROOTFS=1`;
- `UV_PROJECT_ENVIRONMENT=/workspace/monarch/.venv-rootfs`;
- `CARGO_TARGET_DIR=/workspace/monarch/target/bwrap/<recipe-sha256>`;
- rootfs-managed caches under stable sandbox paths, usually
  `/workspace/monarch/scripts/rootfs/cache/...`;
- host NVIDIA driver userspace projected read-only under `/run/nvidia-host`;
- `CUDA_HOME` and `CUDA_PATH` pointing at the synthetic CUDA tree, usually
  `/opt/cuda-synth`;
- `LD_LIBRARY_PATH` and `LIBRARY_PATH` containing
  `/run/nvidia-host:/opt/cuda-synth/lib64` when NVIDIA is present.

On the host:

- rootfs exports may live outside the checkout when the repo filesystem is tight;
- heavy caches and build targets may live outside the checkout, but the sandbox
  paths stay stable;
- portable YAML/config must not encode absolute host paths. Use local resolver
  env or resolved artifacts for host-specific paths.
- local override env values must be absolute, live-checked, and excluded from
  committed portable configuration.

## Setup Ladder

1. **Read the current contract.** Inspect `scripts/run`,
   `scripts/rootfs/enter_rootfs.sh`, `scripts/rootfs/build_rootfs.sh`,
   `scripts/rootfs/contract.env`, and `scripts/rootfs/execution_contract.sh`.
2. **Check host prerequisites and active use.**

   ```sh
   command -v bwrap docker
   df -h . /data01 /data02 2>/dev/null || df -h .
   ps -eo pid,ppid,stat,etime,cmd | rg 'bwrap|sync_test_environment|uv pip install|cargo|rustc' || true
   ```

   Do not delete or replace a rootfs, cache, target, or venv while a process is
   using it.
3. **Choose storage deliberately.** If the checkout filesystem is full, set
   absolute local overrides after replacing placeholders with live paths:

   ```sh
   export MONARCH_ROOTFS=/data01/.../rootfs-<recipe>
   export MONARCH_ROOTFS_CACHE_ROOT=/data01/.../monarch-rootfs-cache
   ```

   Treat these as local resolver inputs. Do not write them into portable
   declared configs.
4. **Prove the rootfs export is current.**

   ```sh
   test -n "${MONARCH_ROOTFS:-}" && test "${MONARCH_ROOTFS#/}" != "$MONARCH_ROOTFS"
   test -n "${MONARCH_ROOTFS_CACHE_ROOT:-}" && test "${MONARCH_ROOTFS_CACHE_ROOT#/}" != "$MONARCH_ROOTFS_CACHE_ROOT"
   scripts/rootfs/execution_contract.sh rootfs-current "$MONARCH_ROOTFS"
   ```

5. **Emit and inspect the bwrap plan before any heavy build.** Use an absolute
   temporary plan path and verify rootfs, cwd, mounts, env, and inner argv.

   ```sh
   plan="$(mktemp -p "${TMPDIR:-/tmp}" monarch-rootfs-plan.XXXXXX.yaml)"
   MONARCH_ROOTFS_EMIT_PLAN="$plan" \
   MONARCH_ROOTFS_EMIT_PLAN_ONLY=1 \
   MONARCH_ROOTFS="$MONARCH_ROOTFS" \
   MONARCH_ROOTFS_CACHE_ROOT="$MONARCH_ROOTFS_CACHE_ROOT" \
   scripts/run python -c 'print(1)'
   python - <<'PY' "$plan" "$MONARCH_ROOTFS_CACHE_ROOT"
   import sys, yaml
   plan = yaml.safe_load(open(sys.argv[1]))
   cache_root = sys.argv[2]
   assert plan["cwd"] == "/workspace/monarch"
   assert plan["env"]["CARGO_TARGET_DIR"].startswith("/workspace/monarch/target/bwrap/")
   mounts = {m["sandbox_path"]: m for m in plan["mounts"]}
   assert mounts["/workspace/monarch/scripts/rootfs/cache"]["host_path"] == cache_root
   assert mounts[plan["env"]["CARGO_TARGET_DIR"]]["host_path"].startswith(cache_root + "/target/bwrap/")
   PY
   ```

6. **Enter with a small probe before any heavy build.**

   ```sh
   MONARCH_ROOTFS="$MONARCH_ROOTFS" \
   MONARCH_ROOTFS_CACHE_ROOT="$MONARCH_ROOTFS_CACHE_ROOT" \
   scripts/run python - <<'PY'
   import os, subprocess, sys
   print(subprocess.check_output(
       ["scripts/rootfs/execution_contract.sh", "identify-controlled"],
       text=True,
   ).strip())
   print(os.getcwd())
   print(sys.executable)
   print(os.environ.get("CARGO_TARGET_DIR"))
   PY
   ```

7. **Sync the rootfs venv from inside the sandbox.**

   ```sh
   MONARCH_ROOTFS="$MONARCH_ROOTFS" \
   MONARCH_ROOTFS_CACHE_ROOT="$MONARCH_ROOTFS_CACHE_ROOT" \
   scripts/run scripts/rootfs/sync_test_environment.sh
   ```

8. **Watch storage while the build runs.** Heavy artifacts must appear under the
   relocated cache root, not the full checkout filesystem:

   ```sh
   du -sh "$MONARCH_ROOTFS_CACHE_ROOT" \
     "$MONARCH_ROOTFS_CACHE_ROOT/target/bwrap" \
     target 2>/dev/null
   df -h "$(dirname "$MONARCH_ROOTFS_CACHE_ROOT")" .
   ```

9. **Verify imports and CUDA from inside bwrap.**

   ```sh
   MONARCH_ROOTFS="$MONARCH_ROOTFS" \
   MONARCH_ROOTFS_CACHE_ROOT="$MONARCH_ROOTFS_CACHE_ROOT" \
   scripts/run python - <<'PY'
   import os, subprocess, sys
   print(subprocess.check_output(
       ["scripts/rootfs/execution_contract.sh", "identify-controlled"],
       text=True,
   ).strip())
   print(sys.executable)
   print(os.environ["CARGO_TARGET_DIR"])
   import monarch
   import monarch._rust_bindings as rust_bindings
   import torch
   print(monarch.__file__)
   print(getattr(rust_bindings, "__file__", "<builtin>"))
   print(torch.__version__, torch.cuda.is_available())
   PY
   ```

10. **Run focused rootfs tests.**

   ```sh
   MONARCH_ROOTFS="$MONARCH_ROOTFS" \
   MONARCH_ROOTFS_CACHE_ROOT="$MONARCH_ROOTFS_CACHE_ROOT" \
   scripts/run python -m pytest python/tests/test_rootfs_enter_plan.py -q
   ```

## Rootfs Design Rules

- Keep `scripts/run` the only normal Linux-local gateway.
- Keep launcher scripts that own outer bwrap, ports, or process lifecycle on the
  host side; they may call `enter_rootfs.sh`, but should not blindly run inside
  `scripts/run`.
- Emit resolved bwrap plans for debuggability. Plans should show rootfs, cwd,
  inner argv, repo projection mode, mounts, env, network, and GPU projection.
- Validate emitted plans against materialized config. Compare concrete
  `host_path` as well as sandbox path and mode.
- Create bind mount targets before launch. If the repo is already mounted at
  `/workspace/monarch`, create mountpoint directories under the host checkout;
  do not overlay `/workspace` with a new tmpfs.
- Bind the external cache root and the recipe-specific target as separate
  mounts. A single cache bind is not enough if `CARGO_TARGET_DIR` still resolves
  to the checkout filesystem.
- Use read-only repo projection for runtime launchers when the launcher does not
  need to mutate source.
- Keep mutable tool caches and build targets outside read-only rootfs exports.
- Pin CUDA compiler, headers, runtime linker names, and debug tools together.
  The synthetic CUDA tree must expose `bin/nvcc`, headers, `lib64`, and the
  unversioned `libcudart.so` linker name.

## Common Failures

- **A placeholder path is used literally:** replace `/data01/...` examples with
  discovered local absolute paths and prove them with `test -d`, `df -h`, and
  `rootfs-current` before use.
- **`No space left on device` under `target/bwrap`:** `CARGO_TARGET_DIR` still
  writes to the checkout filesystem. Add or fix the external cache-root bind and
  verify `du` growth under the external target.
- **`bwrap: execvp /workspace/...: No such file or directory`:** a tmpfs or bind
  overlaid `/workspace` or the command used a host-only absolute path. Preserve
  the repo projection and use sandbox paths or repo-relative entrypoints.
- **An emitted plan passes while mounting the wrong host directory:** validate
  concrete `host_path`, not only sandbox path and mode.
- **Tests pass on host but not under `scripts/run`:** the test may be assuming
  host-entry behavior while already inside the rootfs. For host-entry
  subprocess tests, clear `MONARCH_IN_ROOTFS` deliberately.
- **`-lcudart` or CUDA JIT link failures:** the synthetic CUDA tree is missing
  the unversioned runtime linker name or version-coherent compiler packages.
- **Native extension imports stale or missing:** rebuild/sync the rootfs venv
  inside bwrap and verify `monarch._rust_bindings` imports from the checkout.
- **A rootfs override works once but later drifts:** re-run
  `execution_contract.sh rootfs-current "$MONARCH_ROOTFS"` before trusting it.

## Completion Evidence

Do not report the rootfs as working until fresh evidence includes:

- `identify-controlled` prints `rootfs <recipe-sha256>` inside bwrap;
- `sys.executable` is `/workspace/monarch/.venv-rootfs/bin/python`;
- `CARGO_TARGET_DIR` is recipe-specific and routed to the intended host storage;
- an emitted plan proves the cache and target binds use the intended concrete
  host paths;
- `monarch`, `monarch._rust_bindings`, and `torch` import inside bwrap;
- `torch.cuda.is_available()` matches the intended GPU exposure;
- focused rootfs tests pass;
- no long-running setup/build processes are left behind.
