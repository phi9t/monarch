# Schema-Driven Local SGLang Runtime Milestone

Status: ready-for-human

Created: 2026-08-16T00:00:00Z

## Purpose

This milestone proves that Monarch can launch and tear down a local
SGLang-backed GLM-5.2 OpenAI-compatible Chat Completions endpoint repeatedly and
consistently. It is the first live-serving gate for the larger GLM-5.2 local
serving workstream.

The milestone deliberately excludes Dynamo, the Responses adapter, Harbor,
EvalPlus, benchmark scoring, and published conformance. Those gates remain
blocked until this milestone produces live SGLang endpoint evidence on an
explicit custom port.

## Retrospective Input

The previous workstream added useful verifier, adapter, benchmark, Harbor, and
manifest guardrails, but the live proof path stalled because no real GLM-backed
endpoint was available. Fresh artifacts showed that ambient default ports were
not trustworthy:

- `127.0.0.1:8000` refused Chat connections.
- `127.0.0.1:8080` served SearXNG and returned HTTP 404 for `/v1/models`.

The next plan must not probe conventional ports as implicit defaults. It must
allocate GLM-owned ports from a declared range, materialize the exact runtime
contract, launch only from that contract, and fail loudly on any drift.

## First Principle

No fallback. Fail fast, fail loud.

No command may fall back to an ambient host service, an implicit default port,
an environment-derived model ID, a fake endpoint, a fixture path, or a partial
success state. If a required field is absent, a port is occupied, the materialized
command drifts from the schema, the sandbox layout is invalid, or the live
service does not prove the expected model identity, the run exits nonzero and
writes blocker evidence.

## Scope

### In Scope

- Source-backed schema definitions for the declared launch spec.
- Source-backed schema definitions for the materialized SGLang runtime config.
- Source-backed schema definitions for process records, command records, probe
  records, and launch/teardown summaries.
- Strict run-owned port allocation from a declared range.
- Materialization of concrete SGLang runtime config before launch.
- Explicit bwrap rootfs sandbox configuration, resolved rootfs plan emission,
  mount projection, and in-sandbox directory layout.
- Launching SGLang only from the materialized runtime config.
- Validation that the final launched command and environment match the
  materialized runtime config.
- Readiness probes for `/v1/models` and `/v1/chat/completions`.
- Teardown using recorded process-group and materialized runtime evidence.
- Repeat launch/probe/teardown loops from the same declared spec.
- Debug-mode, logging, and local telemetry controls for diagnosing SGLang as a
  foundation serving technology.
- Run-scoped artifacts that show the declared spec, materialized config,
  resolved local paths, sandbox protocol, actual launch command, probe results,
  process metadata, and teardown evidence.

### Out of Scope

- Dynamo launch or Dynamo-to-SGLang wiring.
- Responses adapter launch.
- Codex provider configuration.
- Harbor Terminal-Bench 2 or SWE-bench execution.
- HumanEval, MBPP, EvalPlus, GSM8K, AIME, RULER, or needle-smoke scoring.
- Published-score conformance.
- Kubernetes, remote hosts, or multi-node deployment.

## Glossary

- **Declared launch spec**: Human-authored YAML that describes intent. It may
  declare a strict port allocation range, but it must not contain hidden
  defaults.
- **Materialized runtime config**: Machine-written YAML that contains only
  concrete executable values. The launcher executes this file, not the declared
  spec.
- **Local environment config**: Machine-local resolver input that maps logical
  path roots such as `repo://`, `run://`, `cache://`, and `temp://` to actual
  host paths. It is not the portable runtime contract.
- **Resolved local paths**: Evidence that records the host paths produced by the
  local environment resolver for one run.
- **Sandbox protocol**: The bwrap/rootfs contract: rootfs entry, mount map,
  sandbox paths, working directory, GPU policy, network policy, and environment
  allowlist.
- **Resolved rootfs plan**: Machine-written output from the rootfs entrypoint
  that describes the actual bwrap/rootfs argv, mounts, cwd, env, GPU/device
  projection, and network policy before launch.
