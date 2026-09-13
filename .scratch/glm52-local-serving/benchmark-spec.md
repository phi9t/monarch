# GLM-5.2 Benchmark Verification Spec

This spec extends the local GLM-5.2 serving verifier from protocol/tool-call
acceptance into coding, long-context, and published-benchmark conformance. The
serving topology remains:

```text
Codex or verifier
  -> Responses adapter
  -> Dynamo frontend
  -> SGLang GLM-5.2
```

The benchmark verifier must not replace the serving verifier. It runs after the
serving verifier proves that the deployment can serve Chat Completions,
Responses streaming, function calls, tool outputs, and cleanup artifacts.

## Goals

- Verify coding-agent behavior, including terminal-style tool calling.
- Use Harbor as the preferred harness for terminal, containerized agent, and
  custom benchmark evaluation.
- Verify long-context behavior expected from the Dynamo GLM-5.2 recipe.
- Compare local quality against pinned published GLM-5.2 benchmark results
  when the official result source, prompt template, decoding profile, and local
  serving profile are compatible.
- Emit machine-readable artifacts that explain every pass, fail, warning, and
  benchmark score.

## Non-Goals

- Do not execute arbitrary model-authored shell commands on the host.
- Do not use Kubernetes, KubeRay, Kueue, or cluster-native jobs for the local
  benchmark runner.
- Do not claim published-score conformance from smoke samples.
- Do not compare a Codex tool-calling profile with thinking disabled against
  published reasoning scores that used a thinking-enabled profile.
- Do not use unpinned moving datasets or prompt templates for conformance.

## Harness Policy

Use Harbor for agentic and terminal-oriented benchmark execution. Harbor is from
the creators of Terminal-Bench and defines the relevant abstractions for this
work:

- A task is an instruction, container environment, and test script.
- A dataset is a collection of tasks and usually corresponds to a benchmark such
  as Terminal-Bench or SWE-bench Verified.
- An agent is a program that completes tasks through Harbor's `BaseAgent` or
  `BaseInstalledAgent` interfaces.
- Environments are containers and can run locally or through supported sandbox
  providers.

For this no-Kubernetes plan, use Harbor's local container execution path first.
External sandbox providers may be useful later for burst capacity, but they are
not part of the local confidence gate.

Primary source:

- Harbor repository: `https://github.com/harbor-framework/harbor`
- Harbor docs: `https://harborframework.com/docs`

For this GLM deployment, Harbor should wrap the local Responses adapter as an
evaluated agent:

```text
Harbor task container
  -> GLM52HarborAgent
  -> http://localhost:8080/v1/responses
  -> Responses adapter
  -> Dynamo/SGLang GLM-5.2
```

The Harbor agent must preserve the Codex-relevant profile:

```yaml
agent:
  type: custom
  import_path: glm52_harbor_agent:GLM52HarborAgent
  responses_base_url: http://localhost:8080/v1
  model: zai-org/GLM-5.2
  stream: true
  tool_loop: true
  thinking: disabled
```

Use Harbor for:

- Terminal-Bench 2.
- SWE-bench Verified when running it as an agent-in-container benchmark.
- Custom terminal/coding tasks that should graduate from the local synthetic
  verifier into reusable task directories.

Use benchmark-native harnesses for:

- HumanEval and MBPP code execution and pass@k scoring.
- RULER prompt generation and long-context task scoring.
- lm-evaluation-harness task definitions when the pinned task config is the
  conformance authority.

The benchmark verifier may still orchestrate Harbor runs so that all GLM-5.2
results land under `glm52-benchmark-results/`.

## No-Kubernetes Local Execution Architecture

Run the benchmark suite as a local evaluation platform. Do not introduce
Kubernetes, KubeRay, Kueue, or cluster-native jobs for the first deployable
system. The local architecture still separates inference, agent harness, task
environment, scoring, and orchestration:

```text
local glm52_benchmark_verifier process
  -> file-backed run manifest and cleanup ledger
  -> suite adapters
      -> Harbor local Docker tasks
      -> native benchmark harnesses inside scripts/run
      -> bwrap rootfs task sandboxes
      -> isolated code-execution containers when official images are required
  -> model-under-test endpoints
      -> http://localhost:8080/v1/responses
      -> http://localhost:8000/v1/chat/completions
  -> glm52-benchmark-results/<run-id> artifacts
```

The local verifier is the durable outer control point for one machine:

- It writes a run record before starting a suite.
- It records every spawned process, bwrap task sandbox, Docker container,
  temporary directory, dataset checkout, and artifact path that must be cleaned
  up.
- It can resume by reading the run record and skipping completed task results
  whose input manifest hash still matches.
- It can clean up after its own crash through the same host-side deployment
  cleanup helper used by serving.

The verifier does not own model serving. Dynamo, SGLang, and the Responses
adapter are separately launched local services. The verifier only checks that
their declared endpoints are reachable, records their `/v1/models` responses,
and stores the serving verifier summary as an input artifact.

### Local process boundaries

Use these execution domains:

```text
Host process domain
  - scripts/run_glm52_deployment.sh
  - bwrap task-sandbox launcher and cleanup
  - Docker or podman CLI
  - Harbor local container provider
  - host-side cleanup of PIDs, ports, task roots, and containers

Monarch rootfs domain
  - scripts/run_glm52_benchmark_verifier.sh
  - Python prompt rendering, scoring, and result collation
  - native harnesses that do not need host Docker access

Bwrap task sandbox domain
  - HumanEval and MBPP generated-code execution when official Docker images are
    not required
  - static benchmark harnesses that need a fresh writable workspace
  - custom terminal/coding tasks whose scoring is owned by this verifier

Container sandbox domain
  - Harbor task containers
  - SWE-bench and Terminal-Bench environments
  - generated-code execution for HumanEval and MBPP when containerized by an
    official harness
```

Do not mount the host Docker socket into a model-controlled task container. The
trusted local runner may create containers, but the agent and task shell must
only see the task environment that Harbor or the native harness exposes.

Prefer the Monarch bwrap rootfs for local verifier-owned execution. Prefer
Docker or podman only when the benchmark's official scoring contract includes a
specific task image, container runtime behavior, or Harbor provider.

### Bwrap rootfs execution backend

The bwrap backend is a first-class local sandbox option. It reuses the Monarch
rootfs userland and toolchain, but each benchmark task receives a fresh task
root rather than writing directly into the repository checkout.

Use bwrap for:

- Native benchmark harnesses that can run inside the Monarch rootfs.
- HumanEval and MBPP generated-code execution when the harness does not require
  an official Docker image.
- GSM8K, AIME, lm-evaluation-harness, RULER, and needle-smoke runs.
- Custom pre-Codex terminal tasks owned by this verifier.

Do not use bwrap as the conformance backend for:

- Terminal-Bench 2 tasks whose official release expects Harbor container
  execution.
- SWE-bench Verified runs whose official evaluator depends on per-instance
  Docker images.
- Any benchmark whose published score is tied to a named container image,
  provider, or filesystem image.

The planned launcher is:

```text
scripts/glm52_bwrap_task_runner.py
scripts/run_glm52_bwrap_task_runner.sh
```

`run_glm52_bwrap_task_runner.sh` is host-side because it must launch bwrap,
track host PIDs, and clean task roots. The task payload itself executes inside
the rootfs.

Each bwrap task sandbox has:

```text
.scratch/glm52-local-serving/run/bwrap/<run-id>/<task-id>/
  input/
  work/
  output/
  tmp/
  task.json
```

Default restrictions:

- Mount the Monarch rootfs read-only.
- Mount only the task `input/` read-only.
- Mount task `work/`, `output/`, and `tmp/` read-write.
- Hide GPUs unless the suite explicitly requests them.
- Disable network by default for generated-code execution.
- Enable network only for model-client or dataset-fetch phases, never for
  untrusted generated code.
- Preserve only the GLM endpoint variables and the minimal rootfs environment
  required by `scripts/run`.
- Use `--die-with-parent` and record the host PID in the cleanup ledger.

The existing `scripts/run` rootfs remains the default for trusted verifier code.
The bwrap task backend is stricter and task-scoped; it must not give
model-authored code write access to the full checkout.

Backend selection is explicit in the benchmark manifest:

```yaml
execution_backend:
  type: bwrap_rootfs
  network: disabled
  gpu: none
  writable_mount: task_workdir
```

Allowed backend values are:

```text
bwrap_rootfs
scripts_run
local_docker
harbor_local_docker
host_subprocess
```

`host_subprocess` is allowed only for trusted preparation and scoring helpers.
It must never execute model-authored code.

### Local orchestration state

Every run writes a local ledger before executing work:

```text
.scratch/glm52-local-serving/run/
  benchmark-<run-id>.json
  benchmark-<run-id>.lock
  cleanup-<run-id>.json
```

The benchmark run record contains:

```json
{
  "schema_version": 1,
  "run_id": "2026-08-15T000000Z-smoke",
  "mode": "smoke",
  "status": "running",
  "created_at": "2026-08-15T00:00:00Z",
  "manifest_sha256": "...",
  "published_scores_sha256": "...",
  "serving_summary_path": "glm52-serving-results/summary.json",
  "responses_base_url": "http://localhost:8080/v1",
  "chat_base_url": "http://localhost:8000/v1",
  "suites": [
    {
      "id": "terminal-bench-2",
      "status": "running",
      "tasks_total": 3,
      "tasks_completed": 1,
      "artifact_dir": "glm52-benchmark-results/2026-08-15T000000Z-smoke/terminal-bench-2"
    }
  ]
}
```

The cleanup record contains only host-observable resources:

```json
{
  "schema_version": 1,
  "run_id": "2026-08-15T000000Z-smoke",
  "processes": [
    {"pid": 12345, "description": "harbor run", "command_contains": "harbor"}
  ],
  "bwrap_tasks": [
    {
      "pid": 23456,
      "task_root": ".scratch/glm52-local-serving/run/bwrap/2026-08-15T000000Z-smoke/task-001",
      "command_contains": "glm52_bwrap_task_runner"
    }
  ],
  "containers": [
    {"id": "abc123", "name": "glm52-tbench-task-...", "labels": {"glm52.run_id": "..."}}
  ],
  "temp_dirs": [
    ".scratch/glm52-local-serving/run/tmp/2026-08-15T000000Z-smoke"
  ],
  "ports": []
}
```

Cleanup is best-effort and idempotent. It must refuse to kill a PID unless the
current command line still matches the recorded command guard.

### Local storage layout

Use local disk, not object storage, for the initial deployment:

```text
.scratch/glm52-local-serving/
  benchmarks/
    benchmark-manifest.yaml
    published-scores.yaml
    datasets/
    harnesses/
    images/
  harbor/
    configs/
    agents/
    datasets/
  run/
    benchmark-<run-id>.json
    cleanup-<run-id>.json
    bwrap/
      <run-id>/
        <task-id>/

glm52-benchmark-results/
  <run-id>/
    run.json
    environment.json
    benchmark-manifest.json
    published-scores.json
    harbor/
      trials.jsonl
      artifacts/
    summary.json
    <suite>/
      samples.jsonl
      metrics.json
      failures.jsonl
```

Large downloaded datasets and container images may be cached under
`.scratch/glm52-local-serving/benchmarks/`, but every scored run must record the
exact revision, content hash, or image digest used. Results remain outside
`.scratch/` so they are easy to archive or compare.

### Local execution pools

The local runner has named pools rather than scheduler classes:

```yaml
pools:
  model_server:
    endpoint_only: true
    responses_base_url: http://localhost:8080/v1
    chat_base_url: http://localhost:8000/v1
  static:
    max_concurrency: 4
    runner: scripts/run
  code_sandbox:
    max_concurrency: 2
    runner: bwrap_rootfs
    network: disabled
    gpu: none
  code_container:
    max_concurrency: 1
    runner: local_docker
    network: disabled
  harbor_terminal:
    max_concurrency: 1
    runner: harbor
    environment: local_docker
  long_context:
    max_concurrency: 1
    runner: scripts/run
```

Default local concurrency must be conservative. Start with one Harbor terminal
task, one long-context task, and at most two bwrap generated-code sandboxes
until model latency, scratch use, and memory pressure are measured. Keep Docker
concurrency at one until image disk use and setup time are known.

### Prefetch and gold-path validation

Before any scored run, the local verifier must support a `prepare` stage that:

- Clones or updates pinned benchmark harness repositories into
  `.scratch/glm52-local-serving/benchmarks/harnesses/`.
- Downloads pinned datasets into
  `.scratch/glm52-local-serving/benchmarks/datasets/`.
- Builds or validates the Monarch bwrap rootfs.
- Pulls or builds required Docker images and records immutable image digests
  when a selected suite uses Docker or Harbor.
- Installs or verifies Harbor in the Monarch rootfs.
- Verifies the Responses and Chat endpoints with `/v1/models`.
- Runs benchmark-native oracle or gold checks when available.

Gold-path checks are required before scaling a suite:

- Terminal-Bench and Harbor tasks must pass their reference or oracle path when
  the upstream task provides one.
- SWE-bench smoke must run at least one gold patch through the official
  evaluator before model patches are scored.
- HumanEval and MBPP sandboxes must pass known-good and known-bad fixtures.
- Bwrap sandbox smoke must prove generated code cannot write outside the task
  workdir and cannot use the network when `network: disabled`.
- GSM8K and AIME extractors must pass fixed answer-extraction fixtures.
- Needle-smoke must pass a deterministic local answer fixture before the model
  is called.

### Failure taxonomy

Every task result uses one of these states:

```text
passed
task_failed
model_timeout
model_protocol_error
tool_protocol_error
environment_setup_failed
environment_crashed
grader_failed
cancelled
skipped
```

Infrastructure failures are not counted as model failures, but they remain in
the published run summary with their own denominator and failure rate.

### Optional durable scheduler

A local Temporal server may be added later if repeated long benchmark campaigns
need durable retries across daemon restarts. It is not required for the first
implementation, and it must remain an outer orchestrator only. It must not move
model serving or sandbox execution into Kubernetes.

## Benchmark Profiles

Every benchmark run declares one profile. Scores are comparable only within a
profile.

### `codex-tool-calling`

Purpose: prove the model can operate as a coding agent through the Responses
adapter.

Configuration:

```yaml
endpoint: responses
stream: true
tools: enabled
chat_template_kwargs:
  enable_thinking: false
temperature: 0
top_p: 1
max_output_tokens: 1024
```

Required suites:

- `terminal-bench-smoke`
- `terminal-bench-2`
- `repo-tool-loop-smoke`
- `tool-error-recovery-smoke`
- `long-conversation-tool-loop-smoke`

This is the profile that gates Codex use.

### `math-reasoning`

Purpose: measure mathematical reasoning against short-form and competition
math benchmarks.

Configuration:

```yaml
endpoint: chat
stream: false
tools: disabled
temperature: 0
top_p: 1
max_output_tokens: 4096
```

Thinking-enabled and thinking-disabled math runs are separate profiles. Use the
thinking-enabled profile for published conformance only when the official
published GLM-5.2 result used thinking.

### `coding-benchmark`

Purpose: measure standalone code generation quality against public coding
benchmarks.

Configuration:

```yaml
endpoint: chat
stream: false
tools: disabled
temperature: 0.2
top_p: 0.95
samples_per_problem: 1
```

This profile may need profile-specific prompt templates for each benchmark.
Do not reuse Codex tool prompts for HumanEval or MBPP.

### `long-context`

Purpose: verify the advertised long-context serving path and Dynamo cache
behavior.

Configuration:

```yaml
endpoint: chat
stream: false
tools: disabled
temperature: 0
top_p: 1
context_lengths: [64000, 128000, 256000]
```

For B200 NVFP4, an optional 500K tier may be added after the 256K tier passes
and the local deployment advertises that context window.

### `published-conformance`

Purpose: compare against published GLM-5.2 results.

Configuration requirements:

- A primary-source citation for the published score.
- Exact model identity, precision, prompt template, and decoding settings.
- Local profile matching the published profile, or an explicit incompatibility
  note that prevents conformance claims.
- A tolerance model based on sample size and expected variance.

If any requirement is missing, the benchmark may run in calibration mode but
must not report conformance.

## Suite 1: Terminal Bench

Status: first slice implemented inside `scripts/glm52_serving_verifier.py` as
`--terminal-bench`.

Purpose: test terminal-shaped coding-agent tool calling without exposing host
shell access.

Tools:

- `terminal_run`
- `terminal_read_file`
- `terminal_write_file`

Configuration:

```yaml
id: terminal-bench-smoke
profile: codex-tool-calling
endpoint: responses
stream: true
max_turns: 8
allowlisted_commands:
  - python -m pytest
  - pytest
  - uv run pytest
writable_files:
  - src/slug.py
expected:
  final_contains:
    - "TERMINAL_BENCH: PASS"
    - "PATCHED: src/slug.py"
    - "TESTS:"
  required_tool_sequence:
    - terminal_run
    - terminal_read_file
    - terminal_write_file
    - terminal_run
```

Acceptance:

- First test run may fail.
- The model must inspect the file.
- The model must write `src/slug.py`.
- A later test run must return `exit_code: 0`.
- The final answer must report pass, patched file, and test command.

Artifacts:

```text
glm52-serving-results/responses-terminal-bench.json
```

Proper configuration:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench
```

The terminal bench should become the minimum coding-tool benchmark before
connecting Codex to the adapter.

## Suite 2: Repo Tool Loop

Status: implemented as the default `responses-agent` and `chat-agent` stages.

Purpose: test file listing, file reads, arithmetic over tool outputs, and final
structured answer.

Configuration:

```yaml
id: repo-tool-loop-smoke
profile: codex-tool-calling
endpoint: responses
stream: true
max_turns: 8
tools:
  - list_project_files
  - read_project_file
required_reads:
  - README.md
  - src/alpha.py
  - src/beta.py
expected:
  final_contains:
    - "FINAL_SCORE: 19"
    - "RISKS: src/alpha.py"
```

Acceptance:

- At least four tool calls.
- Required files must be read.
- Final score and risky module must match.

Proper configuration:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-chat
```

## Suite 3: Tool Error Recovery

Status: proposed.

Purpose: test whether the model can recover from a terminal or file-tool error.

Scenario:

- Ask the model to run tests.
- The first `terminal_run` returns an allowlist error when the model tries a
  non-allowed command such as `python tests/test_slug.py`.
- The model must recover by running `python -m pytest`.

Configuration:

```yaml
id: tool-error-recovery-smoke
profile: codex-tool-calling
endpoint: responses
stream: true
max_turns: 8
expected:
  must_observe_tool_error: true
  must_later_call:
    name: terminal_run
    arguments:
      command: python -m pytest
```

Acceptance:

- The run must include a tool-error output.
- The model must call a valid tool after the error.
- The final answer must be based on the recovered tool result.

Implementation note:

- Tool-error outputs should be normal function-call outputs, not HTTP errors.
  Codex-style agents must learn from tool failures inside the conversation.

## Suite 4: Long Conversation Tool Loop

Status: proposed.

Purpose: test process-local `previous_response_id` state and multi-turn
continuation under Codex-like load.

Scenario:

- The model must make 8-20 short tool calls across multiple Responses turns.
- Each turn depends on the prior tool output.
- The final answer must summarize the accumulated state.

Configuration:

```yaml
id: long-conversation-tool-loop-smoke
profile: codex-tool-calling
endpoint: responses
stream: true
turn_count: 12
requires_previous_response_id: true
```

Acceptance:

- Every turn after the first must use the prior `previous_response_id`.
- Unknown previous IDs must fail explicitly.
- A completed run must preserve all tool results in the final answer.

Operational note:

- This suite must run against a single adapter process or sticky routing. The
  checked-in adapter keeps continuation state in memory.

## Suite 5: HumanEval

Status: proposed.

Primary source:

- OpenAI HumanEval repository: `https://github.com/openai/human-eval`

Purpose: test Python code-generation pass@1 or pass@k on hand-written function
completion tasks.

Proper configuration:

```yaml
id: humaneval
profile: coding-benchmark
endpoint: chat
stream: false
tools: disabled
dataset_source:
  type: git
  url: https://github.com/openai/human-eval
  revision: <pinned commit>
metric: pass@1
execution:
  sandbox: required
  execution_backend: bwrap_rootfs
  network: disabled
  gpu: none
  timeout_seconds_per_problem: 10
decoding:
  temperature: 0.2
  top_p: 0.95
  samples_per_problem: 1
```

Acceptance modes:

- Smoke: run 5 fixed problems and require no harness errors.
- Calibration: run the full dataset and record pass@1, no published comparison.
- Conformance: compare against a pinned GLM-5.2 HumanEval score from a primary
  GLM-5.2 source using a declared tolerance.

Implementation requirements:

- Run generated code in an isolated process with CPU, memory, filesystem, and
  timeout limits.
- Prefer the bwrap rootfs backend for local smoke, calibration, and
  conformance unless the pinned HumanEval harness explicitly requires Docker.
- Store every completion, test result, traceback, and pass/fail result.
- Never run generated code in the verifier process.

Artifacts:

```text
glm52-benchmark-results/humaneval/samples.jsonl
glm52-benchmark-results/humaneval/metrics.json
glm52-benchmark-results/humaneval/failures.jsonl
```

## Suite 6: MBPP

Status: proposed.

Primary source:

- Google Research MBPP: `https://github.com/google-research/google-research/tree/master/mbpp`

Purpose: test entry-level Python programming tasks with natural-language
problem statements and tests.

Proper configuration:

```yaml
id: mbpp
profile: coding-benchmark
endpoint: chat
stream: false
tools: disabled
dataset_source:
  type: git
  url: https://github.com/google-research/google-research
  revision: <pinned commit>
  path: mbpp
metric: pass@1
split: test
execution:
  sandbox: required
  execution_backend: bwrap_rootfs
  network: disabled
  gpu: none
  timeout_seconds_per_problem: 10
decoding:
  temperature: 0.2
  top_p: 0.95
  samples_per_problem: 1
```

Acceptance modes:

- Smoke: run 10 fixed tasks.
- Calibration: run the configured split.
- Conformance: compare only after a primary GLM-5.2 MBPP score is pinned.

Implementation requirements:

- Normalize prompt templates and stop sequences.
- Persist the exact prompt used per task.
- Prefer the bwrap rootfs backend for local smoke, calibration, and
  conformance unless the pinned MBPP harness explicitly requires Docker.
- Keep MBPP separate from HumanEval because prompt and scoring conventions
  differ.

## Suite 7: SWE-bench Verified

Status: proposed, expensive optional gate.

Primary source:

- SWE-bench repository and docs: `https://github.com/swe-bench/SWE-bench`
- SWE-bench site: `https://swebench.com/`

Purpose: test real repository issue resolution with generated patches.

Proper configuration:

```yaml
id: swe-bench-verified
profile: coding-agent
endpoint: responses
stream: true
tools: enabled
harness: harbor
dataset_source:
  type: huggingface_or_swebench
  dataset: SWE-bench Verified
  revision: <pinned revision>
execution:
  harness: harbor
  dataset_adapter: swebench_verified
  execution_backend: harbor_local_docker
  docker: required
  timeout_seconds_per_instance: 1800
subset:
  smoke_instances: <small pinned list>
  conformance_instances: full_verified_or_declared_subset
metric: resolved_percent
```

Acceptance modes:

- Smoke: 1-3 pinned instances, validates infrastructure only.
- Calibration: a pinned subset, reports resolved percent.
- Conformance: compare against a pinned published GLM-5.2/SWE-agent-style
  result only if the agent scaffold, tools, and budget match the source.

Implementation requirements:

- Use the official SWE-bench harness.
- Prefer Harbor as the outer execution harness when it can run the pinned
  SWE-bench Verified dataset without changing scoring semantics.
- Do not replace the official SWE-bench per-instance Docker images with bwrap
  for conformance runs.
- Store patches, logs, test output, and instance metadata.
- Treat Docker image build failures separately from model failures.
- Do not run this as part of the default pre-Codex gate; it is too slow.

## Suite 8: Terminal-Bench 2

Status: proposed, official terminal-agent gate.

Primary source:

- Terminal-Bench 2 benchmark page: `https://www.tbench.ai/benchmarks/terminal-bench-2`
- Terminal-Bench repository: `https://github.com/laude-institute/terminal-bench`

Purpose: test terminal-native coding-agent behavior with the official
Terminal-Bench task suite instead of the local synthetic terminal smoke test.

Proper configuration:

```yaml
id: terminal-bench-2
profile: codex-tool-calling
endpoint: responses
stream: true
tools: enabled
harness_source:
  type: git
  url: https://github.com/harbor-framework/harbor
  revision: <pinned commit>
benchmark_source:
  type: web_or_harness_release
  url: https://www.tbench.ai/benchmarks/terminal-bench-2
  revision: <pinned release or content hash>
execution:
  harness: harbor
  dataset: terminal-bench-2
  execution_backend: harbor_local_docker
  container: required
  timeout_seconds_per_task: 1800
subset:
  smoke_tasks: <small pinned task list>
  calibration_tasks: terminal_bench_2_declared_subset_or_full
metric: success_rate
```

Acceptance modes:

- Smoke: 1-3 pinned tasks, validates adapter-to-terminal-harness integration.
- Calibration: a pinned subset or the full Terminal-Bench 2 task list, reports
  success rate.
- Conformance: compare only to a primary Terminal-Bench 2 leaderboard or GLM-5.2
  result when the agent harness, timeout, container image, and tool budget match.

Implementation requirements:

- Keep the model in the Responses tool loop so this remains a Codex-relevant
  benchmark.
- Run task commands only inside the Terminal-Bench container or sandbox.
- Use Harbor's local Docker backend for conformance unless the pinned
  Terminal-Bench 2 release publishes an equivalent bwrap environment contract.
- Store terminal transcripts, file diffs, test output, task metadata, and
  harness version.
- Store Harbor trial IDs, task IDs, dataset revision, environment provider, and
  agent version.
- Treat task setup failures separately from model failures.
- Keep the local `terminal-bench-smoke` as the cheap preflight before running
  Terminal-Bench 2.

## Suite 9: RULER / Long-Context Synthetic Tasks

Status: proposed.

Primary source:

- NVIDIA RULER repository: `https://github.com/NVIDIA/RULER`

Purpose: test the effective context window and retrieval/reasoning over long
inputs.

