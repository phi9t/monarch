# End-to-End Repeatability Runner

Status: ready-for-agent

Type: task

Blocked by: 01, 02, 03, 04

## Goal

Compose SGLang, Dynamo, and the Responses adapter into one repeatable Local Run
that proves real GLM-5.2 inference and clean teardown across three cycles.

## Requirements

- Run the full Local Run Ladder from `spec.md`.
- Require valid SGLang `prepare-venv` and `prepare-model` records before live
  launch.
- Run three cycles by default.
- In each cycle, launch and probe SGLang, then Dynamo, then the Responses
  adapter.
- Run direct SGLang chat, Dynamo chat, Responses non-stream, Responses stream,
  and Responses tool-call probes.
- Tear down the Responses adapter, Dynamo, and SGLang in reverse order.
- Prove every allocated port is closed after each cycle.
- Prove no owned process orphans remain after each cycle.
- Write the full Contract Artifact tree under `glm52-serving-results/<run-id>/`.
- Write `summary.json` with `ok: true` only when every required gate passes.
- Return nonzero when any required cycle returns `ok: false`.

## Exclusions

- Do not claim benchmark, Harbor, SWE-bench, Terminal-Bench 2, HumanEval, MBPP,
  EvalPlus, or published conformance completion.
- Do not accept a single successful launch without teardown proof.
- Do not accept a `debug_mode: true` run that leaves processes alive.

## Verification Evidence

- Unit tests for repeatability summary success and failure states.
- Unit tests for post-launch failure teardown when `debug_mode: false`.
- Unit tests that reject `ok: false` cycle summaries.
- One live three-cycle run with `summary.json` reporting `ok: true`.
- Live artifacts showing real responses at all three layers and clean teardown
  after every cycle.

## Comments

2026-08-17 update:

- Still blocked by live SGLang generation. Do not proceed to Dynamo or
  Responses completion claims from unit tests, fake endpoints, or `/v1/models`
  alone.
- Live SGLang now launches from the governed rootfs and advertises
  `zai-org/GLM-5.2` on `/v1/models`, but native `POST /generate` times out
  after `300s` without text:
  `glm52-serving-results/glm52-sglang-local-20260817T130527Z-1-0e77aae2/`.
- Removing `--skip-server-warmup` did not fix generation:
  `glm52-serving-results/glm52-sglang-local-20260817T131416Z-1-3695c49e/`.
- The repeat runner now supports `--wait-for-gpu-free-seconds N`, which waits
  for visible GPUs to pass the same occupancy preflight before each cycle and
  records the result in `loop-summary.json`. This is only an opt-in launch
  race reducer; the strict launch preflight still runs immediately before
  process start.
- The repeat runner also supports `--gpu-free-stable-seconds N`, which requires
  repeated free-GPU samples over a stable window before each cycle. This still
  does not reserve GPUs, and the strict launch preflight remains authoritative.
- The temporary SGLang spec
  `.scratch/glm52-local-serving/tmp/sglang-local-dsa-decode-trtllm.yaml`
  changes only `--dsa-decode-backend flashmla_kv` to `trtllm`. With
  `--wait-for-gpu-free-seconds 300`, it launched after observing all eight GPUs
  free, `/v1/models` passed, and native `/generate` accepted the one-token
  request, but generation still timed out after `300s`:
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T133808Z-8b03fa09/`
  and
  `glm52-serving-results/glm52-sglang-local-20260817T133808Z-1-a16e9ec9/`.
- Active-profile diagnostic run
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T135226Z-39aba0e1/`
  reproduced the native `/generate` timeout and sent owned `SIGQUIT` before
  teardown. `stderr.log` recorded SGLang's five-second delayed crash-diagnostic
  path, so the launcher now waits six seconds after a successful diagnostic
  signal before teardown.
