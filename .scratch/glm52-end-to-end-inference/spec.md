# GLM-5.2 End-to-End Local Inference Spec

Status: ready-for-human

Created: 2026-08-17T00:00:00Z

## Purpose

This milestone turns the hardened GLM-5.2 SGLang Hermetic Rootfs substrate into
one robust end-to-end Local Run for inference. The run brings up SGLang,
connects a local Dynamo frontend to that exact SGLang instance, connects the
Responses adapter to that exact Dynamo frontend, proves real inference through
each public surface, and tears every owned process down repeatedly.

The milestone is about live inference readiness and proof quality. It is not a
benchmark-scoring milestone and does not fill published conformance results.

## First Principle

No fallback. Fail fast, fail loud.

The runner must not fall back to host Python, host packages, default ports,
ambient local services, implicit model downloads, alternate URLs, fixture
harnesses, fake Responses routing, or partial success summaries. Any missing
preparation record, stale record, occupied port, command drift, wrong upstream,
wrong model identity, failed probe, failed teardown, or unexpected live service
must produce a nonzero result and a concrete blocker Contract Artifact.

## Scope

### In Scope

- A source-backed declared YAML schema for a complete GLM-5.2 inference run.
- A materialized YAML that resolves every component endpoint, command, port,
  environment value, process record path, and Contract Artifact path used by the
  run.
- Strict run-owned allocation for SGLang, Dynamo, and Responses adapter ports.
- Reuse of the existing SGLang preparation, launch, probe, and teardown
  contract from `scripts/glm52_sglang_runtime.py`.
- Local Dynamo launch that connects only to the materialized SGLang endpoint.
- Responses adapter launch that connects only to the materialized Dynamo
  endpoint.
- Real `/v1/models`, `/v1/chat/completions`, and `/v1/responses` probes.
- Streaming and non-streaming Responses probes.
- A tool-call probe through the existing serving verifier.
- Three repeated end-to-end launch/probe/teardown cycles.
- Post-cycle proof that every allocated port is closed and every owned process
  group is gone.
- Machine-readable `summary.json` that names all Contract Artifacts and reports
  `ok: true` only when every gate passed.

### Out of Scope

- Harbor Terminal-Bench 2 and SWE-bench execution.
- HumanEval, MBPP, EvalPlus, GSM8K, AIME, RULER, needle, or quality scoring.
- Published conformance metadata or placeholder score replacement.
- Kubernetes or multi-node serving.
- Remote workers.
- Changing the generic Hermetic Rootfs schema unless the end-to-end contract
  exposes a concrete drift bug.
- Treating fixture-harness or fake-adapter behavior as live inference evidence.

## Existing Building Blocks

- `scripts/glm52_sglang_runtime.py` owns the hardened SGLang schema,
  preparation records, rootfs plan validation, strict port allocation,
  launch/probe/teardown, and repeatability summary.
- `.scratch/glm52-local-serving/config/sglang-local.yaml` is the current
  portable SGLang declared config.
- `.scratch/glm52-local-serving/config/local-environment.example.yaml` is the
  current local resolver example.
- `scripts/glm52_responses_adapter.py` implements the Chat Completions to
  Responses adapter, but currently exposes ambient defaults that this milestone
  must bypass through materialized arguments.
- `scripts/glm52_serving_verifier.py` already probes Chat and Responses surfaces
  and can run tool-call scenarios.
- `scripts/rootfs/rootfs_sandbox_config.py` and `scripts/rootfs/enter_rootfs.sh`
  own the generic bwrap translation and emitted-plan validation.

## Architecture

The end-to-end Local Run is a single parent lifecycle with three owned
components:

```text
declared inference YAML
  + local environment YAML
  -> materialized inference YAML
  -> validate SGLang preparation records
  -> allocate SGLang, Dynamo, and Responses ports
  -> launch SGLang in the Hermetic Rootfs
  -> probe SGLang models and chat
  -> launch Dynamo against the materialized SGLang URL
  -> probe Dynamo models and chat
  -> launch Responses adapter against the materialized Dynamo URL
  -> probe Responses models, non-stream, stream, and tool calls
  -> teardown Responses, Dynamo, and SGLang in reverse order
  -> prove ports closed and no owned processes remain
```

The parent runner owns the run ID, port allocation, process records, component
dependencies, failure policy, Contract Artifact layout, repeatability loop, and
final summary. Component scripts may remain independent, but end-to-end
inference evidence is valid only when produced by the parent run summary.

## Declared Config Shape

The declared config lives at:

```text
.scratch/glm52-local-serving/config/inference-local.yaml
```