Proper configuration:

```yaml
id: ruler
profile: long-context
endpoint: chat
stream: false
tools: disabled
dataset_source:
  type: git
  url: https://github.com/NVIDIA/RULER
  revision: <pinned commit>
tasks:
  - needle
  - multi_needle
  - variable_tracking
context_lengths:
  - 64000
  - 128000
  - 256000
metric: exact_match_or_task_accuracy
decoding:
  temperature: 0
  top_p: 1
```

Acceptance:

- 64K must pass before running 128K.
- 128K must pass before running 256K.
- 500K is optional and B200-profile-only until the local deployment advertises
  it.
- Failures must distinguish context-window rejection, timeout, malformed
  answer, and wrong answer.

Dynamo-specific checks:

- Record request latency and token counts.
- When Dynamo exposes cache telemetry, record prefix-cache hit rate.
- Repeat the same prefix with different suffix questions and compare latency or
  cache metrics between first and later requests.

## Suite 10: Needle-In-Haystack Smoke

Status: proposed lightweight long-context gate.

Purpose: provide a cheap local long-context check without pulling the full RULER
harness.

Configuration:

```yaml
id: needle-smoke
profile: long-context
endpoint: chat
context_lengths:
  - 64000
  - 128000
  - 256000
needles:
  - key: deployment_cleanup_token
    value: ORCHID-7194
metric: exact_match
```

Acceptance:

- The model must return the exact token.
- The prompt generator must place the needle near the beginning, middle, and
  end across separate cases.
- Every generated prompt must be saved by hash and reproducible seed.

This suite should run before RULER because it catches context plumbing failures
quickly.

## Suite 11: GSM8K

Status: proposed.

Primary source:

- OpenAI Grade School Math / GSM8K repository:
  `https://github.com/openai/grade-school-math`

Purpose: test grade-school multi-step math reasoning with exact final-answer
extraction.

Proper configuration:

```yaml
id: gsm8k
profile: math-reasoning
endpoint: chat
stream: false
tools: disabled
dataset_source:
  type: git
  url: https://github.com/openai/grade-school-math
  revision: <pinned commit>
split: test
metric: exact_match_final_answer
answer_extraction:
  pattern: "#### <answer>"
decoding:
  temperature: 0
  top_p: 1
  max_output_tokens: 2048
```

Acceptance modes:

- Smoke: 20 fixed examples covering arithmetic, ratios, and multi-step word
  problems.
- Calibration: full GSM8K test split, reports exact-match final-answer
  accuracy.
- Conformance: compare only after a primary GLM-5.2 GSM8K score is pinned for
  the same prompt style and thinking profile.

Implementation requirements:

- Store the prompt, raw response, extracted final answer, expected answer, and
  normalization result for every sample.
- Score only the final extracted answer, not explanatory text.
- Keep prompt templates versioned because GSM8K scores are sensitive to
  few-shot vs. zero-shot vs. chain-of-thought prompting.

## Suite 12: AIME

Status: proposed.

Primary source:

- The AIME problem set must be pinned from the exact harness or dataset used for
  comparison. Candidate harnesses include lm-evaluation-harness tasks when
  available in the pinned revision, or a pinned competition-math dataset derived
  from the MATH/AIME family.
- MATH dataset repository for competition-math source context:
  `https://github.com/hendrycks/math`

Purpose: test contest-style mathematical reasoning with integer final answers.

Proper configuration:

```yaml
id: aime
profile: math-reasoning
endpoint: chat
stream: false
tools: disabled
dataset_source:
  type: harness_task_or_pinned_dataset
  name: aime
  revision: <pinned revision>
years:
  - <pinned year list>
metric: exact_match_integer_answer
answer_range: [0, 999]
decoding:
  temperature: 0
  top_p: 1
  max_output_tokens: 8192
```

Acceptance modes:

- Smoke: 5 pinned problems with known integer answers.
- Calibration: the pinned AIME set, reports exact-match accuracy.
- Conformance: compare only against a primary GLM-5.2 AIME score that uses the
  same AIME year set, prompt style, answer extraction, and thinking profile.

Implementation requirements:

- The manifest must name the exact AIME year set. `AIME` alone is not a stable
  benchmark identity.
- Extract the final integer answer and reject answers outside `[0, 999]` unless
  the pinned harness defines a different scoring rule.
- Keep AIME separate from GSM8K because prompt length, difficulty, and answer
  extraction differ materially.

## Suite 13: lm-evaluation-harness Reasoning Benchmarks

Status: proposed.

Primary source:

- EleutherAI lm-evaluation-harness: `https://github.com/EleutherAI/lm-evaluation-harness`

Purpose: run broad academic and reasoning tasks such as MMLU-Pro, GPQA, IFEval,
GSM8K, and AIME when the tasks and published GLM-5.2 sources are pinned in the
selected harness revision.

Proper configuration:

```yaml
id: lm-eval
profile: published-conformance
endpoint: chat
stream: false
tools: disabled
harness_source:
  type: git
  url: https://github.com/EleutherAI/lm-evaluation-harness
  revision: <pinned commit>
tasks:
  - <task names supported by pinned harness>
decoding:
  temperature: 0
  top_p: 1
```

Acceptance:

- Calibration mode may run any supported task and report scores.
- Conformance mode requires a primary GLM-5.2 published score for the same task,
  model, prompt mode, and decoding profile.