- A follow-up retry
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T140313Z-5d340f2b/`
  failed before process start because non-owned VLLM workers occupied the GPUs
  between the repeat wait and strict launch preflight. Do not claim this as a
  generation result.
- The active SGLang profile now has schema-owned crash dump diagnostics:
  `observability.crash_dump_folder: /run/glm52/crash-dumps`, materialized as
  `--crash-dump-folder /run/glm52/crash-dumps`. This is the next diagnostic
  support for the existing owned `SIGQUIT` probe-failure path; it does not
  change scheduler behavior and is not a generation fix by itself.
- Verification for that hardening used the `/data01` rootfs path and passed:
  `MONARCH_ROOTFS_CACHE_ROOT=/data01/builder/opt_draccus/monarch-rootfs-cache scripts/rootfs/enter_rootfs.sh --rootfs /data01/builder/opt_draccus/monarch-glm52-local-serving/rootfs/rootfs-ca484a4d579b45c0 -- uv run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`
  -> `118 passed`. The default `scripts/run` path failed before pytest because
  exporting the repo-local default rootfs hit `No space left on device`.
- No new live SGLang retry was attempted after the crash-dump hardening because
  all eight GPUs were occupied by non-owned `VLLM::Worker_TP*` processes. The
  no-kill/no-fallback policy still applies.
- The launcher now also includes crash dump inventory in the owned
  `SIGQUIT` diagnostic summary: sandbox path, resolved host path, and relative
  files under the dump directory after the six-second flush wait. This was
  verified with the same `/data01` rootfs test command (`118 passed`). A live
  retry is still blocked as of the latest check: all eight GPUs are occupied by
  non-owned `VLLM::Worker_TP*` processes using about `154470` MiB each.
- The next prepared one-variable SGLang diagnostic is
  `.scratch/glm52-local-serving/tmp/sglang-local-disable-overlap-schedule.yaml`.
  It changes only the active profile's `runtime.extra_args` by appending
  `--disable-overlap-schedule`. A materialization check against the `/data01`
  rootfs confirmed the launch argv delta is exactly that one flag:
  `extra= ['--disable-overlap-schedule']`, `missing= []`,
  `disable_overlap_count= 1`. Run this diagnostic only when the strict GPU
  preflight can own the visible GPUs.
- Attempted that diagnostic in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T142318Z-b2665a74/`.
  It failed before launch in the GPU-free wait gate:
  `GPU-free wait timed out after 300s: visible GPU 0 is already occupied by pid
  2026492 (VLLM::Worker_TP0_EP0, 96520 MiB)`. There is no child launch
  artifact and no generation result from this attempt. A current `nvidia-smi`
  check shows all eight GPUs occupied by non-owned `VLLM::Worker_TP*` processes
  using about `96520` MiB each.
- The repeat runner now preserves full GPU blocker snapshots for future wait
  failures. `GpuOccupancyError` carries a structured `blocked_gpus` list, and
  `gpu_wait` failure summaries write that list so blocked runs show every
  occupied visible GPU, not just the first GPU named in the error string.
  Verified under the `/data01` rootfs with
  `python/tests/test_glm52_sglang_runtime.py -q` -> `118 passed`.
- Follow-up zero-wait blocker capture
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T143755Z-0bff4e54/`
  failed before process start in the strict launch preflight. The child run
  directory contains materialization, rootfs plan, help preflight, and
  `launch-summary.json` artifacts, but no `process.yaml`, no server log, and no
  generation result. The repeat `loop-summary.json`
  records `cycles[0].launch.status: failed`,
  `cycles[0].teardown.status: not_started`, and
  `cycles[0].launch.blocked_gpus` for all eight visible GPUs, indices `0..7`.
  The occupying processes are non-owned `VLLM::Worker_TP*` workers, so the
  correct behavior remains fail loud, do not fall back, and do not kill them.
  This artifact proves blocker reporting, not SGLang inference.
- The `--disable-overlap-schedule` diagnostic was then executed with real GPU
  ownership in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T145416Z-8abdaf61/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T145416Z-1-2abac4b8/`.
  The repeat runner observed all eight visible GPUs free for the 60-second
  stable window, launched SGLang on the run-owned port `19000`, and `/v1/models`
  returned `zai-org/GLM-5.2`. The native `/generate` one-token probe still
  timed out after `300s`, so disabling overlap scheduling is not a sufficient
  fix. The launch summary sent owned `SIGQUIT`, recorded crash dump
  `n116-077-207/crash_dump_2026-08-17_15-02-58.pkl`, and teardown left the
  process record stopped with no active compute processes afterward. This is
  stronger live blocker evidence, but it still does not satisfy the
  repeatability-runner goal because no real generation completed.
