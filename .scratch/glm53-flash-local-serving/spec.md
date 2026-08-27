# GLM-5.3-Flash Local Inference Setting Spec

Status: draft, revised 2026-08-26

Owner: local Monarch agent workflow

Source baseline:

- `docs/agentic-ai/glm53-flash-deep-dive.md`
- `docs/agentic-ai/glm52-local-serving.md`
- `ginkgo/README.md`
- `ginkgo/docs/verification-ladder.md`
- `.scratch/glm52-local-serving/bwrap-rootfs-serving-system-design.md`
- `.scratch/glm52-local-serving/config/sglang-local.yaml`
- `.scratch/glm52-local-serving/config/inference-local.yaml`

## Decision Summary

This spec chooses the same local-first architecture as the latest GLM-5.2
system design: a parent-owned, single-machine run with materialized config,
run-owned ports, rootfs-controlled SGLang, and a host-controlled Responses
adapter. Dynamo is a required topology proof before the Dynamo-forwarded setting
is called Codex-ready, but it is not a blocker for the first SGLang
compatibility tracer bullet. This setting is for local compatibility and
benchmark evidence, not a production cluster deployment.

Durable implementation artifacts should be promoted into Ginkgo, because Ginkgo
now owns the portable serving contract. This `.scratch/glm53-flash-local-serving/`
tree owns planning, issue tracking, design notes, and mutable workstream state.
Target durable paths:

- `ginkgo/configs/sglang-glm53-flash.yaml`
- `ginkgo/configs/inference-glm53-flash.yaml`
- `ginkgo/profiles/glm53-flash.yaml`
- `ginkgo/docs/glm53-flash-local-serving.md`
- `glm53-flash-serving-results/<run-id>/` for run artifacts

The first implementation should favor model-scoped files with the
`glm53_flash_` prefix over a broad shared-runtime refactor. The GLM-5.2 scripts
are mature but still encode many model-specific assumptions; proving
GLM-5.3-Flash end to end is the higher-priority tracer bullet. A later cleanup
can extract a shared GLM schema/runtime only after both model paths are green.

The initial live profile is SGLang-first. Other local-serving frameworks named
by the public sources, including vLLM, TokenSpeed, and KTransformers, are
recorded as future profiles. They are not part of the first acceptance path
unless SGLang cannot pass the model preflight.

Backend capability tracking is schema-owned for every named framework, but only
SGLang needs a complete record in the first acceptance path. Future backends may
carry explicit `deferred` records until their profile is selected:

| Backend | Initial status | Required capability record |
| --- | --- | --- |
| SGLang | first live profile | image or venv version, OpenAI Chat endpoint, `glm45` reasoning parser, `glm47` tool parser, FP8 path, multimodal processor, max tested context, KDA/MTP/speculative settings, Dynamo compatibility |
| vLLM | future profile | deferred or observed model-load support, OpenAI Chat endpoint, reasoning/tool parser support, FP8 path, multimodal support, max tested context |
| TokenSpeed | future profile | deferred or observed endpoint shape, FP8 path, long-context support, tool/reasoning compatibility, adapter feasibility |
| KTransformers | future profile | deferred or observed endpoint shape, local hardware assumptions, FP8 or conversion path, long-context support, adapter feasibility |

No backend is interchangeable by name alone. A backend profile becomes eligible
only after its capability record proves the same Responses adapter contract or
declares an explicit adapter delta.

## Goal

Define a GLM-5.3-Flash local inference setting that mirrors the proven shape of
the GLM-5.2 local-serving work while making every GLM-5.3-specific protocol and
runtime assumption explicit.

The first target is a single-machine, local, file-backed run:

```text
Codex CLI / IDE
  -> OpenAI Responses API
  -> Responses-to-Chat adapter
  -> SGLang GLM-5.3-Flash workers
```

The stronger parent-owned lifecycle from the GLM-5.2 system design is the
target, not an ambient external endpoint handoff. A parent runner allocates
ports, resolves logical paths, writes a materialized config, starts components
in order, probes every serving surface, records Contract Artifacts, and tears
the run down. A later profile inserts local Dynamo between the adapter and
SGLang and must pass the lossiness gate before the Dynamo topology is promoted.

## Non-Goals

- Do not use Kubernetes, KubeRay, Kueue, or cluster-native jobs for the initial
  setting.
