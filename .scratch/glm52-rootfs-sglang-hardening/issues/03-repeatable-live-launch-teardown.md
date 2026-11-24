# Issue 03: Repeatable Live Launch, Probe, and Teardown

Status: ready-for-agent

Type: task

Blocked by: 02

Spec: `.scratch/glm52-rootfs-sglang-hardening/spec.md`

Plan: `.scratch/glm52-rootfs-sglang-hardening/implementation-plan.md`

## Outcome

Launch local SGLang GLM-5.2 from the materialized rootfs-backed config on
custom run-owned ports, prove `/v1/models` and real chat inference, and tear
down cleanly across repeated cycles.

## Requirements

- Port allocation must stay inside the declared strict run-owned range.
- Ports `8000`, `8080`, and `18080` must never be used.
- Launch must use the rootfs-managed SGLang venv Python.
- Launch must use the prepared model cache and must not trigger implicit model
  download.
- Launch must validate emitted bwrap plan, outer argv, inner argv, env, mounts,
  repo projection mode, network policy, and GPU policy against materialized
  config.
- Each cycle must probe `/v1/models` and `/v1/chat/completions` on the allocated
  port.
- When `debug_mode=false`, failures must tear down the recorded process group.
- Teardown must verify the process group is gone and the port is closed.
- The final summary is successful only when every configured cycle passes.

## Exclusions

- Do not add Dynamo.
- Do not add Responses adapter launch.
- Do not run Harbor or benchmark scoring.
- Do not treat fixture or fake-runner success as live completion evidence.

## Verification

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
bash -n scripts/run_glm52_sglang_runtime.sh
```

Live acceptance command:

```sh
scripts/run_glm52_sglang_runtime.sh repeatability \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml
```

The live command must produce three passing launch/probe/teardown cycles from
the same declared spec.

## Comments