- Thinking-enabled and thinking-disabled runs must be separate profiles.
- For GSM8K and AIME, prefer the dedicated suite specs above when the harness
  task configuration is ambiguous or changes across revisions.

Implementation requirements:

- Use the harness through an OpenAI-compatible local-completions adapter only
  when the request shape is verified.
- Store harness config, harness revision, task list, and raw result JSON.
- Do not mix harness scores into Codex readiness unless the task exercises
  coding-agent behavior.

## Published Score Manifest

Conformance depends on a checked-in manifest. Example:

```yaml
schema_version: 1
model: zai-org/GLM-5.2
source:
  title: GLM-5.2 official benchmark table
  url: <primary source>
  accessed: 2026-08-15
deployment_profiles:
  codex-tool-calling:
    thinking: disabled
    endpoint: responses
    comparable_to_published: false
  reasoning-thinking-enabled:
    thinking: enabled
    endpoint: chat
    comparable_to_published: true
benchmarks:
  humaneval:
    profile: coding-benchmark
    metric: pass@1
    expected: <pinned value>
    tolerance_abs: 0.03
    source_url: <primary source>
    comparable: true
  mbpp:
    profile: coding-benchmark
    metric: pass@1
    expected: <pinned value>
    tolerance_abs: 0.03
    source_url: <primary source>
    comparable: true
  terminal-bench-2:
    profile: codex-tool-calling
    metric: success_rate
    expected: <pinned value>
    tolerance_abs: 0.02
    source_url: https://www.tbench.ai/benchmarks/terminal-bench-2
    comparable: true
  gsm8k:
    profile: math-reasoning
    metric: exact_match_final_answer
    expected: <pinned value>
    tolerance_abs: 0.02
    source_url: <primary source>
    comparable: true
  aime:
    profile: math-reasoning
    metric: exact_match_integer_answer
    expected: <pinned value>
    tolerance_abs: 0.05
    source_url: <primary source>
    comparable: true
```

Rules:

- `expected` must not be filled from secondary articles.
- `source_url` must point to the source that owns the score.
- `comparable: false` prevents a conformance pass/fail claim.
- Tolerance must be explicit per benchmark.
- Missing manifest entries fail conformance mode before inference starts.

## Harness Layout

Target files for implementation:

```text
scripts/glm52_benchmark_verifier.py
scripts/run_glm52_benchmark_verifier.sh
scripts/glm52_harbor_agent.py
python/tests/test_glm52_benchmark_verifier.py
python/tests/test_glm52_harbor_agent.py
.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml
.scratch/glm52-local-serving/benchmarks/published-scores.yaml
```

The shell entrypoint must be thin and rootfs-aware. Dataset fetch, prompt
rendering, scoring, tolerance checks, and artifact writing live in testable
Python helpers.

Harbor-specific implementation:

```text
.scratch/glm52-local-serving/harbor/
  configs/
    terminal-bench-2-smoke.yaml
    terminal-bench-2-calibration.yaml
    swe-bench-verified-smoke.yaml
  agents/
    glm52_harbor_agent.py
  datasets/
    terminal-bench-2.lock.yaml
    swe-bench-verified.lock.yaml
```

`glm52_harbor_agent.py` should implement Harbor's agent interface and translate
task observations into Responses requests. It should not bypass the checked-in
Responses adapter.

## Result Artifacts

Benchmark runs write:

```text
glm52-benchmark-results/
  run.json
  environment.json
  benchmark-manifest.json
  published-scores.json
  harbor/
    trials.jsonl
    artifacts/
  summary.json
  <suite>/
    samples.jsonl
    metrics.json
    failures.jsonl
```

Each sample record includes:

```json
{
  "suite": "humaneval",
  "case_id": "HumanEval/0",
  "profile": "coding-benchmark",
  "prompt_sha256": "...",
  "response": "...",
  "parsed_answer": "...",
  "passed": true,
  "score": 1.0,
  "latency_seconds": 1.23,
  "usage": {},
  "endpoint": "chat",
  "decoding": {"temperature": 0.2, "top_p": 0.95},
  "dataset_revision": "...",
  "harness_revision": "..."
}
```

## Configuration Flow

1. Run the serving verifier:

   ```sh
   GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
   GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
     scripts/run_glm52_serving_verifier.sh --terminal-bench
   ```

2. Create or refresh benchmark manifests:

   ```sh
   scripts/run_glm52_benchmark_verifier.sh prepare \
     --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml
   ```

   The prepare stage must not launch a scored model run. It resolves pinned
   benchmark revisions, verifies local endpoint reachability, prepares dataset
   and harness caches, validates the bwrap rootfs, records Docker image digests
   for Docker-backed suites, and writes a run-ready manifest hash.

3. Validate the bwrap rootfs backend:

   ```sh
   scripts/run true

   scripts/run_glm52_benchmark_verifier.sh smoke \
     --suite bwrap-sandbox-smoke \
     --pool code_sandbox \
     --execution-backend bwrap_rootfs \
     --run-id bwrap-smoke-$(date -u +%Y%m%dT%H%M%SZ)
   ```

   The sandbox smoke should prove that a task can write inside its task
   workdir, cannot write into the repository checkout, and cannot reach the
   network when `network: disabled`.