- Do not claim benchmark reproduction from Z.ai's published scores until local
  benchmark runs record matching conditions and artifacts.
- Do not preserve GLM-5.2's thinking-disabled default unless a specific local
  backend proves that this is supported and compatible with tool calling.
- Do not launch against default ambient ports such as `8000`, `8080`, or
  `18080`.
- Do not treat generated benchmark caches, downloaded harnesses, run logs, or
  bytecode as tracked source artifacts.
- Do not generalize the GLM-5.2 runtime into a framework abstraction before a
  GLM-5.3-Flash tracer bullet proves the forced-thinking and multimodal path.
- Do not bypass the Responses adapter for coding-agent, Codex, or benchmark
  evidence. Direct Chat probes are backend diagnostics only.

## Model Contract

The declared model identity is:

- Hosted model code: `glm-5.3-flash`
- Hugging Face model id: `zai-org/GLM-5.3-Flash`
- Served local model name: `zai-org/GLM-5.3-Flash`
- Expected `/v1/models` ids: `zai-org/GLM-5.3-Flash`

The local config must also record source model metadata used for preflight:

```yaml
source_metadata:
  architecture: Glm5NextForConditionalGeneration
  model_type: glm5_next
  max_position_embeddings: 1048576
  total_parameters: 320B
  active_parameters: 18B
  text_layers: 45
  linear_attention_layers: 34
  sparse_attention_layers: 11
  routed_experts: 288
  active_experts_per_token: 8
  vision_encoder_layers: 24
  quantization:
    method: fp8
    format: e4m3
```

The serving preflight must prove that the selected backend supports this model
family, not only that a generic OpenAI-compatible HTTP server starts. Required
capability checks:

- architecture `Glm5NextForConditionalGeneration` / `glm5_next`;
- 1M-token position limit in the model config;
- hybrid linear and sparse attention support;
- MoE routing for 288 routed experts and 8 active experts per token;
- FP8 checkpoint handling or an explicitly declared conversion path;
- GLM-5.3-Flash reasoning parser support;
- GLM-5.3-Flash tool-call parser support;
- multimodal processor support for at least image input, recorded as
  `deferred` until the image profile is selected.

The initial config should remain conservative on runtime capacity. The model can
advertise a 1M-token context, but the first Local Run Ladder should validate
basic agent semantics before attempting a full-context stress run. The declared
config should include both:

- `model.max_position_embeddings: 1048576`, copied from source evidence;
- a separate `runtime.context_length`, selected for the local hardware and
  recorded as an explicit run condition.

The first verifier profile should use `runtime.context_length: 262144` only as
a conservative starting condition inherited from GLM-5.2. It must not describe
that as the model limit. A separate long-context profile should later attempt
400K-token coding-agent conditions and 1M-token retrieval conditions after the
basic Responses path is green.

## Protocol Deltas From GLM-5.2

GLM-5.3-Flash is a forced-thinking model in the current Z.ai docs. The GLM-5.2
pattern of setting `chat_template_kwargs.enable_thinking: false` must not be the
default for GLM-5.3-Flash.

The GLM-5.3-Flash Chat Completions request defaults are:

- `temperature: 1`
- `top_p: 0.95`
- `reasoning_effort: max`
- `thinking.type: enabled`
- `thinking.clear_thinking: false`
- `stream: true` for streaming probes
- `tool_stream: true` for streaming tool-loop probes

The adapter and verifier must treat these defaults as part of the profile. A
run that uses different sampling or thinking settings can still be useful, but
its Contract Artifacts must record the override and must not be compared to
published GLM-5.3-Flash benchmark conditions unless the override matches the
source conditions.

If a local SGLang backend exposes backend-specific `chat_template_kwargs` for
reasoning control, the config may record them, but the acceptance path assumes
thinking is enabled and preserved.

With SGLang's GLM-5.3-Flash recipe, launch arguments must include:

- `--model-path zai-org/GLM-5.3-Flash`
- `--reasoning-parser glm45`
- `--tool-call-parser glm47`

When the reasoning parser is active, Chat Completions responses place thinking
in `message.reasoning_content` and the final answer in `message.content`.
The Responses adapter must preserve that distinction:

- `reasoning_content` is recorded as reasoning metadata, not mixed into final
  output text;
