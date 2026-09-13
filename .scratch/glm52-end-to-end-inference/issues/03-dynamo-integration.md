# Dynamo Integration

Status: ready-for-agent

Type: task

Blocked by: 01, 02

## Goal

Launch a local Dynamo frontend that connects only to the materialized,
run-owned SGLang endpoint, then prove Chat Completions inference through Dynamo.

## Requirements

- Consume the Dynamo component slice from `materialized-inference.yaml`.
- Launch Dynamo only after the SGLang component is owned and its probes passed.
- Use the materialized SGLang OpenAI base URL as the only upstream.
- Reject ambient Dynamo, SGLang, or OpenAI URLs.
- Record Dynamo argv, env, config files, stdout, stderr, endpoint URL, and
  process record.
- Probe Dynamo `GET /v1/models`.
- Probe Dynamo `POST /v1/chat/completions`.
- Require the observed model name to match the SGLang served model name.
- Fail if SGLang is no longer owned and healthy in the same run.
- Tear Dynamo down through the shared process-record contract.

## Exclusions

- Do not launch the Responses adapter.
- Do not run Responses probes.
- Do not add benchmark scoring.
- Do not accept direct Dynamo evidence from an operator-started ambient service.

## Verification Evidence

- Unit tests using a controlled fake SGLang upstream for command materialization
  and failure paths.
- Unit tests that reject ambient upstream URLs and disallowed ports.
- Unit tests that reject model identity drift between SGLang and Dynamo.
- SGLang-only live repeatability is available. The host-control Dynamo venv and
  `dynamo.frontend` / `dynamo.sglang` import probes now pass from the
  materialized venv. Live Dynamo evidence remains blocked until the parent run
  can first prove healthy real SGLang generation in the same run.
- Parent runtime tests now cover the schema-owned two-process Dynamo topology:
  worker launch before frontend launch, normal owned teardown for both process
  records, and launch-probe failure cleanup for both process groups before the
  exception is re-raised.

## Comments

2026-08-17 parent-runner prerequisite hardening:

- The parent inference runtime now validates Dynamo prerequisites before
  starting SGLang, so a known missing Dynamo command does not spend a live GPU
  SGLang bringup.
- Earlier placeholder-only proxy argv is rejected before `Popen`; that
  hardening remains in place for configs that use unsupported proxy-style
  frontend flags.
- Fresh host-control blocker run:
  `glm52-serving-results/glm52-inference-dynamo-preflight-20260817T162622Z/`.
  `components/dynamo/environment.json` records
  `status=missing_prerequisite`, `reason=placeholder_argv`,
  `popen_attempted=false`, endpoint
  `http://127.0.0.1:19001/v1`, and upstream
  `http://127.0.0.1:19000/v1`.
- This is not Dynamo live evidence. It is a fail-fast contract artifact that
  proves the parent runner no longer reaches `Popen` or SGLang launch when the
  Dynamo launch command is still placeholder-only.

2026-08-17 Dynamo package and argv surface inspection:

- PyPI wheel inspection found `ai-dynamo==1.4.0` and
  `ai-dynamo-runtime==1.4.0`. The `ai-dynamo` wheel contains
  `dynamo.frontend.__main__`, `dynamo.frontend.main`,
  `dynamo.sglang.__main__`, and `dynamo.sglang.main`, but no console-script
  entry point.
- `python -m dynamo.frontend` is therefore a real module when `ai-dynamo` is
  installed, but the current materialized argv is still not a valid runnable
  frontend contract. The frontend parser uses flags such as `--http-host`,
  `--http-port`, `--model-name`, `--discovery-backend`, `--request-plane`, and
  `--dyn-chat-processor`; it does not expose the parent runner's current
  `--host`, `--port`, `--upstream-url`, or `--model` proxy-style flags.
- The parent runtime now rejects unsupported `dynamo.frontend` flags before
  `Popen` with `reason=unsupported_argv_flag`, so installing `ai-dynamo` cannot
  silently advance to a predictable CLI parse failure.

2026-08-17 schema-backed Dynamo topology materialization:

- `.scratch/glm52-local-serving/config/inference-local.yaml` now declares a
  Dynamo topology instead of proxy-style argv: `mode=local_frontend_worker`,
  `package=ai-dynamo`, `discovery_backend=file`, `request_plane=tcp`,
  `namespace=glm52`, frontend module `dynamo.frontend`, and worker module
  `dynamo.sglang`.
- Materialization derives the frontend command as
  `python -m dynamo.frontend --http-host 127.0.0.1 --http-port <run-port>
  --model-name zai-org/GLM-5.2 --discovery-backend file --request-plane tcp
  --namespace glm52 --dyn-chat-processor sglang`.
- Materialization also records the worker command as
  `python -m dynamo.sglang --model-path zai-org/GLM-5.2 --served-model-name
  zai-org/GLM-5.2 --discovery-backend file --request-plane tcp --namespace
  glm52 --endpoint dyn://glm52.backend.generate --endpoint-types
  chat,completions`.
- Fresh current-config blocker run:
  `glm52-serving-results/glm52-inference-dynamo-topology-20260817T164445Z/`.
  `components/dynamo/environment.json` records
  `status=missing_prerequisite`, `reason=missing_module`,
  `module=dynamo.frontend`, and `popen_attempted=false`.
