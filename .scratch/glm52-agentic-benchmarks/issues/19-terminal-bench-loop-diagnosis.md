# Terminal-Bench Loop Diagnosis

Type: task
Status: claimed
Blocked by:

## Objective

Diagnose and fix, or precisely classify, the remaining Terminal-Bench 2
one-task timeout against local GLM52 serving.

## Context

The current Harbor path reaches the pinned task, local Docker, the Responses
adapter, and GLM52 with streaming enabled. The latest run
`benchmark-e2e-terminal-bench-2-adapter1800-20260822T040029Z` completed the
suite as a model failure with no infrastructure failures:

```text
AgentTimeoutError: Agent execution timed out after 1800.0 seconds
```

Earlier blockers around missing Harbor, SSE parsing, inline GLM tool calls, and
short HTTP timeouts have been fixed. Do not disable streaming to make this pass.

## Requirements

- Reproduce the one-task smoke for `adaptive-rejection-sampler`.
- Preserve and inspect the Harbor trajectory, model messages, streamed
  Responses events, tool calls, tool outputs, and timeout point.
- Establish the smallest fast command or fixture that can turn red for the
  verified failure.
- Classify the root cause as protocol, continuation state, tool-result
  feedback, prompt/profile fit, model incapability, serving throughput, or
  another concrete cause.
- Add a regression test or fixture for the verified cause before changing
  behavior.
- Keep all GLM52 traffic through the Responses adapter and keep streaming
  enabled.
- Do not increase the 1800 second timeout as the primary mitigation.

## Files

- Modify if needed: `scripts/glm52_harbor_agent.py`
- Modify if needed: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_harbor_agent.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`
- Update: `.scratch/glm52-local-serving/issues/09-harbor-host-bootstrap.md`

## Exclusions

- Do not change Terminal-Bench scoring semantics.
- Do not run a multi-task or leaderboard-style Terminal-Bench run.
- Do not mount the host Docker socket into a model-controlled container.
- Do not treat a model timeout as an infrastructure failure once Harbor and the
  endpoint are healthy.

## Verification

Run focused tests after any code change:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
```

Then rerun the pinned one-task smoke using the explicit Harbor venv path or the
codified host preflight path:

```sh
PATH=.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH \
  python scripts/glm52_benchmark_verifier.py smoke \
    --suite terminal-bench-2 \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --execution-backend harbor_local_docker \
    --responses-base-url http://127.0.0.1:18081/v1 \
    --run-id benchmark-e2e-terminal-bench-2-loop-diagnosis-<timestamp>
```

Use the repo-local wrapper when the run belongs inside the rootfs execution
domain; use host Python only for documented host-control Harbor orchestration.

## Done When

- The one-task smoke either completes or records a concrete model/tool-loop
  blocker with trajectory evidence.
- The summary keeps infrastructure failures at zero when host, Docker, Harbor,
  and endpoint preflight pass.
- Any code fix has a regression test that fails before the fix and passes after
  the fix.

## Progress

### 2026-08-23 decoding propagation and cancellation diagnostics

Added regression coverage for the two verified gaps before changing behavior:

- Harbor agent cancellation now preserves
  `context.metadata["inflight_responses_request"]` with the stage, endpoint,
  timeout, stream flag, input item count, tool names, decoding profile, and
  elapsed time.
- Harbor smoke job config now passes the selected benchmark-manifest suite's
  `decoding_profile` into `GLM52HarborAgent` kwargs. The one-task
  Terminal-Bench config therefore carries `temperature: 0.2`, `top_p: 0.95`,
  `max_output_tokens: 4096`, and `glm_thinking: disabled` while keeping
  streaming enabled.

Verification:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_harbor_agent.py::test_agent_run_records_inflight_request_when_cancelled \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  -q
# 2 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 184 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m py_compile \
  scripts/glm52_harbor_agent.py \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_harbor_agent.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

Live Terminal-Bench rerun is currently blocked before Harbor execution because
no Responses adapter is listening on `http://127.0.0.1:18081/v1`. The verifier
recorded this clean preflight result in
`glm52-benchmark-results/benchmark-e2e-terminal-bench-2-loop-diagnosis-20260823T172406Z/summary.json`
with `status: environment_setup_failed`.

The GLM52 SGLang config still requires tensor parallel size 8 over GPUs `0..7`.
At the time of this update, GPU 0 was occupied by a user-owned
`torchtitan.train` process, so starting the 8-GPU serving stack was not safe.