- final assistant output uses `message.content`;
- streaming preserves ordering across reasoning deltas, content deltas, tool
  call deltas, and tool result continuations;
- follow-up turns preserve complete prior reasoning blocks when the run uses
  `thinking.clear_thinking: false`;
- malformed, missing, truncated, rewritten, or reordered reasoning history is a
  verifier failure, not a silent fallback.

Tool calling remains Chat-Completions-shaped:

- request tools describe functions;
- `tool_choice` defaults to `auto`;
- responses include `tool_calls` with stable ids, function names, and JSON
  string arguments.

Codex compatibility still requires the Responses API even if the backend and
frontend expose only Chat Completions. The GLM-5.3-Flash adapter must support
`/v1/models`, `/v1/responses`, non-streaming responses, streaming responses,
tool calls, tool outputs, and `previous_response_id`.

## Responses Adapter Contract

The Responses adapter is a protocol adapter, not a prompt rewriter. It owns
OpenAI Responses compatibility and delegates generation to a Chat Completions
surface. It must keep a run-local response store for `previous_response_id`
continuation and must record enough request/response metadata for verifier
replay.

Required inbound request support:

- `model`
- `input` as text, message arrays, and tool-result continuations
- `tools`
- `tool_choice`, limited to `auto` unless a backend proves more support
- `previous_response_id`
- `stream`
- `tool_stream` for profiles that validate incremental tool-call arguments
- `temperature`, `top_p`, `max_output_tokens`
- GLM profile fields for `reasoning_effort` and `thinking`

The default reasoning policy is `private_metadata`. The adapter stores
reasoning content in the run-local response store and diagnostic artifacts, but
does not mix it into final answer text. If a future Codex surface accepts
Responses reasoning events, a profile may switch to
`responses_reasoning_events`; that profile must define event names, retention,
and redaction separately.

Reasoning retention rules:

- retain reasoning only under the run root and response store for the run;
- include SHA256 digests and lengths in public summary artifacts;
- include raw reasoning only in stage artifacts that are already treated as
  Contract Artifacts for local diagnosis;
- replay prior reasoning to Chat exactly and in order for
  `previous_response_id` when `thinking.clear_thinking: false`;
- redact or omit reasoning from any artifact intended for publication outside
  the local benchmark evidence bundle.

Required outbound non-streaming mapping:

| Chat field | Responses handling |
| --- | --- |
| `message.content` | final assistant output text |
| `message.reasoning_content` | reasoning item or response metadata, never final text |
| `message.tool_calls[].id` | stable Responses tool call id |
| `message.tool_calls[].function.name` | Responses function name |
| `message.tool_calls[].function.arguments` | JSON string preserved byte-for-byte unless invalid JSON must fail |
| token usage | Responses usage fields plus raw Chat usage in artifact metadata |

Required streaming mapping:

| Chat stream delta | Responses event requirement |
| --- | --- |
| reasoning delta | ordered reasoning delta event or metadata event |
| content delta | ordered output text delta |
| tool-call id/name delta | ordered function-call metadata delta |
| tool-call argument delta | ordered argument delta with final JSON validation |
| finish reason | terminal response completion event |

The adapter must fail loudly when the backend interleaves tool-call and content
states in a way that cannot be represented as Responses events. It must not
repair invalid tool JSON silently. It may preserve raw Chat payloads in
diagnostic artifacts, but public Responses output must not leak Chat-only field
names such as `reasoning_content` unless the Responses schema deliberately
exposes them as metadata.

The streaming tool-loop verifier must retain a raw chunk transcript digest and
prove that incremental tool-call arguments reconstruct byte-for-byte into the
same JSON string that the final Chat message reports.

## Local Runtime Shape

The GLM-5.3-Flash runtime should be introduced as model-scoped siblings to the
GLM-5.2 files rather than by mutating GLM-5.2 constants in place.

Recommended names:

- scratch root: `.scratch/glm53-flash-local-serving/`
- durable SGLang config: `ginkgo/configs/sglang-glm53-flash.yaml`
- durable parent config: `ginkgo/configs/inference-glm53-flash.yaml`
- durable profile: `ginkgo/profiles/glm53-flash.yaml`
- result roots: `glm53-flash-serving-results/` and
  `glm53-flash-benchmark-results/`