- This is not Dynamo live evidence. It proves the parent runner now reaches the
  schema-backed topology contract and fails loudly before `Popen` because
  `ai-dynamo` is not installed in the host-control Python environment.

2026-08-17 host-control Dynamo venv and parent-run blocker update:

- The parent declared config now materializes
  `components.dynamo_frontend.topology.host_control_venv` as
  `cache://glm52/venvs/dynamo`.
- `glm52-serving-results/prepare-dynamo-venv-20260817T165525Z/components/dynamo/dynamo-venv.json`
  records a run-owned host-control venv at
  `/var/tmp/monarch-glm52-local-serving-cache/glm52/venvs/dynamo`, installed
  packages `ai-dynamo==1.4.0` and `ai-dynamo-runtime==1.4.0`, and successful
  import probes for `dynamo.frontend` and `dynamo.sglang` through that venv's
  Python.
- `glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z/materialized.yaml`
  uses strict run-owned ports `19000`, `19001`, and `19002`; the materialized
  Dynamo frontend and worker argv use the resolved Dynamo venv Python rather
  than ambient host Python.
- `glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z/components/dynamo/environment.json`
  records `status=ok`, `reason=python_module_importable`,
  `module=dynamo.frontend`, and `popen_attempted=false`. This proves the
  Dynamo package prerequisite is no longer the active blocker.
- The same parent launch then started the owned SGLang child run
  `glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z-sglang/`.
  SGLang advertised `zai-org/GLM-5.2` from `/v1/models` on the run-owned port
  `19000`, but the real generation probe timed out after `300s`.
- `launch-summary.json` records `status=launch_failed`,
  `error="generate probe timed out after 300s"`, a schema-owned diagnostic
  `SIGQUIT` to process group `2622371`, and a crash dump under
  `crash-dumps/n116-077-207/crash_dump_2026-08-17_17-05-09.pkl`. The SGLang
  stderr log records `Health check failed. Server couldn't get a response from
  detokenizer for last 20 seconds`.
- Cleanup was checked after the failed run: `process.yaml` records
  `status=stopped`, the recorded process group `2622371` is gone from the host
  process table, and a host `nvidia-smi --query-compute-apps` check returned no
  active compute processes. Older defunct `sglang::schedul` /
  `sglang::detoken` entries remain from prior runs, but they are zombie
  processes with no GPU allocation and are not live SGLang services.
- This is still not Dynamo live inference evidence. It advances the blocker
  from missing Dynamo installation/topology to parent-run SGLang generation
  health before Dynamo frontend and worker launch.

2026-08-17 parent topology and SGLang profile alignment:

- The parent-referenced active SGLang config now includes the same
  `--moe-runner-backend triton` runtime extra arg that was present in the
  successful SGLang-only repeat artifact
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T155846Z-1cfe6ce1/`.
  The previous parent failure
  `glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z-sglang/`
  lacked that argument in `materialized-sglang-runtime.yaml`, while the
  successful child run
  `glm52-serving-results/glm52-sglang-local-20260817T155846Z-1-df427599/`
  included it and completed `/generate`, `/v1/completions`, and
  `/v1/chat/completions`.
- Parent materialization now preserves that active SGLang profile. Fresh
  materialization artifact:
  `glm52-serving-results/glm52-inference-topology-materialize-20260817T171737Z/materialized.yaml`.
  The derived child SGLang launch tail is
  `--cuda-graph-backend-decode=disabled --skip-server-warmup
  --moe-runner-backend triton`, and the strict parent ports are still
  `19000`, `19001`, and `19002`.
- The parent Dynamo launcher now starts the schema-owned local topology as two
  host-controlled processes: the `dynamo.sglang` worker first, then
  `dynamo.frontend`. The materialized component records
  `worker_process_record` at
  `repo://glm52-serving-results/<run-id>/components/dynamo/worker-process.json`,
  and the worker argv uses endpoint `dyn://glm52.backend.generate`.
- Focused verification:
  `MONARCH_ROOTFS=/data01/builder/opt_draccus/monarch-glm52-local-serving/rootfs/rootfs-ca484a4d579b45c0 MONARCH_ROOTFS_CACHE_ROOT=/data01/builder/opt_draccus/monarch-rootfs-cache scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q`
  reported `39 passed` after adding probe-failure cleanup coverage.
- The launcher now marks and stops both owned Dynamo process records with
  `stop_reason=launch_failed` when the Dynamo probe fails after worker and
  frontend startup. Teardown remains process-record based; this is unit-tested
  with fake process groups and does not authorize killing unowned host
  processes.
- No new live parent run was attempted after this patch because a host GPU
  preflight showed GPU 4 occupied by non-owned pid `2672717`
  (`/opt/tiger/b200/bin/python`, about `12898` MiB). A live all-8-GPU parent
  run must wait for a clean strict-preflight window rather than killing or
  reusing a non-owned process.
- This still is not Dynamo live inference evidence. It removes the stale parent
  SGLang profile mismatch and the single-process Dynamo launcher gap so the
  next live attempt can reach the real local Dynamo frontend plus worker
  topology once the GPUs are clean.
