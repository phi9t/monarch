# Bootstrap Harbor Host-Control Harnesses

Type: task
Status: ready-for-human
Blocked by: host Harbor installation
Parent: 04-harbor-agent.md

## Problem

Terminal-Bench 2 and SWE-bench Verified smoke runs use the `harbor_local_docker`
execution backend, which is intentionally a host-control domain. Current host
preflight reaches the verifier and fails cleanly because `harbor` is not on
`PATH`:

```text
host bootstrap required for harbor_local_docker: harbor executable not found
```

Observed runs:

- `benchmark-live-tbench2-host-preflight-20260821T100207Z`
- `benchmark-live-swebench-host-preflight-20260821T100221Z`

## Requirements

- Install or expose a pinned Harbor CLI on the host path used for benchmark
  orchestration.
- Keep nested Docker access in the trusted host runner, not in model-controlled
  containers.
- Re-run Terminal-Bench 2 and SWE-bench Verified smoke commands against the
  local Responses adapter after Harbor is available.
- Preserve the verifier's environment setup failure artifacts when prerequisites
  are missing.

## Acceptance Criteria

- `command -v harbor` returns the intended pinned executable on the host.
- Terminal-Bench 2 smoke either runs a task or fails with a task-specific
  harness error after Harbor startup.
- SWE-bench Verified smoke either runs the selected instance or fails with a
  task-specific harness error after Harbor startup.

## Verification

```sh
python scripts/glm52_benchmark_verifier.py smoke --suite terminal-bench-2 --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --execution-backend harbor_local_docker --responses-base-url http://127.0.0.1:18081/v1 --run-id <run-id>
python scripts/glm52_benchmark_verifier.py smoke --suite swe-bench-verified --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --execution-backend harbor_local_docker --responses-base-url http://127.0.0.1:18081/v1 --run-id <run-id>
```

## Comments

### 2026-08-22 host-control rerun

Default host `PATH` still lacks `harbor`:

- `benchmark-e2e-terminal-bench-2-host-preflight-20260822T024922Z`
- `benchmark-e2e-swe-bench-verified-host-preflight-20260822T024922Z`

Both classify as `environment_setup_failed` with:

```text
host bootstrap required for harbor_local_docker: harbor executable not found
```

The repo scratch environment does contain a pinned user-local Harbor CLI:
`.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor`, version `0.21.0`.
Running with that directory prepended to `PATH` advances beyond the original
bootstrap failure, so this ticket's host installation criterion remains open
only for the default orchestration path.

Additional findings from the same rerun:

- `benchmark-e2e-terminal-bench-2-harbor-localhost-20260822T025038Z` reached
  Harbor and the local Responses adapter, then failed because the Harbor agent
  could not parse streaming SSE as JSON. This was fixed in
  `scripts/glm52_harbor_agent.py`.
- `benchmark-e2e-terminal-bench-2-streaming-20260822T025410Z` reached the model
  and verifier with streaming enabled, but the model emitted inline
  `<tool_call>...</tool_call>` text instead of structured Responses
  `function_call` items. This was fixed in `scripts/glm52_harbor_agent.py`.
- `benchmark-e2e-terminal-bench-2-inline-tools-20260822T025736Z` advanced past
  inline tool parsing and timed out under Harbor's then-default 900 second agent
  budget while waiting for the next Responses call. The verifier now propagates
  the smoke config's declared 1800 second task/instance timeout into Harbor's
  `agent.override_timeout_sec`.
- `benchmark-e2e-swe-bench-verified-streaming-20260822T031816Z` fails before
  trial execution because Harbor 0.21.0 cannot resolve registry dataset
  `swe-bench-verified`: `ValueError: Dataset swe-bench-verified not found`.

Current next actions:

- Put the pinned Harbor executable on the default host orchestration `PATH`, or
  make the benchmark wrapper consistently prepend the scratch Harbor venv.
- Rerun Terminal-Bench with the declared 1800 second Harbor agent timeout.
- Replace or adapt the SWE-bench Harbor dataset config so Harbor uses a real
  resolvable dataset/task source for the pinned smoke instance.

### 2026-08-22 streaming and timeout propagation rerun

The Harbor bridge now keeps Responses streaming enabled for GLM inference. The
agent parses SSE, handles inline GLM `<tool_call>...</tool_call>` text, and uses
the smoke config timeout for both Harbor's agent budget and the agent's
Responses HTTP read budget.

Run `benchmark-e2e-terminal-bench-2-adapter1800-20260822T040029Z` used:

- Harbor CLI from `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor`
  (`0.21.0`).
- Responses adapter `http://127.0.0.1:18082/v1`, launched with
  `--timeout-seconds 1800`.
- Harbor agent config with `stream: true`,
  `override_timeout_sec: 1800.0`, and
  `responses_timeout_seconds: 1800`.

Result:

- Summary status: `fail`.
- Suite state: `completed`.
- Infrastructure failures: `0`.
- Model failures: `1`.
- Terminal-Bench task: `adaptive-rejection-sampler`.
- Failure: `AgentTimeoutError: Agent execution timed out after 1800.0 seconds`.

This clears the earlier Harbor streaming/JSON parsing, inline tool-call parsing,
and too-short HTTP timeout blockers. The remaining Terminal-Bench smoke blocker
is not host bootstrap: the model/tool loop did not complete the task within the
declared 1800 second budget.

SWE-bench Verified remains blocked before trial execution. The latest observed
run is still `benchmark-e2e-swe-bench-verified-streaming-20260822T031816Z`, with
`environment_setup_failed` and:

```text
ValueError: Dataset swe-bench-verified not found
```

Current next actions:

- Keep streaming enabled in GLM inference and Harbor agent calls.
- Make the default host orchestration path expose the pinned Harbor CLI, or
  codify use of the scratch Harbor venv.
- Diagnose the Terminal-Bench model/tool-loop nontermination from the stored
  Harbor trajectory before increasing the timeout again.
- Replace or adapt the SWE-bench Harbor dataset config so Harbor uses a real
  resolvable dataset/task source for the pinned smoke instance.