- run groups: `glm53-flash-sglang-local` and
  `glm53-flash-inference-local`
- script/module prefix: `glm53_flash_`
- env var prefix: `GLM53_FLASH_`
- health sentinel: `GLM53_FLASH_HEALTH_OK`
- Codex provider name: `glm53-flash`

All local commands run through `scripts/run` unless the command is explicitly in
a separate execution domain such as host-controlled Docker/Harbor work. The
SGLang worker process runs inside the Monarch bwrap rootfs. Dynamo and the
Responses adapter are host-controlled local processes for the initial design;
that is an execution-domain choice, not a fallback.

Execution domains:

| Domain | Owner | Examples | Rule |
| --- | --- | --- | --- |
| repo Python | `scripts/run` | schema validation, unit tests, verifier helper code | run inside the Monarch rootfs |
| SGLang payload | bwrap rootfs | `/cache/glm53-flash/venvs/sglang/bin/python -m sglang.launch_server` | launched from materialized sandbox config |
| parent lifecycle | host control | port allocation, PID records, cleanup, Docker/Harbor, orphan scans | not nested inside bwrap when host resources are required |
| Dynamo frontend | host control | local Dynamo process against materialized SGLang URL | no fallback to ambient endpoints |
| Responses adapter | host control | local Responses service against materialized Dynamo URL | no fallback to direct Chat for Codex evidence |
| model-authored code | task bwrap or official containers | code benchmark tasks, Terminal-Bench-style tasks | isolated from repo writes except declared task work dirs |

The declared SGLang config should keep GLM-5.2's fail-fast and port discipline:

```yaml
schema_version: 1
run_group: glm53-flash-sglang-local
fail_fast: true
allow_fallback: false
port_policy:
  mode: strict_run_owned_range
  bind_host: 127.0.0.1
  range_start: 19200
  range_end: 19300
  disallowed_ports: [8000, 8080, 18080]
model:
  id: zai-org/GLM-5.3-Flash
  path: zai-org/GLM-5.3-Flash
  served_model_name: zai-org/GLM-5.3-Flash
  expected_model_ids: [zai-org/GLM-5.3-Flash]
  max_position_embeddings: 1048576
runtime:
  kind: sglang_openai
  device: cuda
  cuda_visible_devices: "0,1,2,3,4,5,6,7"
  tensor_parallel_size: 8
  checkpoint_quantization:
    method: fp8
    format: e4m3
    loading_mode: native_or_declared_conversion
  compute_dtype: bfloat16
  context_length: 262144
  kv_cache_dtype: bfloat16
  max_total_tokens: 65536
  max_running_requests: 1
  sampling:
    temperature: 1
    top_p: 0.95
  reasoning_parser: glm45
  tool_call_parser: glm47
  thinking:
    type: enabled
    clear_thinking: false
    reasoning_effort: max
  kda_state_pool:
    enabled: true
    capacity_limit: profile_default
    observed_metrics_required: true
  mtp:
    enabled: profile_default
    draft_tokens: profile_default
    observed_metrics_required: true
  speculative_decoding:
    enabled: profile_default
    mode: profile_default
    observed_metrics_required: true
  extra_args:
    - --reasoning-parser
    - glm45
    - --tool-call-parser
    - glm47
```

The parent inference config should compose components with the same
`component://` pattern as GLM-5.2:

```yaml
schema_version: 1
run_group: glm53-flash-inference-local
fail_fast: true
allow_fallback: false
ports:
  mode: strict_run_owned_range
  bind_host: 127.0.0.1
  range_start: 19200
  range_end: 19400
  disallowed_ports: [8000, 8080, 18080]
components:
  sglang_backend:
    enabled: true
    declared_ref: repo://ginkgo/configs/sglang-glm53-flash.yaml
    required_records:
      venv: repo://glm53-flash-serving-results/prepare-venv/sglang-venv.json
      model_cache: repo://glm53-flash-serving-results/prepare-model/model-cache.json
  dynamo_frontend:
    enabled: profile_required
    kind: local_dynamo_sglang
    execution_domain: host_controlled
    bind_host: 127.0.0.1
    upstream_ref: component://sglang_backend/openai_base_url
    model_name_ref: component://sglang_backend/served_model_name
    logs_root: run://logs/dynamo
    startup_timeout_seconds: 300
    protocol_requirements:
      preserve_reasoning_content: true
      preserve_tool_calls: true
  responses_adapter:
    enabled: true
    execution_domain: host_controlled
    bind_host: 127.0.0.1
    upstream_ref: component://sglang_backend/openai_base_url
    dynamo_profile_upstream_ref: component://dynamo_frontend/openai_base_url
    model_name_ref: component://sglang_backend/served_model_name
    logs_root: run://logs/responses-adapter
    startup_timeout_seconds: 120
    timeout_seconds: 1800
    protocol_requirements:
      wire_api: responses
      previous_response_id: required
      stream: required
      tool_calls: required
      reasoning_metadata: required
      multimodal_input: profile_required
```