4. Install or validate Harbor in the rootfs:

   ```sh
   scripts/run uv tool install harbor
   scripts/run harbor --help
   ```

   Pin the Harbor version in the benchmark manifest before conformance. Harbor
   currently requires Python 3.12, which matches the Monarch rootfs.

   Harbor commands that only inspect CLI availability can run inside
   `scripts/run`. Harbor commands that create Docker containers must be launched
   by the trusted host-side benchmark runner so they can reach the host
   container runtime without exposing Docker control to the model.

5. Validate local Docker or podman access for Harbor-backed suites:

   ```sh
   docker version
   docker info
   ```

   The benchmark verifier should record the container runtime version and reject
   Harbor suites when the runtime is missing. It should not skip silently,
   because Terminal-Bench and SWE-bench smoke results are only meaningful when
   the sandbox actually started.

   This step is optional when running only bwrap-backed suites such as
   HumanEval, MBPP, GSM8K, AIME, RULER, and needle-smoke.

6. Run smoke suites:

   ```sh
   GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
   GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
     scripts/run_glm52_benchmark_verifier.sh smoke \
       --run-id smoke-$(date -u +%Y%m%dT%H%M%SZ)
   ```

   The smoke command writes:

   ```text
   .scratch/glm52-local-serving/run/benchmark-<run-id>.json
   .scratch/glm52-local-serving/run/cleanup-<run-id>.json
   glm52-benchmark-results/<run-id>/summary.json
   ```

7. Run bwrap-backed code-generation smoke:

   ```sh
   GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
     scripts/run_glm52_benchmark_verifier.sh smoke \
       --suite humaneval --suite mbpp \
       --pool code_sandbox \
       --execution-backend bwrap_rootfs \
       --run-id code-bwrap-smoke-$(date -u +%Y%m%dT%H%M%SZ)
   ```

   Generated code runs in per-task bwrap roots under
   `.scratch/glm52-local-serving/run/bwrap/<run-id>/`. It must not execute in
   the verifier process or the repository checkout.

8. Run Harbor-backed Terminal-Bench 2 smoke locally:

   ```sh
   GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
     scripts/run_glm52_benchmark_verifier.sh smoke \
       --suite terminal-bench-2 \
       --pool harbor_terminal \
       --local-container-runtime docker \
       --run-id tbench2-smoke-$(date -u +%Y%m%dT%H%M%SZ)
   ```

   The verifier should invoke Harbor with the pinned task config and custom
   GLM52 Harbor agent, then copy Harbor trial artifacts into
   `glm52-benchmark-results/<run-id>/harbor/`.

   Harbor task containers must reach the adapter through an explicit local host
   route. On Linux Docker this is usually `host.docker.internal` with
   `--add-host=host.docker.internal:host-gateway`, or host networking for a
   trusted local development run. Record the chosen route in
   `environment.json`.

9. Inspect status or clean up after interruption:

   ```sh
   scripts/run_glm52_deployment.sh status \
     --state .scratch/glm52-local-serving/run/cleanup-<run-id>.json

   scripts/run_glm52_deployment.sh cleanup \
     --state .scratch/glm52-local-serving/run/cleanup-<run-id>.json
   ```

   Cleanup is host-side. Do not run it through `scripts/run`, because it must
   see host PIDs, bwrap task processes, task roots, and containers.

10. Run calibration:

   ```sh
   GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
     scripts/run_glm52_benchmark_verifier.sh calibration \
       --suite humaneval --suite mbpp --suite needle-smoke \
       --execution-backend bwrap_rootfs \
       --run-id calibration-$(date -u +%Y%m%dT%H%M%SZ)
   ```

11. Run conformance only after published scores are pinned:

   ```sh
   GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
     scripts/run_glm52_benchmark_verifier.sh conformance \
       --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
       --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
       --run-id conformance-$(date -u +%Y%m%dT%H%M%SZ)
   ```

   In conformance mode, backend selection comes from the pinned manifest. The
   runner must reject command-line backend overrides that would change a
   published-score condition.

12. Archive results:

   ```sh
   tar -C glm52-benchmark-results \
     -czf glm52-benchmark-results/<run-id>.tar.gz <run-id>
   ```

   Archive only after `summary.json` marks the run terminal. Do not delete the
   cleanup ledger until cleanup has been run or all recorded resources have been
   observed gone.

## Promotion Criteria

### Codex readiness

Required:

- Serving verifier passes.
- Responses verifier passes.
- Terminal bench passes.
- Long conversation tool loop passes when implemented.

Published academic conformance is not required for initial Codex readiness.

### Quality confidence

Required:

- HumanEval calibration complete.
- MBPP calibration complete.
- GSM8K calibration complete.
- AIME smoke complete.
- Needle-smoke passes at intended context lengths.
- RULER subset passes at 64K and 128K.
- Terminal-Bench 2 smoke complete.

### Published conformance

Required:

- Published-score manifest fully populated from primary sources.
- Matching local profile for each compared score.
- Full benchmark run for each compared suite.
- Local score within tolerance.

## Open Decisions

- Which official GLM-5.2 benchmark table is authoritative for published scores.
- Whether B200 NVFP4 and H200 FP8 should have separate published-score manifests.
- Whether conformance should use thinking-enabled Chat mode for reasoning tasks
  while Codex readiness uses thinking-disabled Responses mode.
- Whether SWE-bench should use the checked-in Responses adapter directly or a
  fuller Codex-like harness that can edit real worktrees.
- Which AIME year set and harness are authoritative for GLM-5.2 conformance.
- Which Terminal-Bench 2 task list, container images, and timeout are
  authoritative for conformance.