- **Outer command**: The host-visible command that enters the bwrap rootfs
  sandbox.
- **Inner command**: The in-sandbox command that launches SGLang.
- **Command drift**: Any mismatch between the materialized runtime config and
  the actual argv/env/process record used at launch.

## Architecture

The milestone has five phases:

```text
declared YAML spec
  -> schema validation
  -> strict port allocation and path resolution
  -> materialized SGLang runtime YAML
  -> sandboxed SGLang launch
  -> live probes and teardown evidence
```

The declared spec is portable and intentionally does not contain absolute host
paths. The materialized runtime config is also portable for host layout fields:
it uses logical path references. A separate resolved-path evidence file records
machine-local absolute host paths after applying the local environment config.

The only absolute paths allowed in portable config are sandbox paths, because
they are part of the bwrap/rootfs protocol enforced at launch.

## Schema Model

The YAML files must be backed by source code. Examples are not the contract.

The schema module should define typed models for:

- `DeclaredSglangLaunchSpec`
- `PortPolicy`
- `ModelSpec`
- `SglangRuntimeSpec`
- `ObservabilitySpec`
- `ProbeSpec`
- `ArtifactSpec`
- `LocalEnvironmentConfig`
- `MaterializedSglangRuntimeConfig`
- `HostLayout`
- `SandboxSpec`
- `SandboxMount`
- `LaunchCommand`
- `ResolvedRootfsPlan`
- `ProcessRecord`
- `ProbeRecord`
- `LaunchSummary`
- `TeardownSummary`

The parser must reject:

- missing required fields;
- unknown fields;
- nullable values where a concrete value is required;
- absolute host paths in portable host-layout fields;
- disallowed fallback ports;
- fallback mode flags;
- implicit model IDs;
- implicit model paths;
- implicit bind hosts;
- implicit cache, temp, or results directories;
- command strings that require shell parsing.

All executable commands must be represented as structured argv arrays and
explicit env maps. The launcher may render those arrays at the final subprocess
boundary, but it must never execute a shell command assembled from free-form
strings.

## Declared Launch Spec

The declared spec is human-authored YAML. It describes intent and policy, not
the final launch command.

Example shape:

```yaml
schema_version: 1
run_group: glm52-sglang-local
fail_fast: true
allow_fallback: false

port_policy:
  mode: strict_run_owned_range
  bind_host: 127.0.0.1
  range_start: 19000
  range_end: 19100
  disallowed_ports:
    - 8000
    - 8080
    - 18080

model:
  id: zai-org/GLM-5.2
  path: zai-org/GLM-5.2
  served_model_name: zai-org/GLM-5.2
  expected_model_ids:
    - zai-org/GLM-5.2

runtime:
  kind: sglang_openai
  cuda_visible_devices: "0,1,2,3,4,5,6,7"
  tensor_parallel_size: 8
  dtype: bfloat16
  context_length: 262144
  extra_args: []

sandbox:
  kind: bwrap_rootfs
  rootfs_ref: rootfs://monarch-default
  cwd: /workspace/monarch
  network: host_loopback_required
  gpu: required

observability:
  debug_mode: false
  leave_running_on_failure: false
  log_level: info
  telemetry:
    local_artifacts: true
    remote_export: false

local_paths:
  results_root: repo://glm52-serving-results
  scratch_root: repo://.scratch/glm52-local-serving
  cache_root: cache://glm52-local-serving
  temp_root: temp://glm52-local-serving

probes:
  startup_timeout_seconds: 900
  models_required: true
  chat_required: true
  chat_template_kwargs:
    enable_thinking: false

repeatability:
  cycles: 3
```

Required validation:

- `fail_fast` must be `true`.
- `allow_fallback` must be `false`.
- `port_policy.mode` must be `strict_run_owned_range`.
- `range_start` and `range_end` must be explicit and valid.
- `disallowed_ports` must include `8000`, `8080`, and `18080`.
- `model.id`, `model.path`, `model.served_model_name`, and
  `model.expected_model_ids` must be explicit.