The context length, max-total-token limit, speculative decoding, KDA state-pool
sizing, CPU offload, CUDA graph settings, FP8 execution mode, and MTP settings
must be treated as run conditions. They should be declared in config and echoed
into `environment.json`, but not treated as validated defaults until a live run
proves them on the local machine.

For FP8, the verifier must distinguish the checkpoint format from runtime
compute and KV-cache dtypes. Loading FP8 weights into BF16 compute can be a valid
profile only if the materialized config records the conversion or native-kernel
path and the environment artifact records the observed backend verdict.

Suggested first profiles:

- `sglang-basic-agent`: 8 GPUs, conservative context, forced thinking,
  Responses tool loop, no published benchmark claims.
- `sglang-long-context`: same adapter path, larger context targets, RULER and
  needle-smoke only after `sglang-basic-agent` passes.
- `sglang-terminal-bench`: same Responses adapter, high output-token budget,
  host-controlled Harbor/Docker as required by the benchmark contract.
- `sglang-direct-chat-diagnostic`: direct Chat-only probes for parser and
  Dynamo diagnosis; not acceptable as Codex or benchmark evidence.
- `sglang-dynamo-lossiness`: compare direct SGLang Chat transcripts with
  Dynamo-forwarded transcripts for reasoning, content, tool calls, and stream
  chunks before declaring the Dynamo topology Codex-ready.

## Configuration and Materialization

Reuse the GLM-5.2/Ginkgo three-scope configuration model:

- declared config is human-authored and portable;
- local environment config maps logical roots to absolute host paths;
- materialized config is machine-written for exactly one run and is the only
  launch source of truth.

Portable declared configs may use `repo://`, `cache://`, `temp://`, `run://`,
`rootfs://`, and `component://` references. They must not contain workstation
absolute paths. Commands are structured argv arrays; shell strings are invalid
at the schema boundary.

Materialized GLM-5.3-Flash configs must record:

- resolved model id, model path, served name, and expected model ids;
- resolved ports and base URLs for SGLang, Dynamo, and Responses;
- argv arrays and environment maps for every process;
- bwrap rootfs identity and projection paths;
- SGLang image/package provenance, including whether the
  `lmsysorg/sglang:glm-5.3-flash` recipe image or an equivalent venv is used;
- reasoning parser, tool-call parser, thinking settings, and sampling defaults;
- multimodal processor availability;
- process records, log paths, run root, result root, cache root, and temp root.

Schema migration requirements:

- cache namespace, sandbox projection paths, result roots, and health sentinels
  must be model-scoped rather than hard-coded to GLM-5.2;
- model id, served name, expected ids, source metadata, parser flags, thinking
  policy, multimodal capability, FP8 mode, MTP settings, and KDA state-pool
  settings must be schema-owned fields, not only `extra_args`;
- GLM-5.3-Flash parser and thinking fields must be accepted explicitly by the
  schema and rejected when missing from the default profile;
- parent materialization must write `sglang_backend.openai_base_url`,
  `dynamo_frontend.openai_base_url`, and `responses_adapter.openai_base_url`
  from the declared run-owned port policy;
- benchmark commands must read URLs from materialized config or GLM53_FLASH env
  vars generated from that config, never default `localhost:8000/8080`.

The materializer must reject:

- `allow_fallback: true`;
- ports outside the run-owned range;
- configured use of `8000`, `8080`, or `18080`;
- absolute host paths inside declared config;
- shell-string commands;
- missing `reasoning_parser`;
- missing `tool_call_parser`;
- missing `thinking.type: enabled`;
- missing `thinking.clear_thinking`;
- `chat_template_kwargs` that disable thinking in the default profile;
- multimodal verifier requirements without a declared fixture and processor;
- benchmark profiles whose `responses_adapter` component is disabled;
- streaming tool-loop profiles that omit `tool_stream: true`;
- FP8 checkpoints without a native-load or declared-conversion verdict.

## Preflight and Failure Classes

Preflight should fail before model launch when a required condition is absent.
Failure artifacts should use stable classes so blocked follow-up work can be
triaged without reading logs by hand.

Required failure classes:

- `environment_setup_failed`: rootfs, GPU visibility, Python package, Docker, or
  host-control prerequisite is missing.
- `model_cache_failed`: model files are absent, incomplete, corrupt, or do not
  match expected metadata.
- `backend_capability_failed`: SGLang or another backend cannot load
  GLM-5.3-Flash architecture, FP8 weights, KDA/MTP requirements, parsers, or
  multimodal processor.
- `port_ownership_failed`: a configured port is disallowed, already in use, or
  still open after teardown.
- `protocol_mapping_failed`: Chat fields cannot be mapped into Responses
  semantics without loss.
- `reasoning_preservation_failed`: reasoning content is absent when required,
  merged into final text, dropped across turns, or reordered.
- `tool_call_failed`: tool call JSON, tool ids, tool result continuation, or
  final tool-loop output is invalid.
- `multimodal_failed`: image fixture loading, request serialization, processor
  availability, or backend response validation fails.
- `benchmark_contract_failed`: a benchmark attempts fixture/static evidence,
  bypasses Responses, omits condition metadata, or runs before serving passes.

## Verifier Ladder

The GLM-5.3-Flash serving verifier must prove agent compatibility before any
benchmark run can be accepted.

The verifier must sit on top of the Ginkgo lower gates. GLM-5.3-specific live
checks do not replace rootfs, dependency, CPU, CUDA, dense, or MoE readiness.
Required gate order:

1. Schema.
2. Materialization.
3. Rootfs plan.
4. Dependency environment.
5. CPU serving smoke.
6. CUDA-kernel capability probes.
7. Dense serving smoke.
8. MoE serving smoke.
9. GLM-5.3-Flash SGLang live.
10. Responses live against SGLang.
11. Dynamo live and lossiness proof for the Dynamo profile.
12. Repeatability.
13. Benchmark readiness.

Required stages:

1. Environment: record GPU list, rootfs identity, Python/SGLang/Dynamo package
   versions, model cache evidence, parser settings, and multimodal processor
   availability.
2. Backend `/v1/models`: require the expected GLM-5.3-Flash model id and reject
   ambient/default services.
3. Backend Chat health: send a short prompt and require a successful final
   `message.content`.
4. Reasoning separation: require a prompt that emits non-empty
   `message.reasoning_content` and final `message.content`, then verify that the
   adapter does not merge the two channels.
5. Tool loop over Chat Completions: require a deterministic local tool call,
   tool result continuation, and final answer.
6. Optional multimodal smoke for the first tracer bullet: when an image fixture
   is declared, send one image input through the backend Chat surface and
   require a content-bearing answer that proves the image request path was used.
   Absence of the fixture blocks the multimodal profile, not the first text and
   tool compatibility run.
7. Dynamo `/v1/models` and Chat for the Dynamo profile: require the same model
   identity and protocol behavior through the frontend.
8. Dynamo lossiness check for the Dynamo profile: compare direct SGLang and
   Dynamo-forwarded raw
   transcripts for `reasoning_content`, `content`, `tool_calls`, and streaming
   deltas.
9. Responses `/v1/models`: require the model id surfaced through the adapter.
10. Responses non-streaming: require final text and reasoning metadata mapping.
11. Responses streaming: require ordered reasoning, text, tool-call, and final
    events without leaking raw Chat-only fields.
12. Responses tool loop: require tool calls, tool outputs, and
    `previous_response_id` continuation.
13. Teardown: require process-group ownership, closed allocated ports, and an
    orphan scan.

Required Contract Artifacts:

- `environment.json`
- `sglang-models.json`
- `sglang-health.json`
- `sglang-reasoning.json`
- `sglang-tool-loop.json`
- `sglang-multimodal.json`
- `dynamo-models.json`
- `dynamo-chat.json`
- `dynamo-lossiness.json`
- `responses-models.json`
- `responses-nonstream.json`
- `responses-stream.json`
- `responses-tool-loop.json`
- `teardown.json`
- `summary.json`
- `archive-manifest.json`

The verifier exits zero only when every required stage for the selected profile
passes and `archive-manifest.json` hashes every Contract Artifact for the run.
The first `sglang-basic-agent` profile requires text, reasoning, streaming,
tool, and `previous_response_id` coverage through Responses against SGLang. The
`sglang-dynamo-lossiness` and multimodal profiles add their own required stages.
Partial evidence is useful for diagnosis but does not make the selected profile
complete.

The artifact schema is versioned independently from the GLM-5.2 verifier. If
implementation reuses current GLM-5.2 names such as `chat-health.json`,
`chat-agent.json`, `responses-agent.json`, or `responses-terminal-bench.json`,
it must provide a compatibility mapping to the GLM-5.3 v2 names listed above.
The important contract is stage role plus archive hash, not the legacy filename.

Minimum artifact fields:

- all artifacts: `schema_version`, `run_id`, `profile`, `started_at`,
  `finished_at`, `status`, `failure_class`, `materialized_config_sha256`;
- environment artifact: GPU ids, rootfs identity, package versions, backend
  package/image provenance, model metadata, parser settings, thinking settings,
  multimodal processor status;
- model artifacts: requested base URL, returned ids, expected ids, raw response
  digest;
- reasoning artifacts: raw Chat digest, reasoning length, final-content length,
  channel-separation verdict, preserved-thinking replay verdict;
- tool-loop artifacts: tool schemas, tool-call ids, argument JSON digest, tool
  result ids, raw stream chunk digest when streaming, `tool_stream` setting,
  final answer, model-vs-infrastructure failure classification;
- multimodal artifact: fixture path, fixture digest, license/provenance record,
  content block shape, processor status, response verdict;
- Dynamo lossiness artifact: direct SGLang transcript digest, Dynamo transcript
  digest, compared fields, lossiness verdict, and any dropped-field evidence;
- teardown artifact: process ids, signal sequence, open-port scan, orphan scan;
- archive manifest: relative artifact paths, SHA256 digests, and artifact roles.

Required parent-run artifacts:

- declared config copy;
- local environment copy;
- materialized parent inference config;
- per-component materialized configs;
- resolved bwrap plan;
- preparation records for venvs, model cache, and backend profile;
- process records for SGLang, Dynamo, and Responses;
- log paths;
- port allocation and post-teardown port proof;
- readiness probes;
- inference probes;
- teardown summary;
- `summary.json`;
- `archive-manifest.json`.

Failed runs are blocker evidence. They do not satisfy completion criteria even
when they write useful diagnostics.

## Benchmark Gate

Benchmarks are downstream of the serving verifier. They must not replace it.

The first benchmark profile should reuse the GLM-5.2 harness boundaries:

- coding-agent smoke through Responses;
- code benchmark smoke through the bwrap task runner;
- host-controlled Harbor/Docker only for suites that require that execution
  domain;
- long-context probes that record prompt length, generated tokens, parser
  settings, and timeout;
- optional published-score conformance only after matching source conditions are
  recorded.

Benchmark modes:

- `prepare`: validate pinned datasets, harness revisions, image digests,
  endpoint model identity, bwrap rootfs, Docker/Harbor prerequisites, and
  gold-path/oracle checks without claiming model performance.
- `smoke`: run a small live sample through the run-owned Responses endpoint and
  write complete Contract Artifacts.
- `calibration`: run enough live samples to separate model failures from
  infrastructure failures.
- `conformance`: compare to published or source benchmark claims only after
  source metadata, local run conditions, tolerances, and live evidence match.

GLM-5.3-Flash-specific benchmark conditions to record:

- forced-thinking enabled;
- `reasoning_effort`;
- whether preserved thinking history is included across turns;
- parser versions: `glm45` reasoning and `glm47` tool calls;
- multimodal input type and media token budget for vision tasks;
- total context length attempted versus the model's 1M-token limit;
- output-token limit, especially for Terminal-Bench-style runs;
- agent harness name and version;
- shell, container, or Harbor environment identity;
- wall-clock timeout;
- source suite revision;
- context budget used by the harness;
- mapping between benchmark `max_new_tokens` and Responses
  `max_output_tokens`;
