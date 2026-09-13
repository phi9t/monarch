# Monarch Control Plane for GLM-5.2 Codex Serving

Status: final

## Goal

Run GLM-5.2 locally through Dynamo/SGLang and use it as a Codex custom provider
with enough verification and monitoring that promotion is a controlled
operational decision, not a one-off curl success.

## Decisions

- The first production path is **Codex -> Responses adapter -> Dynamo/SGLang**.
- The Responses adapter is the compatibility boundary for Codex. It must expose
  `/v1/responses` and `/v1/models`.
- Dynamo and SGLang own inference, KV-aware routing, prefix-cache locality, and
  model workers.
- Monarch owns local orchestration, verification, telemetry, supervision, and
  cleanup evidence around the serving path.
- Monarch is not required for the first successful model-token flow.
- A deployment is not operationally monitored until the Monarch control-plane
  gate passes.
- Cleanup must be possible from recorded state even if the launcher, adapter, or
  Monarch control plane crashes.

## Non-Goals

- Monarch does not replace Dynamo's KV-aware routing or SGLang inference.
- Monarch is not in the model-token hot path for the first deployable version.
- The first production path does not require Monarch to proxy every byte of the
  SSE stream.
- The initial Responses adapter does not expose arbitrary local shell or
  filesystem tools to the model.

## Deployment Shape

```text
Codex
  -> Responses adapter
      -> Dynamo frontend
          -> SGLang GLM-5.2 workers

Monarch control plane
  -> probes the adapter and Dynamo
  -> owns typed verifier tools
  -> records telemetry and contract artifacts
  -> supervises local tool/probe actors
```

The first deployable path is the top lane. The Monarch lane makes that path
observable and repeatably verifiable.

## Readiness Levels

### Level 1: Serving Ready

GLM-5.2 is running behind Dynamo/SGLang and passes the raw Chat verifier gate.
This proves model serving and tool-call generation work, but Codex is not yet
compatible.

### Level 2: Codex Ready

The Responses adapter passes the Responses verifier gate and a Codex smoke task
uses at least one tool successfully. This is sufficient for daily Codex use.

### Level 3: Operationally Monitored

The Monarch control plane is running, probe/scenario verdicts are queryable, and
cleanup/status commands work after simulated launcher failure. This is the
target for confident shared or long-running deployments.

## Deployment Inventory

Every deployment component must have an owner, a discovery handle, and an
idempotent cleanup action. The cleanup action must work even when the original
launcher or Monarch control-plane process is gone.

| Component | Owner | Discovery handle | Cleanup action |
|-----------|-------|------------------|----------------|
| Kubernetes namespace | Operator | namespace name, default `glm` | `kubectl delete namespace <namespace>` when namespace-scoped |
| Hugging Face secret | Operator | `hf-token-secret` in namespace | `kubectl delete secret hf-token-secret -n <namespace>` |
| Model-cache PVC | Dynamo recipe | recipe labels and PVC name | `kubectl delete -f recipes/glm-5.2/model-cache/model-cache.yaml -n <namespace>` |
| Model download job | Dynamo recipe | `job/model-download` | `kubectl delete -f recipes/glm-5.2/model-cache/model-download.yaml -n <namespace>` |
| Dynamo/SGLang deployment | Dynamo recipe | recipe labels and deployment/service names | `kubectl delete -f <deploy.yaml> -n <namespace>` |
| Port-forward process | Launcher | pidfile under `.scratch/glm52-local-serving/run/` | kill pid if live, then remove pidfile |
| Responses adapter process | Launcher or external service manager | pidfile or service name | service-manager stop or kill pid if live |
| Verifier artifacts | Verifier | `glm52-serving-results/` | preserve by default; delete only with explicit cleanup flag |
| Monarch control-plane actors | Monarch job | job apply ID and actor status | `job.kill()` or cleanup script stop command |
| Temporary run state | Launcher | `.scratch/glm52-local-serving/run/` | remove stale pidfiles and lockfiles after processes are gone |