- `model.served_model_name` must be included in `model.expected_model_ids`.
- `runtime.kind` must be `sglang_openai`.
- `sandbox.kind` must be `bwrap_rootfs`.
- `observability.debug_mode` and `observability.leave_running_on_failure` must be
  explicit.
- Host-side path fields must use logical refs, not absolute host paths.
- Sandbox paths may be absolute because they are protocol paths inside the
  governed rootfs sandbox.

## Local Environment Config

The local environment config is separate from the declared spec and
materialized runtime config. It maps logical roots to host paths for the current
checkout and machine.

Example shape:

```yaml
schema_version: 1
roots:
  repo: <absolute-path-to-monarch-checkout>
  cache: <absolute-path-to-local-glm52-cache>
  temp: <absolute-path-to-local-glm52-temp>
rootfs:
  monarch-default: <absolute-path-to-built-bwrap-rootfs>
```

This file is machine-local resolver input. Operators must copy the example and
fill concrete absolute host paths outside the committed portable runtime config.
Those paths may appear in run evidence as resolved local paths, but they must
not replace logical refs in the declared runtime config.

## Materialized Runtime Config

The materialized runtime config is machine-written YAML. It is written before
launch and is the only executable input to the launcher.

Example shape:

```yaml
schema_version: 1
run_id: glm52-sglang-local-20260816T000000Z-001
run_group: glm52-sglang-local
fail_fast: true
allow_fallback: false

service:
  kind: sglang_openai
  bind_host: 127.0.0.1
  port: 19017
  base_url: http://127.0.0.1:19017/v1
  expected_model_ids:
    - zai-org/GLM-5.2

model:
  id: zai-org/GLM-5.2
  path: zai-org/GLM-5.2
  served_model_name: zai-org/GLM-5.2
  expected_model_ids:
    - zai-org/GLM-5.2

runtime:
  kind: sglang_openai
  cuda_visible_devices: "0,1,2,3,4,5,6,7"
  tensor_parallel_size: 8
  dtype: bfloat16
  context_length: 262144
  extra_args: []

observability:
  debug_mode: false
  leave_running_on_failure: false
  log_level: info
  telemetry:
    local_artifacts: true
    remote_export: false

host_layout:
  results_root: repo://glm52-serving-results
  run_dir: repo://glm52-serving-results/glm52-sglang-local-20260816T000000Z-001
  logs_dir: run://logs
  tmp_dir: temp://glm52-sglang-local-20260816T000000Z-001
  cache_dir: cache://glm52-sglang-local
  materialized_config: run://materialized-sglang-runtime.yaml

sandbox:
  kind: bwrap_rootfs
  rootfs_ref: rootfs://monarch-default
  cwd: /workspace/monarch
  network: host_loopback_required
  gpu: required
  env_allowlist: []
  env:
    CUDA_VISIBLE_DEVICES: "0,1,2,3,4,5,6,7"
    HF_HOME: /tmp/glm52/hf-home
  mounts:
    - host_path_ref: repo://
      sandbox_path: /workspace/monarch
      mode: ro
    - host_path_ref: run://
      sandbox_path: /run/glm52
      mode: rw
    - host_path_ref: temp://glm52-sglang-local-20260816T000000Z-001
      sandbox_path: /tmp/glm52
      mode: rw
    - host_path_ref: cache://glm52-sglang-local
      sandbox_path: /cache/glm52
      mode: rw

launch:
  outer_argv:
    - scripts/rootfs/enter_rootfs.sh
    - --emit-plan
    - run://sandbox/resolved-bwrap-plan.yaml
    - --
    - python
    - -m
    - sglang.launch_server
    - --model-path
    - zai-org/GLM-5.2
    - --served-model-name
    - zai-org/GLM-5.2
    - --host
    - 127.0.0.1
    - --port
    - "19017"
    - --tp
    - "8"
    - --dtype
    - bfloat16
  inner_argv:
    - python
    - -m
    - sglang.launch_server
    - --model-path
    - zai-org/GLM-5.2
    - --served-model-name
    - zai-org/GLM-5.2
    - --host
    - 127.0.0.1
    - --port
    - "19017"
    - --tp
    - "8"
    - --dtype
    - bfloat16
  env:
    CUDA_VISIBLE_DEVICES: "0,1,2,3,4,5,6,7"
    HF_HOME: /tmp/glm52/hf-home

probes:
  models_url: http://127.0.0.1:19017/v1/models
  chat_url: http://127.0.0.1:19017/v1/chat/completions
  chat_payload:
    model: zai-org/GLM-5.2
    messages:
      - role: user
        content: Reply with GLM52_HEALTH_OK
    max_tokens: 64
    chat_template_kwargs:
      enable_thinking: false

artifacts:
  declared_spec_copy: run://declared-spec.yaml
  materialized_config: run://materialized-sglang-runtime.yaml
  resolved_local_paths: run://resolved-local-paths.yaml
  process_record: run://process.yaml
  launch_summary: run://launch-summary.json
  teardown_summary: run://teardown-summary.json
  resolved_rootfs_plan: run://sandbox/resolved-bwrap-plan.yaml
  models_probe: run://probes/models.json
  chat_probe: run://probes/chat-completions.json
  stdout_log: run://logs/stdout.log
  stderr_log: run://logs/stderr.log
  telemetry_log: run://logs/telemetry.jsonl
  sglang_cli_help: run://sandbox/sglang-launch-server-help.txt
```