- The follow-up `--moe-runner-backend triton` diagnostic ran in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T150751Z-1d162a9c/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T150751Z-1-4c87f083/`.
  It launched after the same 60-second all-GPU stable-free gate, `/v1/models`
  passed, and native `/generate` accepted the one-token request. The request did
  not complete: SGLang closed the HTTP connection after scheduler exceptions in
  `sglang/srt/utils/offloader.py:145` -> `torch.nn.utils.stateless.functional_call`,
  ending with tied `kv_b_proj.weight` keys and the message to consider
  `tie_weights=False`. Teardown left no owned process or compute app. This
  rules out Triton MoE as a direct fix under the current `cpu_offload_gb: 16`
  profile and makes CPU offload/tied weights the next diagnostic target.
- The no-CPU-offload diagnostic ran in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T151603Z-ad63b324/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T151603Z-1-3075c47d/`.
  The materialized command changed only `--cpu-offload-gb 16` to
  `--cpu-offload-gb 0`. It did not reach `/v1/models`: SGLang exited with
  `returncode=137`, and `stderr.log` records `torch.OutOfMemoryError: CUDA out
  of memory` during MoE weight allocation on GPU 2 after the process had used
  about `178.27 GiB`. Teardown reported the owned process group already stopped
  and no active compute apps remained. This rules out simply disabling CPU
  offload for the current GLM-5.2 memory profile.
- A patched-offloader `--moe-runner-backend triton` diagnostic ran in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T152148Z-8afefe11/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T152148Z-1-a2b9d576/`.
  The local SGLang venv patch changed `OffloaderV1` to call
  `functional_call(..., tie_weights=False)`; the offloader file hash changed
  from
  `1d89240584d56990174e22f31f1dd89d8585075607e14f6491a943dbd44aabed` to
  `0c6f79db8bc8cffcdf4152e10864b04963cb6844ff50a2435107d4e0ee127c3d`.
  The run launched after a 60-second all-GPU stable-free gate and `/v1/models`
  passed, but `/generate` still failed with `Remote end closed connection
  without response`. The tied-weight error disappeared. The new scheduler
  failure is a CPU/CUDA mismatch at
  `sglang/srt/models/deepseek_common/attention_forward_methods/forward_mla.py:710`,
  `q_nope_out = torch.bmm(q_nope.transpose(0, 1), self.w_kc)`, with `self.w_kc`
  on CPU and request tensors on CUDA across TP ranks. Source inspection shows
  `w_kc` and `w_vc` are plain tensor attributes assigned by the DeepSeek weight
  loader, not registered parameters or buffers, so the next diagnostic target is
  `OffloaderV1`'s `module.state_dict()`-only device-state construction for
  absorbed MLA side tensors. This is live blocker evidence, not completion
  evidence.
- A second local SGLang venv patch extended `OffloaderV1` to move absorbed-MLA
  plain tensor attributes (`w_kc`, `w_vc`, and related scale tensors) to the
  target device during the wrapped forward and restore them afterward. The
  patched `offloader.py` hash was
  `7d9b58db50c64a06561c3e2ef00ccc06c61e4e8172f0178b23e630db2166550a`, and a
  rootfs-projected SGLang venv CUDA micro-check verified CPU `w_kc` move/restore
  behavior. The live diagnostic then ran in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T153422Z-2270bbbc/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T153422Z-1-e2856b57/`.
  It launched after the 60-second all-GPU stable-free gate, `/v1/models` passed,
  and native `/generate` completed for the first time: `probes/generate.json`
  records content `"You"` from one generated token (`payload.text` was
  `" You"`, `completion_tokens: 1`, `finish_reason.type: length`,
  `e2e_latency: 158.43309165816754`). The run also wrote completions and chat
  probe artifacts. However, the repeat wrapper exited nonzero during successful
  teardown because it validated `process.yaml` against the pre-launch
  materialized config instead of the post-model-cache config that launch wrote;
  the error was `process record outer_argv must match materialized config`.
  Port `19000` was no longer listening afterward, and no persistent run-owned
  compute process remained. This proves direct live SGLang generation but still
  does not close this repeatability issue until a clean launch/probe/teardown
  cycle passes.