The config must be portable. It may use logical refs such as `repo://`,
`cache://`, `temp://`, `run://`, `rootfs://`, and `component://`. It must not
encode absolute host paths. Concrete host paths remain confined to the local
environment YAML and resolved evidence.

Representative shape:

```yaml
schema_version: 1
run_group: glm52-inference-local
fail_fast: true
allow_fallback: false

ports:
  mode: strict_run_owned_range
  bind_host: 127.0.0.1
  range_start: 19000
  range_end: 19200
  disallowed_ports: [8000, 8080, 18080]

components:
  sglang_backend:
    enabled: true
    declared_ref: repo://.scratch/glm52-local-serving/config/sglang-local.yaml
    required_records:
      venv: repo://glm52-serving-results/prepare-venv/sglang-venv.json
      model_cache: repo://glm52-serving-results/prepare-model/model-cache.json

  dynamo_frontend:
    enabled: true
    kind: local_dynamo_sglang
    bind_host: 127.0.0.1
    upstream_ref: component://sglang_backend/openai_base_url
    model_name_ref: component://sglang_backend/served_model_name
    config_root: repo://.scratch/glm52-local-serving/dynamo
    logs_root: run://logs/dynamo
    startup_timeout_seconds: 300

  responses_adapter:
    enabled: true
    bind_host: 127.0.0.1
    upstream_ref: component://dynamo_frontend/openai_base_url
    model_name_ref: component://sglang_backend/served_model_name
    logs_root: run://logs/responses-adapter
    startup_timeout_seconds: 120

probes:
  sglang:
    models_required: true
    chat_required: true
  dynamo:
    models_required: true
    chat_required: true
  responses:
    models_required: true
    nonstream_required: true
    stream_required: true
    tool_call_required: true

repeatability:
  cycles: 3

teardown:
  process_group_required: true
  port_closed_required: true
  orphan_scan_required: true
```

## Materialized Contract

The parent runner writes:

```text
glm52-serving-results/<run-id>/materialized-inference.yaml
```

The materialized config must contain:

- the run ID and creation timestamp;
- allocated SGLang, Dynamo, and Responses adapter ports;
- concrete component URLs;
- the served model name and expected model IDs;
- SGLang preparation record paths and digests;
- the rootfs plan digest used by SGLang;
- each component's structured argv;
- each component's environment mapping;
- stdout and stderr log paths;
- process record paths;
- probe request and response artifact paths;
- teardown proof paths;
- failure policy.

Every process launch and every probe consumes the materialized config or a
validated component slice derived from it. Free-form `--chat-base-url`,
`--responses-base-url`, or ambient environment defaults are invalid in the
end-to-end path.

## Execution Domains

The end-to-end runner has one host-control parent process. SGLang runs inside
the Hermetic Rootfs through the existing SGLang runtime contract. Dynamo and the
Responses adapter are host-controlled local processes unless a later ticket
adds an explicit Hermetic Rootfs component slice for them. Host-controlled does
not mean fallback: their commands, env, ports, upstream URLs, logs, and process
records still come only from `materialized-inference.yaml`.

If a component needs the Hermetic Rootfs, the schema must declare that execution
domain before launch. The runner must not infer or switch execution domains
after a command fails.

## Component Contracts


### SGLang Backend

The SGLang component must reuse the existing rootfs-owned runtime path. Before
launch, the parent runner validates:

- `prepare-venv` record exists and matches the current rootfs plan digest;
- `prepare-model` record exists and points to a readable model snapshot;
- model launch will not download weights;
- allocated port is not disallowed and is currently free;
- materialized command includes `--served-model-name`;
- `HF_HOME` and SGLang cache paths are the governed `/cache/glm52/...` paths.

The SGLang probes must require:

- `GET /v1/models` advertises `zai-org/GLM-5.2`;
- path identities such as `/models/glm52` do not satisfy model identity;
- `POST /v1/chat/completions` returns non-empty real model output.

### Dynamo Frontend

Dynamo must launch only after SGLang probes pass. Its upstream URL must be the
materialized SGLang OpenAI base URL, not an operator-supplied URL or ambient
default. The parent runner records the Dynamo launch command, environment,
config files, stdout, stderr, and process record.

The Dynamo probes must require:

- `GET /v1/models` advertises the same served model name as SGLang;
- `POST /v1/chat/completions` returns non-empty output;
- the response is not accepted as live evidence if SGLang is not still owned and
  healthy in the same run.

The initial Dynamo implementation uses the host-controlled execution domain. It
still consumes only the materialized SGLang URL and must write process
ownership evidence.

### Responses Adapter

The Responses adapter must launch only after Dynamo probes pass. Its upstream
URL must be the materialized Dynamo OpenAI base URL. The existing adapter's
ambient defaults for port `8080` and chat base URL are not valid in this path.