Materialization must allocate a single concrete service port from the declared
range and write it into every dependent field:

- `service.port`
- `service.base_url`
- `launch.outer_argv`
- `launch.inner_argv`
- `probes.models_url`
- `probes.chat_url`
- `model.served_model_name` and the `--served-model-name` launch argument

If any dependent field disagrees, the materialized config is invalid and the
launcher must refuse to start SGLang.

## Path Rules

Portable config files must not encode absolute host paths in host-layout fields.
They must use logical refs:

- `repo://`
- `run://`
- `cache://`
- `temp://`
- `rootfs://`

Machine-local absolute host paths are allowed only in:

- local environment config;
- resolved-path evidence;
- process evidence;
- diagnostic error messages.

Absolute sandbox paths are allowed in portable config because the sandbox layout
is a launch protocol:

- `/workspace/monarch`
- `/run/glm52`
- `/tmp/glm52`
- `/cache/glm52`

The validator must reject any portable host-layout field that starts with `/`
unless that field is explicitly declared as a sandbox path.

## Sandbox Contract

The bwrap/rootfs sandbox is governed by schema, not by implicit launcher
behavior. The materialized config must declare:

- rootfs reference;
- entry mechanism;
- sandbox working directory;
- mount plan;
- read-only versus read-write mount modes;
- GPU policy;
- network policy;
- environment allowlist;
- explicit environment values;
- in-sandbox cache, temp, and run directories.

The launcher must not treat `scripts/rootfs/enter_rootfs.sh` as an opaque
execution boundary. The rootfs entrypoint must support a plan-emission mode that
resolves the actual bwrap/rootfs plan before launch. That plan must include:

- rootfs path;
- full outer argv;
- inner argv;
- working directory;
- mount list;
- mount modes;
- GPU and device projection;
- network policy;
- exact env map;
- env allowlist;
- repo projection mode.

The launcher must validate the emitted rootfs plan against the sandbox schema
before starting:

- the declared rootfs reference resolves to a concrete rootfs path;
- every `host_path_ref` resolves through the local environment config;
- every mount mode is honored by the outer command;
- the repo mount is read-only unless a future schema explicitly grants write
  authority;
- run, temp, and cache mounts are writable;
- the sandbox cwd matches the materialized config;
- the env passed to the process equals the materialized env plus the explicitly
  allowed launcher-controlled variables;