Namespace-scoped cleanup is safest for throwaway local deployments. Shared
clusters should use labels instead of deleting the namespace:

```text
app.kubernetes.io/part-of=glm52-codex
app.kubernetes.io/managed-by=monarch-glm52-launcher
glm52.codex/deployment-id=<id>
```

## Deep Modules

### Responses Adapter

Interface:

- `GET /v1/models`
- `POST /v1/responses`

Responsibilities:

- Convert Responses `input` and `instructions` into Chat messages.
- Convert Responses function tools into SGLang/OpenAI Chat tools.
- Disable GLM thinking mode for structured tool use by injecting
  `chat_template_kwargs.enable_thinking=false`.
- Convert Chat tool calls into Responses function-call output items and SSE
  events.
- Convert Responses function-call outputs back into Chat `role=tool` messages.
- Preserve model IDs and request IDs in logs/telemetry.

Required behavior:

- Advertise `zai-org/GLM-5.2` from `/v1/models`.
- Stream Responses SSE events for Codex by default.
- Preserve function-call IDs across request, tool execution, and continuation.
- Reject malformed function-call arguments as structured adapter errors.
- Keep raw provider errors diagnosable without leaking secrets.

The interface stays small so Codex sees an ordinary Responses provider. Dynamo,
SGLang, and GLM-specific quirks stay inside the implementation.

### Tool Runtime

Interface:

```text
execute_tool(name, arguments, context) -> ToolResult
```

Responsibilities:

- Validate tool names and JSON arguments against a registry.
- Execute only explicitly registered tools.
- Return structured success/error payloads.
- Record input/output digests and latency.

Required behavior:

- Treat unknown tool names as hard failures.
- Treat invalid JSON arguments as hard failures.
- Include a scenario/session context in every tool event.
- Preserve tool outputs in verifier artifacts.

The first runtime should expose verifier-only synthetic tools. Real coding tools
can be added after the adapter passes the Codex compatibility gate.

### Serving Verifier

Interface:

```text
scripts/run_glm52_serving_verifier.sh [options]
```

Responsibilities:

- Check raw Dynamo/SGLang Chat health.
- Check Codex-facing Responses compatibility.
- Run a multi-turn tool-calling task.
- Emit JSON contract artifacts.
- Fail loudly on missing required Codex behavior.

Raw Chat `/models` is advisory. Responses `/models` is mandatory.

Implemented artifacts:

- `scripts/run_glm52_serving_verifier.sh`
- `scripts/glm52_serving_verifier.py`
- `glm52-serving-results/`

### Monarch Control Plane

Interface:

```text
start_glm52_control_plane(config) -> ControlPlaneState
run_glm52_verifier(state, scenario) -> VerifierVerdict
query_glm52_telemetry(state, sql) -> rows
```

Responsibilities:

- Start local probe and tool actors.
- Supervise failing probe/tool actors.
- Record endpoint, tool, stream, and verdict events into Monarch telemetry.
- Surface live state through the dashboard and Mesh Admin TUI.
- Keep contract artifacts on disk for deployment decisions.

This module should be a shallow caller of Monarch primitives but a deep module
for GLM serving operators.

Required behavior:

- A failed probe marks endpoint health red without killing the control plane.
- A failed scenario writes a failed verdict and preserves raw turn artifacts.
- Telemetry failure fails only the operational-monitoring gate.
- Cleanup/status must not depend on live actor state.

## Monarch Actor Sketch

```text
Glm52ControlPlaneActor
  - owns config and scenario registry
  - starts child actors
  - emits deployment verdict

EndpointProbeActor
  - probes /v1/models, /v1/chat/completions, /v1/responses
  - records latency, HTTP status, model IDs, stream events

ToolExecutorActor
  - owns typed verifier tools
  - validates JSON arguments
  - returns ToolResult

AgentScenarioActor
  - drives the multi-turn agent loop through the Responses adapter
  - delegates tool execution to ToolExecutorActor
  - records all model/tool turns

TelemetryReporterActor
  - normalizes events for Monarch telemetry
  - writes JSON contract artifacts
```