- SGLang speculative decoding / MTP settings;
- KDA state-pool settings and concurrency limits.

Published GLM-5.3-Flash scores are source context, not acceptance criteria for
the local setting. A benchmark artifact may compare to them only after the
run records enough condition metadata to show whether the comparison is valid.

Benchmark execution must enforce these gates:

- every benchmark run references a passing serving `summary.json` and the exact
  `materialized-inference.yaml` digest;
- exact-suite smoke may use a fake Responses endpoint only in unit tests, never
  as live evidence;
- live smoke must record `endpoint` as the run-owned Responses URL, not
  `fixture`;
- calibration and conformance runs must refuse direct SGLang/Dynamo Chat URLs;
- published-score comparison requires benchmark source, dataset revision,
  harness revision, prompt template hash, sampling settings, output-token
  budget, timeout, context limit, and execution backend;
- Terminal-Bench-style profiles must record whether Harbor/Docker runs in the
  host-control domain and must fail if launched inside `scripts/run`.

## Multimodal Profiles

Image input is a required follow-up profile because GLM-5.3-Flash is natively
multimodal and the backend must prove the processor path exists before any
multimodal claim. It is not a blocker for the first text and tool compatibility
tracer bullet. Video and file inputs are explicitly out of the first acceptance
path until separate profiles declare prerequisites and fixtures.

Initial profile requirements:

- one tracked image fixture;
- license/provenance metadata;
- SHA256 digest;
- Chat content blocks with `type: image_url` plus text instruction;
- no network fetch at verifier runtime.

Deferred video profile requirements:

- `torchcodec` availability;
- video fixture provenance and digest;
- 2 FPS sampling condition;
- 240,000 visual-token cap condition;
- timeout and memory budget;
- artifact proving the backend used the video processor path.

Deferred file profile requirements:

- fixture provenance and digest;
- content-block serialization evidence;
- backend parser/processor support;
- explicit benchmark or verifier use case.

## Ticket-Local Decisions

- Ticket 02 records whether the first SGLang live run should use a rootfs venv
  or the `lmsysorg/sglang:glm-5.3-flash` image. The spec recommends rootfs venv first
  for parity with GLM-5.2, with the Docker image recorded as backend
  provenance or a separate profile.
- Ticket 02 records which FP8 path is acceptable locally: native SGLang loading,
  a declared conversion, or a fail-fast unsupported verdict.
- Ticket 05 chooses the tracked image fixture for the multimodal smoke and
  records its license/provenance.
- Ticket 04 proves whether Dynamo preserves the GLM reasoning and tool-call
  response fields without loss. Until that proof passes, the first compatibility
  path routes the Responses adapter directly to SGLang.
- Ticket 01 keeps the first implementation model-scoped under `glm53_flash_*`.
  A later cleanup may decide whether to lift model-specific constants into a
  shared schema runtime after GLM-5.3-Flash is live.

## Acceptance Criteria

- A GLM-5.3-Flash declared SGLang config exists and validates without absolute
  host paths.
- A GLM-5.3-Flash parent inference config exists and composes SGLang and
  Responses through `component://` references; the Dynamo profile additionally
  composes Dynamo between them and passes the lossiness proof.
- The materializer rejects fallback mode, ambient default ports, shell command
  strings, missing parser settings, missing thinking settings, missing model
  identity, and unsupported multimodal declarations.
- The serving verifier produces all Contract Artifacts required for the selected
  profile.
- The first verifier profile proves reasoning separation, tool calls, streaming,
  and `previous_response_id` continuation through the Responses API.
- The multimodal profile proves image input through the Responses API before
  any multimodal compatibility claim.
- Teardown closes every allocated port and records process cleanup.
- Benchmark execution is blocked until the serving verifier has a passing run
  for the same materialized config.

## Suggested Tickets

The first ticket set lives under `.scratch/glm53-flash-local-serving/issues/`:

1. `01-config-schema-and-templates.md`
2. `02-sglang-launch-and-preflight.md`
3. `03-responses-adapter-reasoning.md`
4. `04-serving-verifier-ladder.md`
5. `05-multimodal-smoke-fixture.md`
6. `06-benchmark-profile-wiring.md`