- no disallowed fallback port appears in outer argv, inner argv, env, or probe
  URLs.

If `enter_rootfs.sh` cannot emit a resolved plan, or if the emitted plan does not
match the materialized sandbox schema, launch fails before SGLang starts.

The process record must capture the host-visible outer process group. Teardown
uses that process group, not an inferred inner PID.

## Launch Command Validation

The materialized config and final command must be validated in both directions.

Before launch:

- `service.port` must equal the `--port` value in `launch.inner_argv`.
- `service.bind_host` must equal the `--host` value in `launch.inner_argv`.
- `model.path` materialized into the launch command must equal the
  `--model-path` value.
- `model.served_model_name` must equal the `--served-model-name` value in
  `launch.inner_argv`.
- `runtime.tensor_parallel_size` materialized into the launch command must equal
  the `--tp` value.
- `runtime.dtype` materialized into the launch command must equal the `--dtype`
  value.
- probe URLs must derive from `service.base_url`.
- `CUDA_VISIBLE_DEVICES` in launch env must equal the sandbox env.
- the SGLang tail embedded in `launch.outer_argv` must equal
  `launch.inner_argv`.
- no launch value may come from ambient `GLM52_*` environment variables unless a
  later schema explicitly models that override.

The launcher must also preflight the installed SGLang CLI before launch:

- run the in-sandbox equivalent of `python -m sglang.launch_server --help`;
- archive the help text;
- verify that `--served-model-name` is supported by the installed SGLang
  launcher;
- fail loudly if the flag is missing rather than inferring model identity from
  `--model-path`.

At launch:

- the launcher records the exact outer argv;
- the launcher records the exact inner argv;
- the launcher records the exact env map passed to the process;
- the launcher records PID and process group;
- the launcher compares the record back to the materialized config.

If the recorded argv or env differs from the materialized config, the run fails
with command-drift evidence even if SGLang starts successfully.

## Observability Contract

SGLang is foundation serving technology for the larger workstream, so this
milestone must make failures diagnosable rather than merely pass/fail.

The declared spec and materialized config must explicitly encode observability:

- `debug_mode`;
- `leave_running_on_failure`;
- `log_level`;
- local telemetry enablement;
- remote telemetry export, which must default to `false`;
- stdout and stderr log paths;
- structured telemetry log path;
- SGLang CLI help artifact path;
- resolved rootfs plan artifact path.

Default behavior:

- `debug_mode=false`;
- `leave_running_on_failure=false`;
- every post-launch failure triggers best-effort teardown;
- logs and telemetry stay local to the run directory;
- no remote telemetry is required for milestone completion.

Debug behavior:

- `debug_mode=true` may allow `leave_running_on_failure=true`;
- leaving a process running after failure must be explicit in the declared spec
  and materialized config;
- the launch summary must state that the process was intentionally left running;
- the summary must include the process group, selected port, and exact teardown
  command;
- repeatability acceptance must run with `debug_mode=false`, so debug mode cannot
  hide lifecycle bugs.

Structured telemetry must include at least:

- run ID;
- phase name;
- timestamp;
- selected port;
- process group when known;
- SGLang CLI version or help digest when available;
- rootfs plan digest;
- probe latency;
- probe status;
- failure category;
- teardown action.

## Port Allocation

Port allocation is strict and run-owned.

Rules:

- The declared spec provides a range.
- The allocator chooses one free port from that range.
- Disallowed ports are never selected.
- Occupied ports are rejected.
- The allocator does not retry outside the declared range.
- The allocator does not fall back to default SGLang ports.
- The selected port is written to the materialized config before launch.
- The selected port is reused consistently within one run.

If the chosen port becomes occupied before launch, the launcher fails and writes
blocker evidence. It must not silently pick another port after materialization.
A new materialization step is required for a different port.

The implementation should use a run-scoped port lock or reservation artifact to
reduce allocation races. If a port is free during materialization but becomes
occupied before SGLang binds it, the failure category is `port_race_lost`.