- After patching the repeat runner to reload the post-launch materialized config
  for successful teardown, a clean-repeat retry ran in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T154435Z-42e6204f/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T154435Z-1-76692ead/`.
  It did not reach the fixed successful-teardown path. SGLang exited before
  `/v1/models` with `returncode=137`; `stderr.log` records SGLang's
  memory-balance guard, `RuntimeError: The memory capacity is unbalanced. Some
  GPUs may be occupied by other processes`, with `pre_model_load_memory` around
  `147.9 GiB` and the allowed `local_gpu_memory * 0.9` threshold around
  `158.6 GiB`. The owned process record ended stopped, teardown returned
  `already_stopped`, and port `19000` was not listening afterward. A later GPU
  sample showed a non-owned `python3 xperf_plugin/unit_test/tf/test_mfalcon.py`
  process using about `28.5 GiB` on GPU 5; it was not killed. This is external
  GPU-occupancy/startup blocker evidence, not a generation regression.
- The governed SGLang venv preparation path now applies and records the
  offloader patch instead of relying on an ad hoc site-packages edit. The
  refreshed `glm52-serving-results/prepare-venv/sglang-venv.json` records
  `checks.offloader_patch.patch_id:
  glm52-offloader-v1-plain-tensor-attrs-v1`, `changed: true`, and
  `sha256_after:
  9ac28bc702ae84608f3ebbe80987e4f382d4e8e9dc8a8f1920a1947091b41097`.
  The patcher was extended to handle the single-line upstream
  `functional_call(module, device_state, args=args, kwargs=kwargs)` form found
  in the installed SGLang package; focused regression coverage and the full
  SGLang runtime test file passed under the `/data01` rootfs.
- A clean governed SGLang-only three-cycle repeat then passed in
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T155846Z-1cfe6ce1/`.
  `loop-summary.json` reports `status: passed` with all three cycles
  `launch_passed` and `teardown_passed`. The child runs were:
  `glm52-serving-results/glm52-sglang-local-20260817T155846Z-1-df427599/`
  on port `19000`,
  `glm52-serving-results/glm52-sglang-local-20260817T160433Z-2-e49b1e4a/`
  on port `19001`, and
  `glm52-serving-results/glm52-sglang-local-20260817T161010Z-3-e827a64c/`
  on port `19002`.
- Each of those three SGLang cycles wrote `/v1/models`, native `/generate`,
  `/v1/completions`, and `/v1/chat/completions` probe artifacts. `/v1/models`
  returned `zai-org/GLM-5.2`; `/generate` produced one token with content
  `"You"` and `finish_reason.type: length`; `/v1/completions` produced
  `"You"` for model `zai-org/GLM-5.2`; and `/v1/chat/completions` produced
  `"OK"` for model `zai-org/GLM-5.2`. Every child `process.yaml` ended with
  `status: stopped`, and a post-run `nvidia-smi` sample showed zero GPU memory
  used on GPUs `0..7` with no compute apps listed.
- This closes the SGLang-only launch/probe/teardown repeatability blocker for
  the current patched-offloader `--moe-runner-backend triton` profile. It does
  not close this full end-to-end issue: Dynamo, the Responses adapter,
  Responses streaming/tool-call probes, Harbor, SWE-bench, Terminal-Bench 2,
  EvalPlus, and published conformance still require their own real live
  evidence.