Supervision rules:

- Probe failures do not kill the control plane; they mark endpoint health red.
- Tool executor failure fails the current scenario and restarts the actor.
- Scenario failure writes a failed verdict and preserves all turn artifacts.
- Telemetry failure is reported but does not mask a serving failure.

## Verification Gates

### Gate 1: Raw Dynamo/SGLang

Command:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-responses
```

Required:

- `/v1/chat/completions` returns `GLM52_HEALTH_OK`.
- Chat tool loop emits function calls.
- Tool outputs are accepted.
- Final task answer is correct.

Advisory:

- Raw Chat `/v1/models` advertises `zai-org/GLM-5.2`.

### Gate 2: Responses Adapter

Command:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-chat
```

Required:

- `/v1/models` advertises `zai-org/GLM-5.2`.
- `/v1/responses` streams valid Responses SSE.
- Function-call argument deltas are reconstructable.
- Function-call outputs continue the same response chain.
- Final task answer is correct.

### Gate 3: Codex Smoke

Required:

- Codex starts with provider `glm52`.
- A simple repo task uses at least one tool.
- The adapter logs a completed Responses run.
- No parser errors, timeout retries, or malformed tool calls occur.

### Gate 4: Monarch Control Plane

Required:

- Control-plane actors start under `ProcessJob` or `LocalJob`.
- Probe and scenario verdicts are queryable through distributed telemetry.
- Dashboard or Mesh Admin shows probe/scenario actor status.
- Contract artifacts match the verifier's JSON schema.

## Telemetry Events

Record these logical events:

- `glm52.request.started`
- `glm52.request.completed`
- `glm52.stream.event`
- `glm52.tool_call.started`
- `glm52.tool_call.completed`
- `glm52.verifier.stage`
- `glm52.verifier.verdict`
- `glm52.endpoint.health`

Useful attributes:

- `provider`
- `model`
- `endpoint`
- `request_id`
- `response_id`
- `scenario`
- `tool_name`
- `status`
- `latency_ms`
- `http_status`
- `error_kind`

## Failure Policy

- Missing Responses `/v1/models`: fail Codex compatibility.
- Missing raw Chat `/v1/models`: warning only.
- Missing function-call deltas in streaming mode: fail Responses compatibility.
- Tool-call arguments that are not valid JSON: fail the scenario.
- Thinking-mode text in place of structured tool calls: fail the scenario.
- Final answer without required arithmetic/risk result: fail the scenario.
- Monarch telemetry unavailable: fail Gate 4, not Gates 1-3.
- Cleanup failure after a launcher crash is a deployment failure until every
  owned component is either removed or explicitly marked external.

## Cleanup Contract

The launcher must be crash-tolerant:

- Write a deployment manifest before creating resources.
- Assign one deployment ID to every local process, Kubernetes object label, and
  artifact path.
- Write pidfiles only after the child process has started.
- On normal exit, run cleanup traps in reverse creation order.
- On restart, inspect the prior manifest, verify each pid still belongs to the
  expected command, and offer or perform cleanup before creating new resources.
- Never delete an unlabelled Kubernetes object in a shared namespace.
- Preserve verifier artifacts by default so failed deployments remain
  diagnosable.

The deployment manifest should be a JSON file:

```json
{
  "deployment_id": "glm52-20260815-181200",
  "namespace": "glm",
  "mode": "namespace-scoped",
  "created_at": "2026-08-15T18:12:00Z",
  "components": [
    {
      "kind": "kubernetes-manifest",
      "name": "dynamo-sglang",
      "path": "recipes/glm-5.2/sglang/agg-b200-agentic/deploy.yaml",
      "namespace": "glm",
      "cleanup": "kubectl delete -f <path> -n <namespace>"
    },
    {
      "kind": "process",
      "name": "dynamo-port-forward",
      "pidfile": ".scratch/glm52-local-serving/run/dynamo-port-forward.pid",
      "expected_command": "kubectl port-forward"
    }
  ]
}
```