## Probe Contract

The launch is not successful until live probes pass against the materialized
service URL.

Required probes:

1. `GET /v1/models`
   - Must return JSON.
   - Must contain a non-empty `data` list.
   - Must include one of `service.expected_model_ids`.
   - Must include `model.served_model_name` unless a future schema explicitly
     declares additional accepted aliases.
   - Must be written to `probes/models.json`.

2. `POST /v1/chat/completions`
   - Must use the materialized `chat_payload`.
   - Must set `chat_template_kwargs.enable_thinking=false`.
   - Must return a valid Chat Completions response.
   - Must contain a response to the health prompt.
   - Must be written to `probes/chat-completions.json`.

Probe failure categories:

- `port_unreachable`
- `invalid_http_response`
- `invalid_json`
- `model_identity_mismatch`
- `chat_completion_failed`
- `chat_completion_invalid_shape`
- `port_race_lost`
- `timeout`

Probe success cannot be inferred from process liveness. It must be proven by
HTTP response artifacts.

## Artifact Layout

Each run writes a fresh run directory under the logical results root:

```text
glm52-serving-results/<run-id>/
  declared-spec.yaml
  materialized-sglang-runtime.yaml
  resolved-local-paths.yaml
  process.yaml
  launch-summary.json
  teardown-summary.json
  probes/
    models.json
    chat-completions.json
  logs/
    stdout.log
    stderr.log
  sandbox/
    mount-plan.yaml
    resolved-bwrap-plan.yaml
    outer-command.json
    inner-command.json
```

Failure before launch still writes:

- declared spec copy when parseable;
- validation summary;
- resolved local paths when resolution reached that phase;
- blocker summary.

Failure after launch additionally writes:

- process record;
- stdout/stderr logs;
- structured telemetry log;
- resolved rootfs plan;
- probe artifacts for every attempted probe;
- teardown recommendation.

Artifacts must never claim success when a prior gate failed. A status may be
only one of:

- `validated`
- `materialized`
- `running`
- `passed`
- `failed`
- `teardown_passed`
- `teardown_failed`
- `already_stopped`

## Teardown Contract

Teardown is schema-driven and idempotent.

Inputs:

- materialized runtime config;
- process record;
- resolved local paths.

Behavior:

- Terminate only the recorded outer process group.
- Refuse to kill if command guard validation fails.
- Wait for process exit.
- Wait for the materialized port to be released.
- Record whether the process was running, stopped, missing, or mismatched.
- Preserve run artifacts by default.
- Treat a second teardown as `already_stopped` with evidence.
- Fail if the materialized port remains occupied by the recorded process.
- Fail loudly if the materialized port remains occupied by an unknown process.

Teardown must not infer a port from current environment, default settings, or a
newly materialized config. It uses the original materialized runtime config.

Every post-launch failure must run teardown in a best-effort `finally` path when
`leave_running_on_failure=false`. This applies to probe failures, command-drift
failures, telemetry-write failures, and summary-write failures after process
creation. If teardown itself fails, the run status is `teardown_failed` and the
artifact must preserve enough process evidence for manual cleanup.

## Repeatability Acceptance

Milestone completion requires repeated launch and teardown from the same
declared spec.

Default acceptance loop:

```text
for cycle in 1..3:
  validate declared spec
  materialize runtime config
  launch SGLang from materialized config
  validate actual command and env
  probe /v1/models
  probe /v1/chat/completions
  teardown from process record
  verify process group is gone
  verify materialized port is released
```

Each cycle gets a fresh run directory and fresh materialized config. The
declared spec is the same. The selected port may differ between cycles, but each
cycle must be internally consistent and must stay within the declared range.

The repeat loop fails if any cycle reuses:

- stale PID;
- stale process group;
- stale probe artifact;
- stale materialized config;
- stale port occupancy assumption;
- stale teardown state.

## Negative Test Requirements

The implementation must include tests that fail before the launcher exists and
pass after it is implemented:

- Declared spec rejects missing `fail_fast`.
- Declared spec rejects `allow_fallback=true`.
- Declared spec rejects missing model ID.
- Declared spec rejects missing model path.
- Declared spec rejects absolute host paths in portable host-layout fields.
- Declared spec rejects a port range containing only disallowed ports.
- Materialized config rejects `service.port` not matching `launch.inner_argv
  --port`.
- Materialized config rejects `service.bind_host` not matching
  `launch.inner_argv --host`.
- Materialized config rejects `model.served_model_name` not matching
  `launch.inner_argv --served-model-name`.
- Materialized config rejects missing `--served-model-name`.
- Materialized config rejects an `outer_argv` whose SGLang tail differs from
  `inner_argv`.
- Materialized config rejects probe URLs that do not derive from
  `service.base_url`.
- Materialized config rejects disallowed fallback ports anywhere in argv, env,
  or probe URLs.
- Sandbox validation rejects missing rootfs reference.
- Sandbox validation rejects undeclared host path refs.
- Sandbox validation rejects a writable repo mount.
- Sandbox validation rejects a missing resolved rootfs plan.
- Sandbox validation rejects a resolved rootfs plan that disagrees with the
  materialized mount plan.
- SGLang CLI preflight rejects installed launcher help that lacks
  `--served-model-name`.
- Model probe validation rejects `/v1/models` returning only `model.path` when
  `model.served_model_name` is expected.
- Launch validation fails on command drift between materialized config and
  recorded process argv/env.
- Post-launch probe failure triggers teardown when `leave_running_on_failure` is
  false.
- Debug mode may leave the process running only when
  `leave_running_on_failure=true` is explicit.
- Teardown refuses to kill a PID whose command guard does not match.
- Teardown succeeds idempotently when run twice against the same completed run.

## Live Verification Requirements

Unit tests are not enough to close this milestone. The milestone requires a
real local run on the governed rootfs path:

- SGLang imports and starts inside the bwrap/rootfs sandbox.
- `enter_rootfs.sh` emits a resolved rootfs plan and the launcher validates it.
- SGLang CLI preflight proves `--served-model-name` is available.
- The selected custom port is reachable from the host.
- `/v1/models` identifies the expected GLM-5.2 model.
- `/v1/chat/completions` returns a valid response for the health prompt.
- Teardown stops the recorded process group.
- The selected port is released.
- The launch/probe/teardown cycle passes three times from the same declared
  spec.

The final evidence must include the three run directories and a loop summary
that lists each run ID, selected port, launch status, probe status, teardown
status, and port-release status.

## Promotion Rule

This milestone is complete only when:

- the source-backed schema validates declared and materialized YAML;
- launch commands are generated from materialized YAML only;
- command drift is detected and fails;
- `enter_rootfs.sh` emits a resolved rootfs plan and the launcher validates it;
- bwrap/rootfs sandbox layout is schema-governed;
- host path resolution is separate from portable config;
- served model identity is explicitly configured and validated through
  `/v1/models`;
- debug/logging/telemetry artifacts are written locally;
- live SGLang launches on custom allocated ports;
- live probes prove model identity and Chat Completions behavior;
- teardown is idempotent and process-group scoped;
- the repeatability loop passes three cycles;
- all artifacts are run-scoped and inspectable.

Only after this milestone passes should the workstream proceed to the next
milestone: schema-driven local Dynamo deployment wired explicitly to the
materialized SGLang endpoint.

## Follow-On Milestone Boundary

The next milestone will add Dynamo. It must consume the SGLang materialized
endpoint as an explicit upstream and produce its own materialized Dynamo runtime
config. It must follow the same first principle: no fallback, fail fast, fail
loud.

The SGLang milestone should not pre-design Dynamo beyond preserving the fields
needed by downstream consumers:

- service kind;
- bind host;
- selected port;
- base URL;
- expected model IDs;
- sandbox/rootfs identity;
- run artifact location;
- probe evidence location.
