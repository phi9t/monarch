# Harbor Agent Pilot

Type: task
Status: ready-for-agent
Blocked by: 09 11

## Objective

Add the first `harbor_agent` adapter path for Terminal-Bench and SWE-bench
Verified pilot evidence without mounting the host Docker socket into
model-controlled environments.

## Context

The current verifier has Harbor smoke paths and local Docker/Harbor integration
tests. The v1 campaign treats `terminal-bench-2` and `swe-bench-verified` as
pilot evidence, not full leaderboard runs.

## Requirements

- Create a `harbor_agent` adapter module.
- Preserve current Harbor smoke behavior from `scripts/glm52_benchmark_verifier.py`.
- Treat Harbor/local Docker orchestration as trusted `host_subprocess`, not a
  model-controlled task environment.
- Keep model traffic routed through the resolved Responses endpoint.
- Preserve raw trajectories or predictions before grading when the upstream
  harness exposes them.
- Emit normalized suite summaries and campaign-compatible failure categories.
- Require explicit user authorization for larger full-suite Harbor runs.

## Files

- Create: `ginkgo/eval/adapters/harbor_agent.py`
- Modify: `ginkgo/eval/orchestrator.py`
- Modify: `ginkgo/eval/artifacts.py`
- Modify: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_agentic_benchmark_platform.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_harbor_agent.py`

## Exclusions

- Do not mount `/var/run/docker.sock` into a model-controlled container.
- Do not claim Terminal-Bench or SWE-bench leaderboard parity from pilot runs.
- Do not add Daytona, Modal, Kubernetes, or cloud execution.

## Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_agentic_benchmark_platform.py -q
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
scripts/run python -m pytest python/tests/test_glm52_harbor_agent.py -q
```

## Done When

- Terminal-Bench and SWE-bench pilot paths can be represented as `harbor_agent`
  suites.
- Harbor failures classify as infrastructure, scorer, unsupported, or model
  failures according to the campaign taxonomy.
- Existing Harbor tests remain green.