The Responses probes must require:

- `GET /v1/models` advertises the served GLM-5.2 model name;
- non-streaming `POST /v1/responses` returns non-empty output;
- streaming `POST /v1/responses` emits valid SSE events and a completed answer;
- a tool-call scenario succeeds through `scripts/glm52_serving_verifier.py`;
- failures preserve raw adapter and upstream response artifacts.

## Local Run Ladder

1. **Environment**
   Validate declared and local environment YAML, portable refs, local roots,
   rootfs availability, SGLang preparation records, and strict port range.

2. **Build / Preparation**
   This milestone does not hide preparation inside live launch. If preparation
   records are missing, the runner fails with a prepare-required blocker and
   points to the explicit `prepare-venv` and `prepare-model` commands.

3. **Unit-Level Smoke**
   Launch and probe SGLang alone. Then launch and probe Dynamo alone against the
   owned SGLang instance. Then launch and probe Responses alone against the
   owned Dynamo instance.

4. **Integration**
   Run the complete direct-chat, Dynamo-chat, Responses non-stream, Responses
   stream, and Responses tool-call inference sequence in one owned lifecycle.

5. **Failure Classification**
   There is no accepted flaky-pass classification for this milestone. Any
   failed required probe, teardown miss, orphan, or port leak fails the Local
   Run. Later benchmark suites may define their own classification rules.

## Repeatability

The acceptance run executes three cycles:

```text
preflight
launch sglang
probe sglang
launch dynamo
probe dynamo
launch responses adapter
probe responses adapter
run inference smoke
teardown responses adapter
teardown dynamo
teardown sglang
prove ports closed
prove no owned processes remain
```

Cycles may reuse the prepared SGLang virtual environment and model cache only
when their records match the current materialized run. Cycles must not reuse a
live SGLang, Dynamo, or Responses process from a previous cycle.

If a post-launch phase fails and `debug_mode: false`, teardown still runs and
the final status remains nonzero. If `debug_mode: true`, preserving a process on
failure must be explicit and must mark the run as not accepted.

## Contract Artifacts

Each run writes:

```text
glm52-serving-results/<run-id>/
  declared-inference.yaml
  local-environment.redacted.yaml
  materialized-inference.yaml
  port-allocation.json
  preparation-records/
    sglang-venv.json
    model-cache.json
  components/
    sglang/
      materialized.yaml
      process.json
      bwrap-plan.json
      launch.argv.json
      models.json
      chat.json
      stdout.log
      stderr.log
    dynamo/
      process.json
      launch.argv.json
      models.json
      chat.json
      stdout.log
      stderr.log
    responses-adapter/
      process.json
      launch.argv.json
      models.json
      responses-nonstream.json
      responses-stream.sse
      tool-call.json
      stdout.log
      stderr.log
  teardown/
    responses-adapter.json
    dynamo.json
    sglang.json
    ports.json
    orphan-scan.json
  summary.json
```

`summary.json` is the authoritative completion artifact. It must include:

- `ok`;
- run ID;
- component statuses;
- exact endpoint URLs;
- model IDs observed at every layer;
- per-cycle artifact paths;
- teardown status;
- blocker kind and message when `ok` is false.

## Acceptance Criteria

The milestone is accepted only when a fresh run produces:

- valid `prepare-venv` evidence;
- valid `prepare-model` evidence;
- three successful end-to-end cycles;
- real direct SGLang chat output;
- real Dynamo chat output;
- real Responses non-stream output;
- real Responses streaming output;
- real Responses tool-call output;
- matching GLM-5.2 model identity at every layer;
- no use of ports `8000`, `8080`, or `18080`;
- no fallback URL, fake response, fixture result, or ambient service evidence;
- all allocated ports closed after every cycle;
- no owned process orphans after every cycle;
- `summary.json` with `ok: true`.

## Non-Completion Evidence

The following remain useful diagnostics but are not completion evidence:

- unit tests with fake SGLang, fake Dynamo, or fake Responses endpoints;
- fixture-harness benchmark scores;
- Harbor or Docker health without a GLM-backed Responses URL;
- `/v1/models` from SearXNG or another ambient service;
- a chat endpoint on port `8000`;
- a Responses adapter on port `8080`;
- a single successful launch without teardown proof;
- a run with `debug_mode: true` that leaves processes alive.

## Implementation Tickets

- `issues/01-inference-run-schema.md`
- `issues/02-owned-process-records.md`
- `issues/03-dynamo-integration.md`
- `issues/04-responses-adapter-integration.md`
- `issues/05-repeatability-runner.md`

The first implementation slice is schema and materialization. Live Dynamo launch
waits until the parent materialized contract can prove there is no ambient
endpoint or fallback path.