Crash cleanup command shape:

```text
scripts/run_glm52_deployment.sh status --state <manifest>
scripts/run_glm52_deployment.sh cleanup --state <manifest>
scripts/run_glm52_deployment.sh cleanup --namespace glm --selector app.kubernetes.io/part-of=glm52-codex
```

`scripts/run_glm52_deployment.sh` is a host-side helper. It must see host pids
for `kubectl port-forward` and local adapter processes, so it intentionally does
not enter the Monarch Hermetic Rootfs. The verifier remains rootfs-backed
because it runs repo-local Python against external HTTP endpoints.

The cleanup command must be idempotent. Missing objects, dead pids, and already
removed pidfiles are successful cleanup states.

## Launcher Responsibilities

The launcher should own orchestration, not protocol translation:

- Preflight `kubectl`, namespace access, GPU node availability, recipe files,
  and `HF_TOKEN`.
- Apply model cache and download resources.
- Apply the selected Dynamo/SGLang recipe.
- Wait for model download, deployment readiness, and service endpoints.
- Start and record local port-forwards.
- Start or locate the Responses adapter.
- Run verifier Gates 1 and 2.
- Print the Codex config only after Gate 2 passes.
- Expose `status` and `cleanup` subcommands that do not require the original
  launcher process to still be alive.

## Crash Scenarios

- **Launcher dies after namespace creation:** cleanup deletes the namespace or
  removes labelled objects.
- **Launcher dies during model download:** cleanup deletes the job; PVC deletion
  depends on whether model cache preservation was requested.
- **Launcher dies after port-forward start:** cleanup reads the pidfile, verifies
  the command is still `kubectl port-forward`, kills it, and removes the pidfile.
- **Responses adapter dies:** verifier Gate 2 fails; cleanup stops any adapter
  pid owned by the manifest.
- **Monarch control plane dies:** Kubernetes serving continues; cleanup can run
  from the manifest and does not require actor state.
- **Cleanup dies midway:** rerunning cleanup resumes from the manifest and treats
  already-removed resources as success.

## Implementation Plan

1. Harden the standalone verifier and docs. Done in this checkout.
2. Add host-side manifest `status` and `cleanup` helpers. Done in this
   checkout.
3. Implement or select the Responses adapter.
4. Run Gates 1 and 2 against live endpoints.
5. Configure Codex and run Gate 3.
6. Add a crash-safe deployment launcher with `deploy`, `status`, and `cleanup`
   subcommands. `status` and `cleanup` exist now; `deploy` remains future work.
7. Add Monarch `Glm52ControlPlaneActor`, `EndpointProbeActor`, and
   `ToolExecutorActor` around the same verifier scenario.
8. Add telemetry and dashboard visibility.
9. Promote only after all gates required for the target environment pass.

## Promotion Decision

Promote to daily Codex use when Gates 1, 2, and 3 pass against the target
deployment. Add Gate 4 before calling the deployment operationally monitored.

Do not promote when any of these remain true:

- The Responses adapter has not passed streaming tool-call verification.
- Codex has not completed a tool-using smoke task through the adapter.
- Cleanup cannot account for every launcher-owned process and Kubernetes object.
- Deployment status depends on live launcher process memory rather than the
  manifest and Kubernetes labels.

## Current Checkout State

Implemented:

- Rootfs-backed serving verifier.
- Host-side manifest `init-state`, `status`, and `cleanup` helper.
- Deployment guide.
- Control-plane design.
- Focused parser, verifier, and cleanup tests.

Not implemented:

- Responses-to-Chat adapter service.
- Full `deploy` subcommand that applies Dynamo/SGLang manifests and starts
  port-forwards.
- Monarch control-plane actors and telemetry emission.
- Live GLM-5.2/Dynamo/SGLang validation.

The next implementation milestone should be the Responses adapter, because that
is the blocking compatibility layer for Codex.
