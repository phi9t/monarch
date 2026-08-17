# GLM-5.2 SGLang Rootfs Hardening Spec

Status: ready-for-human

Created: 2026-08-17T00:00:00Z

## Purpose

This milestone hardens the governed bwrap rootfs runtime used to run local
SGLang GLM-5.2. It turns the recently landed generic rootfs sandbox contract
into a SGLang-specific execution contract that can prepare dependencies, prove
model cache readiness, launch on a custom run-owned port, probe real inference,
and tear down repeatedly without using ambient services or host fallbacks.

The milestone is narrower than the full GLM-5.2 local serving workstream. It
does not launch Dynamo, the Responses adapter, Harbor, EvalPlus, or benchmark
scoring. It produces the hardened SGLang substrate those later milestones can
depend on.

## First Principle

No fallback. Fail fast, fail loud.

The launcher must not fall back to host Python, host packages, ambient default
ports, implicit model downloads, fake endpoints, fixture harnesses, or partial
success states. Any missing package, stale rootfs, wrong mount, occupied port,
command drift, model-cache miss, model identity mismatch, failed teardown, or
unexpected live service must produce a nonzero result and a concrete blocker
artifact.

## Scope

### In Scope

- Source-backed schema for the GLM-5.2 SGLang rootfs overlay.
- Portable declared YAML that contains logical refs only for host-side paths.
- Machine-local resolver YAML for concrete host roots.
- Materialized runtime YAML that explicitly references every SGLang runtime
  field used to build the final command.
- Resolved-path evidence with concrete host paths for one run.
- Resolved bwrap plan validation using `scripts/rootfs/rootfs_sandbox_config.py`.
- Rootfs-managed SGLang virtual environment under `/cache/glm52/venvs/sglang`.
- Rootfs-managed Hugging Face cache under `/cache/glm52/hf-home`.
- Separate SGLang package preparation and model-cache preparation commands.
- Preflight that refuses to launch if preparation evidence is missing or stale.
- Strict run-owned port allocation from the declared range.
- Launch command generation from the materialized config only.
- Actual command, environment, bwrap plan, and process record validation.
- `/v1/models` and `/v1/chat/completions` probes against the allocated custom
  port.
- Repeated launch/probe/teardown cycles with proof that the port and process
  group are gone after each cycle.
- Debug logging and local telemetry artifacts for SGLang bringup diagnosis.

### Out of Scope

- Dynamo frontend launch or Dynamo-to-SGLang wiring.
- Responses adapter launch.
- Codex provider configuration.
- Harbor Terminal-Bench 2 or SWE-bench execution.
- HumanEval, MBPP, EvalPlus, GSM8K, AIME, RULER, needle, or published-score
  conformance.
- Kubernetes, remote hosts, or multi-node serving.
- Rebuilding the generic rootfs schema module unless a concrete SGLang contract
  bug is found.

## Existing Building Blocks

- `scripts/rootfs/rootfs_sandbox_config.py` owns the generic bwrap schema,
  mount plan materialization, bwrap argv generation, bwrap argv parsing, and
  validation that concrete host mounts and env values match the plan.
- `scripts/rootfs/verify_rootfs.py` owns structural rootfs verification.
- `scripts/rootfs/enter_rootfs.sh` can emit the resolved bwrap plan and validate
  the generated bwrap argv before launch.
- `scripts/glm52_sglang_runtime.py` already contains initial GLM-5.2 SGLang
  schema, materialization, SGLang help validation, `/v1/models` parsing, model
  snapshot validation, rootfs-plan validation, and teardown-policy helpers.
- `.scratch/glm52-local-serving/config/sglang-local.yaml` is the current
  declared SGLang example.
- `.scratch/glm52-local-serving/config/local-environment.example.yaml` is the
  current machine-local resolver example.

## Architecture

The hardened flow is:

```text
declared SGLang YAML
  + local environment YAML
  -> SGLang rootfs overlay schema validation
  -> prepare SGLang venv inside bwrap
  -> prepare model cache inside bwrap
  -> materialized runtime YAML
  -> resolved bwrap plan emission
  -> command and mount drift validation
  -> launch SGLang on allocated custom port
  -> live models and chat probes
  -> process-group teardown
  -> post-teardown port/process proof
```

The GLM-5.2 SGLang overlay must consume the generic rootfs contract instead of
reimplementing it. The overlay declares additional SGLang-specific roots,
environment values, package checks, model-cache checks, and launch probes. The
generic rootfs module remains responsible for translating a materialized sandbox
plan into the exact bwrap argv and validating that translation.

## Path Model

Portable declared config and portable materialized config must not encode
absolute host paths for host layout fields. They use logical refs:

- `repo://...`
- `cache://...`
- `temp://...`
- `run://...`
- `rootfs://...`

Machine-local resolver config may contain concrete absolute host paths. Resolved
evidence may contain concrete absolute host paths. Sandbox paths may be absolute
because they are part of the enforced bwrap protocol.

Required SGLang sandbox paths:

- `/cache/glm52/venvs/sglang`
- `/cache/glm52/hf-home`
- `/cache/glm52/sglang`
- `/workspace/monarch`
- `/workspace/monarch/.scratch/glm52-local-serving`

The rootfs overlay verifier must reject:

- relative local resolver paths;
- portable config containing absolute host paths;
- cache roots inside the rootfs export;
- missing bind targets;
- mounts whose sandbox path matches but whose concrete host path is wrong;
- SGLang venvs outside `/cache/glm52/venvs/sglang`;
- HF caches outside `/cache/glm52/hf-home`.

