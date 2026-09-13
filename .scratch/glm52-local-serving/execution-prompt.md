# GLM-5.2 Local Serving Workstream Execution Prompt

Use this prompt as the main execution guidance for the
`glm52-local-serving` workstream. It is written for an agent starting from a
fresh context in the Monarch checkout.

## Mission

Run GLM-5.2 locally as a Codex-compatible model provider and prove it with
repeatable Local Run evidence.

The target shape is:

```text
Codex or verifier
  -> OpenAI Responses-compatible adapter
  -> Dynamo frontend
  -> SGLang GLM-5.2
```

Monarch supports this workstream through Local Run discipline, the Hermetic
Rootfs, verifier Contract Artifacts, status and cleanup ledgers, and optional
monitoring/control-plane work. Monarch is not in the model-token hot path for
the first deployable version.

## Load First

Read these files before making changes:

```text
CONSTITUTION.md
AGENTS.md
CONTEXT.md
docs/adr/0001-bwrap-rootfs-for-local-runs.md
docs/adr/0002-python-isolation-reruns-for-local-run-classification.md
.scratch/glm52-local-serving/spec.md
.scratch/glm52-local-serving/control-plane-design.md
.scratch/glm52-local-serving/benchmark-spec.md
docs/agentic-ai/glm52-local-serving.md
```

Then inspect the ticket you are implementing:

```text
.scratch/glm52-local-serving/issues/01-serving-verifier.md
.scratch/glm52-local-serving/issues/02-bwrap-task-backend.md
.scratch/glm52-local-serving/issues/03-benchmark-verifier.md
.scratch/glm52-local-serving/issues/04-harbor-agent.md
.scratch/glm52-local-serving/issues/05-published-conformance-manifests.md
```

If an older ticket conflicts with the main spec, follow the main spec and note
the conflict in the ticket comments. The main spec is the current source of
intent.

## Operating Rules

- Run Linux-local Monarch Python, tests, docs, and trusted verifier code through
  `scripts/run` unless the task explicitly needs host resources.
- Run host-side cleanup and host process/container discovery outside
  `scripts/run`; cleanup must see host PIDs, ports, containers, and bwrap task
  roots.
- Preserve the Responses adapter as the Codex compatibility boundary. Codex
  does not call Chat Completions directly.
- Disable GLM thinking for the initial Codex tool-calling profile.
- Keep generated or model-authored code out of the repository checkout. Use the
  bwrap task backend or an official benchmark container.
- Use Docker or Harbor only when the benchmark contract requires a container or
  official provider.
- Do not introduce Kubernetes, KubeRay, Kueue, or cluster-native jobs for the
  local benchmark runner.
- Treat Contract Artifacts as the durable truth. Logs are supporting evidence,
  not acceptance criteria.
- Do not claim published conformance unless the manifest pins the primary
  source, prompt template, decoding profile, benchmark revision, execution
  backend, metric, and tolerance.

## Work Order

### Phase 0: Baseline Orientation

Goal: know exactly what is already implemented before taking a ticket.

Steps:

1. Inspect git status and preserve unrelated work.
2. Read the files in the Load First section.
3. Read the target ticket and all blocker tickets.
4. Inspect existing scripts and tests for GLM-5.2.
5. Run the current focused test suite if it exists:

   ```sh
   scripts/run python -m pytest \
     python/tests/test_glm52_serving_verifier.py \
     python/tests/test_glm52_responses_adapter.py \
     python/tests/test_glm52_deployment.py \
     -q
   ```

Completion criterion: you can state which ticket is being worked, what is
already present, what files you will touch, and what command will go red first.

### Phase 1: Serving and Adapter Readiness

Goal: make the Codex-facing provider contract work locally.

Required behavior:

- Raw Chat health can call the Dynamo/SGLang endpoint.
- Responses adapter exposes model discovery and response creation.
- Responses streaming emits stable text and function-call events.
- Function-call output continuation works through `previous_response_id`.
- GLM thinking is disabled by default for tool-calling requests.
- Adapter environment variables survive entry into the Hermetic Rootfs.

Expected verification:

```sh
python3 -m py_compile \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_deployment.py

bash -n \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_deployment.sh

scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  -q
```

Live endpoint verification when Dynamo/SGLang is available:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_responses_adapter.sh --host 127.0.0.1 --port 8080
```

In another shell:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --terminal-bench
```

Completion criterion: the focused tests pass, and a live run either passes or
is explicitly blocked by the absence of a GLM-5.2 endpoint.

### Phase 2: Crash-Recoverable Deployment State

Goal: cleanup works after launchers, adapters, or control-plane processes die.

Required behavior:

- Every launched component has an owner, discovery handle, and cleanup action.
- The state file is written before or at resource creation time.
- PID cleanup is guarded by command matching.
- Cleanup runs in reverse dependency order.
- Cleanup can be dry-run and repeated.

Expected verification:

```sh
scripts/run python -m pytest python/tests/test_glm52_deployment.py -q

scripts/run_glm52_deployment.sh status \
  --state .scratch/glm52-local-serving/run/deployment.json

scripts/run_glm52_deployment.sh cleanup \
  --state .scratch/glm52-local-serving/run/deployment.json \
  --dry-run
```

Completion criterion: stale and mismatched resources are handled safely, and a
crash-recovery operator can see what would be cleaned before doing it.

### Phase 3: bwrap Task Backend

Goal: provide a strict local execution backend for verifier-owned benchmark
tasks and generated code.

Required behavior:

- A host-side launcher creates one task root per benchmark task.
- Task root has read-only `input/` and writable `work/`, `output/`, and `tmp/`.
- The Monarch Hermetic Rootfs is mounted read-only.
- Generated code cannot write to the repository checkout.
- Network is disabled by default for generated-code execution.
- GPU visibility is disabled by default.
- The cleanup ledger records host PID and task root.

Suggested interface:

```text
run_bwrap_task(task_spec) -> task_result
```

Task spec should include:

```text
run_id
task_id
input_dir
work_dir
output_dir
timeout_seconds
network
gpu
command
environment_allowlist
```

Expected verification:

```sh
scripts/run python -m pytest python/tests/test_glm52_bwrap_task_runner.py -q

scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite bwrap-sandbox-smoke \
  --pool code_sandbox \
  --execution-backend bwrap_rootfs \
  --run-id bwrap-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

Completion criterion: the smoke proves in-task writes work, checkout writes
fail, and network access fails when disabled.

### Phase 4: Local Benchmark Verifier

Goal: run smoke, calibration, and conformance suites without Kubernetes.

Required behavior:

- Load benchmark manifests.
- Validate published-score manifests before conformance inference.
- Write run state and cleanup ledgers before launching suite work.
- Emit run-scoped Contract Artifacts.
- Support `bwrap_rootfs`, `scripts_run`, `local_docker`,
  `harbor_local_docker`, and `host_subprocess` backend declarations.
- Reject conformance backend overrides that change pinned score conditions.
- Separate model failures from infrastructure failures.

Minimum result layout:

```text
glm52-benchmark-results/<run-id>/
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

Expected verification:

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite needle-smoke \
    --execution-backend bwrap_rootfs \
    --run-id needle-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

Completion criterion: smoke mode writes complete artifacts, missing manifest
fields fail before inference in conformance mode, and infrastructure failures
are not counted as model failures.

### Phase 5: Harbor Agent and Terminal-Bench 2

Goal: run terminal-agent benchmarks through Harbor while preserving the Codex
Responses tool-calling profile.

Required behavior:

- Harbor agent calls the local Responses adapter, not SGLang Chat directly.
- Streaming and tool calls remain enabled.
- Trial artifacts include task ID, trial ID, model ID, endpoint, agent version,
  environment provider, and local host route.
- Harbor local Docker is used for Terminal-Bench 2 unless the pinned release
  defines an equivalent bwrap contract.
- Harbor artifacts are copied into the run-scoped result directory.

Expected verification:

```sh
scripts/run python -m pytest python/tests/test_glm52_harbor_agent.py -q

GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

Completion criterion: at least one pinned Terminal-Bench 2 smoke task can run
through Harbor against the local Responses adapter, or the run fails with a
classified environment setup failure.

### Phase 6: Published Conformance Manifests

Goal: make benchmark conformance claims reproducible and hard to overstate.

Required behavior:

- Manifest pins every benchmark suite by dataset revision, harness revision,
  prompt template, decoding profile, profile name, execution backend, and
  metric.
- Published-score manifest cites primary sources only.
- Thinking-enabled and thinking-disabled profiles are separate.
- Codex tool-calling readiness is separate from reasoning conformance.
- Every comparable score has an explicit tolerance.
- Non-comparable local profiles are marked non-comparable.

Expected verification:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  -q

GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_benchmark_verifier.sh conformance \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
    --run-id conformance-dry-run
```

Completion criterion: conformance refuses incomplete manifests before model
calls, and complete manifests record enough metadata to reproduce the claimed
condition.

## Acceptance Ladder

Use this order for end-to-end promotion:

1. Focused unit tests pass for adapter, serving verifier, and deployment helper.
2. Live raw Chat verifier passes against Dynamo/SGLang.
3. Live Responses verifier passes against the adapter.
4. Terminal bench smoke passes.
5. Deployment status and cleanup dry-run work from recorded state.
6. Bwrap sandbox smoke passes.
7. Benchmark smoke writes complete artifacts.
8. Harbor Terminal-Bench 2 smoke completes or fails with classified environment
   setup failure.
9. HumanEval, MBPP, GSM8K, AIME, and needle-smoke calibration runs complete.
10. Published conformance runs only after manifests are primary-source pinned.

Initial Codex readiness requires steps 1 through 5. Benchmark quality
confidence requires steps 6 through 9. Published conformance requires step 10.

## Commands Cheat Sheet

Start the adapter:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_responses_adapter.sh --host 127.0.0.1 --port 8080
```

Run serving verifier:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --terminal-bench
```

Run Responses-only terminal bench:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench
```

Check cleanup state:

```sh
scripts/run_glm52_deployment.sh status \
  --state .scratch/glm52-local-serving/run/deployment.json
```

Dry-run cleanup:

```sh
scripts/run_glm52_deployment.sh cleanup \
  --state .scratch/glm52-local-serving/run/deployment.json \
  --dry-run
```

Run all focused local tests:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_deployment.py \
  -q
```

## Ticket Closeout

Before marking any ticket resolved:

1. Run the focused tests named by the ticket.
2. Run `git diff --check`.
3. Inspect the diff for unrelated changes.
4. Update the ticket with an `## Answer` section describing what changed and
   the exact verification evidence.
5. Leave remaining work as a new numbered ticket instead of burying it in chat.

When a ticket changes behavior documented in this prompt, update this prompt in
the same workstream.