## Schema Requirements

Add source-backed schema types to `scripts/glm52_sglang_runtime.py` or a focused
helper imported by it. The public GLM runtime entrypoint remains
`scripts/glm52_sglang_runtime.py`.

Required new or extended schema concepts:

- `SglangRootfsOverlaySpec`
- `SglangVenvSpec`
- `ModelCacheSpec`
- `SglangPreparationRecord`
- `ModelCacheRecord`
- `SglangRootfsVerificationReport`
- `LaunchCycleRecord`
- `RepeatabilitySummary`

The schema must reject:

- unknown fields;
- nullable values where concrete values are required;
- shell command strings;
- unstructured environment strings;
- absolute host paths in portable fields;
- default or ambient ports `8000`, `8080`, or `18080`;
- `allow_fallback: true`;
- `fail_fast: false`;
- `leave_running_on_failure: true` unless `debug_mode: true`;
- launch configs that omit `--served-model-name`;
- launch configs that omit the allocated port;
- launch configs that would trigger model download at launch time.

## Preparation Contract

SGLang package preparation is a separate command:

```text
scripts/run_glm52_sglang_runtime.sh prepare-venv --declared <yaml> --local-env <yaml>
```

It must:

- run inside the governed bwrap rootfs;
- create or update `/cache/glm52/venvs/sglang`;
- install the declared SGLang package set through `uv`;
- write a preparation record with package versions, Python executable,
  `sys.prefix`, CUDA visibility, command argv, rootfs recipe digest, and bwrap
  plan digest;
- validate `python -m sglang.launch_server --help` includes
  `--served-model-name`;
- fail if the active Python executable is not inside `/cache/glm52/venvs/sglang`.

Model cache preparation is a separate command:

```text
scripts/run_glm52_sglang_runtime.sh prepare-model --declared <yaml> --local-env <yaml>
```

It must:

- run inside the governed bwrap rootfs;
- use `HF_HOME=/cache/glm52/hf-home`;
- materialize a concrete model snapshot path;
- validate `model.safetensors.index.json`, non-empty shard mapping, required
  shard files, and metadata readability;
- write a model cache record with repo ID, snapshot path, revision when known,
  shard count, missing shard count, rootfs recipe digest, and bwrap plan digest;
- fail if launch would need to download the model.

## Launch Contract

Launch uses the materialized runtime config only. The final SGLang command must
be a structured argv array. It must include:

- the rootfs-managed SGLang Python executable;
- `-m sglang.launch_server`;
- `--host 127.0.0.1`;
- `--port <allocated custom port>`;
- `--model-path <prepared snapshot or declared explicit path>`;
- `--served-model-name <declared served model name>`;
- `--tp-size <declared tensor_parallel_size>`;
- declared dtype, context length, memory, and request limits;
- only declared extra args.

Before launch, the launcher must:

- verify rootfs structure;
- verify SGLang venv preparation record;
- verify model cache preparation record;
- allocate a port from the strict run-owned range;
- reject occupied ports instead of moving silently to a fallback;
- emit the resolved bwrap plan;
- validate rootfs, repo projection mode, mounts, host paths, env, cwd, network,
  GPU policy, outer argv, and inner argv against the materialized config;
- write a process record before waiting for readiness.

## Probe Contract

Each launch cycle must probe:

- `GET /v1/models`, requiring the declared `served_model_name` and intersection
  with `expected_model_ids`;
- `POST /v1/chat/completions`, requiring HTTP 200 and non-empty assistant
  content or a valid structured output item.

The probes must use the allocated custom port from the materialized config. They
must never try `8000`, `8080`, `18080`, or any endpoint not present in the
materialized config.

## Teardown Contract

When `debug_mode=false`, every post-launch failure must attempt teardown in a
`finally` path. Teardown must:

- target the recorded process group;
- refuse to kill a process if command guards do not match the process record;
- wait for exit;
- escalate from `SIGTERM` to `SIGKILL` only after a declared timeout;
- verify the process group is gone;
- verify the allocated port is closed;
- write a teardown summary.

When `debug_mode=true` and `leave_running_on_failure=true`, teardown may be
skipped only after writing an explicit debug-preserve artifact that names the
process group, port, logs, and cleanup command.

## Acceptance Criteria

The milestone is complete when these are true:

- Source-backed schema tests pass for declared config, local resolver config,
  SGLang rootfs overlay config, preparation records, materialized runtime
  config, launch cycle records, and repeatability summary.
- Rootfs overlay tests reject wrong host mounts, wrong cache mounts, wrong venv
  path, wrong HF cache path, missing `--served-model-name`, ambient ports, and
  command drift.
- `prepare-venv` succeeds inside bwrap and writes package evidence.
- `prepare-model` succeeds inside bwrap or fails with a prepare-required blocker
  artifact before launch.
- With a prepared model cache, the launcher completes three cycles from the same
  declared spec using non-default custom ports.
- Each cycle records resolved config, emitted bwrap plan, actual argv/env,
  process record, `/v1/models` probe, chat probe, teardown summary, and
  post-teardown port/process proof.
- The final summary exits zero only if all cycles pass.

## Implementation Tickets

- `issues/01-rootfs-overlay-schema.md`
- `issues/02-prepare-sglang-venv-and-model-cache.md`
- `issues/03-repeatable-live-launch-teardown.md`
