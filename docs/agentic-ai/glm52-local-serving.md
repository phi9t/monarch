# GLM-5.2 Local Serving for Coding Agents

This guide describes how to deploy GLM-5.2 locally behind NVIDIA Dynamo and how
to verify that it can serve Codex-style coding-agent traffic. The deployment is
not a Monarch Local Run: it validates an external model-serving stack and a
Responses-compatible gateway.

## Target Topology

Current Codex custom providers use the OpenAI Responses API at
`POST /v1/responses`. NVIDIA's GLM-5.2 Dynamo recipe serves GLM-5.2 through
SGLang's OpenAI-compatible Chat Completions endpoint at
`POST /v1/chat/completions`. Put a compatibility gateway between them:

```text
Codex CLI / IDE
  -> OpenAI Responses API
  -> Responses-to-Chat adapter
  -> NVIDIA Dynamo frontend
  -> SGLang GLM-5.2 workers
```

The adapter is required for Codex compatibility. A server that only exposes
`/v1/chat/completions` is not enough.

## Dynamo Deployment

Start from NVIDIA's GLM-5.2 Dynamo recipe rather than hand-building the graph.
The useful local shapes are:

- `recipes/glm-5.2/sglang/agg-b200-agentic/deploy.yaml` for four B200 GPUs and
  `nvidia/GLM-5.2-NVFP4`.
- `recipes/glm-5.2/sglang/agg-h200-agentic/deploy.yaml` for eight H200 GPUs and
  `zai-org/GLM-5.2-FP8`.

The externally visible model name is:

```text
zai-org/GLM-5.2
```

Example deployment:

```sh
git clone https://github.com/ai-dynamo/dynamo.git
cd dynamo

export NAMESPACE=glm
kubectl create namespace "$NAMESPACE"
kubectl create secret generic hf-token-secret \
  --from-literal=HF_TOKEN="$HF_TOKEN" \
  -n "$NAMESPACE"

kubectl apply -f recipes/glm-5.2/model-cache/model-cache.yaml -n "$NAMESPACE"
kubectl apply -f recipes/glm-5.2/model-cache/model-download.yaml -n "$NAMESPACE"
kubectl wait --for=condition=Complete job/model-download -n "$NAMESPACE" --timeout=7200s

kubectl apply -f recipes/glm-5.2/sglang/agg-b200-agentic/deploy.yaml -n "$NAMESPACE"
```

Expose Dynamo locally while bringing the stack up:

```sh
kubectl port-forward svc/glm52-agg-b200-agentic-frontend 8000:8000 -n "$NAMESPACE"
```

Then check the raw Chat Completions path:

```sh
curl http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "zai-org/GLM-5.2",
    "messages": [{"role": "user", "content": "Reply with GLM52_HEALTH_OK"}],
    "max_tokens": 64,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

## Responses Adapter Contract

Run the checked-in adapter after the Dynamo frontend is reachable:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_responses_adapter.sh --host 127.0.0.1 --port 8080
```

The wrapper enters Monarch's Hermetic Rootfs through `scripts/run` before
running Python, while proxying to the external Dynamo/SGLang deployment. The
adapter defaults to `zai-org/GLM-5.2`, forwards to
`$GLM52_CHAT_BASE_URL/chat/completions`, and serves the Codex-facing Responses
API at `http://127.0.0.1:8080/v1`.

Useful knobs:

```sh
GLM52_MODEL=zai-org/GLM-5.2
GLM52_CHAT_BASE_URL=http://localhost:8000/v1
GLM52_RESPONSES_ADAPTER_HOST=127.0.0.1
GLM52_RESPONSES_ADAPTER_PORT=8080
GLM52_API_KEY_ENV=GLM_API_KEY
GLM52_ADAPTER_TIMEOUT_SECONDS=300
```

The adapter should expose at least:

```text
GET  /v1/models
POST /v1/responses
```

It should forward to Dynamo with these core translations:

```text
Responses API                    Chat Completions
---------------------------------------------------------------
input                         -> messages
instructions                  -> system message
tools[].type=function         -> tools[]
tool_choice                   -> tool_choice
max_output_tokens             -> max_tokens
function_call output items    -> tool role messages
response.output_text.delta    <- choices[].delta.content
function_call items           <- choices[].delta.tool_calls
response.completed            <- finish_reason
```

Tool-call support is mandatory. Coding agents need a loop that can receive a
function call, run the tool, send the tool output back, and continue until the
model returns a final answer.

The checked-in adapter stores `previous_response_id` conversation state in the
adapter process. For Codex deployment, run one adapter process or keep requests
sticky to the same process. Restarting the adapter drops in-flight continuation
state; treat that as a failed session and retry from the client.

Disable GLM thinking mode at first:

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

The NVIDIA recipe documents `reasoning_content` and notes that structured
decoding requires thinking to be disabled. Tool calling is structured decoding
for this verifier's purposes. Mapping `reasoning_content` into Responses
reasoning events can be added after the basic tool loop is stable.

## Serving Verifier

The committed verifier exercises both the raw Dynamo Chat endpoint and the
Responses adapter. It writes JSON Contract Artifacts under
`glm52-serving-results/`.

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh
```

The wrapper enters Monarch's Hermetic Rootfs through `scripts/run` before
running Python. `GLM52_MODEL`, `GLM52_CHAT_BASE_URL`,
`GLM52_RESPONSES_BASE_URL`, and `GLM_API_KEY` are preserved through that
gateway.

Use only the Chat side while the adapter is not ready:

```sh
GLM52_CHAT_BASE_URL=http://localhost:8000/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-responses
```

Use only the Responses side for Codex compatibility acceptance:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-chat
```

Add the terminal coding bench when you want a stronger tool-calling gate:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench
```

The terminal bench uses virtual terminal tools rather than host shell access.
The model must run tests, read `src/slug.py`, write a fix to `src/slug.py`, run
tests again, and report `TERMINAL_BENCH: PASS`. Only allowlisted test commands
are accepted, and only the synthetic `src/slug.py` file is writable.

If the adapter does not stream yet, run the Responses check in non-streaming
mode as an intermediate bring-up step:

```sh
GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_serving_verifier.sh --skip-chat --responses-non-stream
```

Set `GLM_API_KEY` when the endpoint requires authentication:

```sh
export GLM_API_KEY=...
```

### Verification Ladder

The verifier fails loudly at the first failed stage unless `--keep-going` is
passed.

- **Environment:** requires at least one base URL and records model, endpoint,
  auth-env, and results path.
- **Raw Chat model discovery:** calls `/v1/models` on the Chat base URL when it
  exists. This stage is a warning only because the Dynamo recipe's required
  serving surface is `/v1/chat/completions`.
- **Responses model discovery:** calls `/v1/models`; the Codex-facing Responses
  adapter must advertise `zai-org/GLM-5.2`.
- **Chat health:** calls `/v1/chat/completions` and requires an exact
  `GLM52_HEALTH_OK` answer.
- **Chat tool loop:** asks the raw Chat endpoint to solve a synthetic code-review
  task using `list_project_files` and `read_project_file`.
- **Responses tool loop:** asks the Responses adapter to solve the same task
  through streaming Responses events, function-call argument deltas, tool
  outputs, and final text.
- **Terminal coding bench:** when `--terminal-bench` is passed, asks the
  Responses adapter to run a synthetic terminal workflow with `terminal_run`,
  `terminal_read_file`, and `terminal_write_file` tools.

The complex task is intentionally small but not a string echo. The model must:

- list synthetic project files;
- read `README.md`, `src/alpha.py`, and `src/beta.py`;
- apply the scoring rule from `README.md`;
- compute `FINAL_SCORE: 19`;
- identify `RISKS: src/alpha.py`.

This catches deployments that can answer plain text but cannot perform the
agent loop that Codex depends on.

### External Backend Handoff

The Monarch scripts do not start Dynamo or SGLang. The operator must provide a
real GLM-5.2 OpenAI-compatible Chat Completions endpoint, then point the
adapter at it with a base URL such as
`GLM52_CHAT_BASE_URL=http://127.0.0.1:<chat-port>/v1`.

Avoid occupied default ports on this host. `:8000` has been observed serving
SimpleHTTP, `:8080` has been observed serving SearXNG, and `:18080` can also be
occupied. Choose free ports, then verify the upstream Chat endpoint before
starting the adapter:

```sh
export GLM52_CHAT_PORT=<free-chat-port>
export GLM52_RESPONSES_PORT=<free-adapter-port>
export GLM52_CHAT_BASE_URL=http://127.0.0.1:$GLM52_CHAT_PORT/v1
export GLM52_RESPONSES_BASE_URL=http://127.0.0.1:$GLM52_RESPONSES_PORT/v1

curl "$GLM52_CHAT_BASE_URL/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "zai-org/GLM-5.2",
    "messages": [{"role": "user", "content": "Reply with GLM52_HEALTH_OK"}],
    "max_tokens": 64,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

Start the adapter on the chosen free port:

```sh
GLM52_CHAT_BASE_URL="$GLM52_CHAT_BASE_URL" \
  scripts/run_glm52_responses_adapter.sh \
    --host 127.0.0.1 \
    --port "$GLM52_RESPONSES_PORT"
```

In another shell, verify adapter model discovery and then run the serving
verifier with the terminal bench:

```sh
curl "$GLM52_RESPONSES_BASE_URL/models"

GLM52_CHAT_BASE_URL="$GLM52_CHAT_BASE_URL" \
GLM52_RESPONSES_BASE_URL="$GLM52_RESPONSES_BASE_URL" \
  scripts/run_glm52_serving_verifier.sh --terminal-bench
```

For the Terminal-Bench 2 Harbor smoke, pass a host-resolvable Responses URL for
the adapter preflight. When Docker containers need to call the host adapter, use
`host.docker.internal` as the container route and declare it explicitly:

```sh
scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite terminal-bench-2 \
  --responses-base-url "$GLM52_RESPONSES_BASE_URL" \
  --local-host-route host.docker.internal \
  --local-container-runtime docker \
  --run-id tbench2-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

When `--responses-base-url` uses `localhost`, `127.0.0.1`, or `::1`, the
verifier keeps that URL for the host `/models` preflight and gives the Harbor
agent the matching `--local-host-route` URL so Docker resolves the host adapter.

Harbor local-Docker execution is a host-control requirement. Run that smoke
through `scripts/run_glm52_benchmark_verifier.sh`, not through `scripts/run`,
because Harbor must launch containers through the host Docker CLI and socket.
Monarch code, unit tests, docs checks, and trusted in-rootfs verifiers still run
through `scripts/run`.

If the Harbor smoke command runs inside the rootfs, the benchmark verifier must
stop before launching Harbor with `status=environment_setup_failed`,
`environment_diagnostics.execution_domain=scripts_run_rootfs`, and
`environment_diagnostics.required_execution_domain=host`. It writes those
diagnostics in `summary.json`, `environment.json`, and `harbor/trials.jsonl`.
Treat missing `harbor`, missing `docker`, absent Docker sockets, or the rootfs
execution-domain mismatch as a host-control/bootstrap blocker, not as a model
failure or a published benchmark result.

Expected serving-verifier artifacts include
`glm52-serving-results/<run-id>/summary.json` and
`glm52-serving-results/<run-id>/responses-agent.json`. If
`responses-agent.json` reports
`Responses stream error: downstream Chat Completions stream error HTTP 501`, the
configured upstream is not a Chat Completions server. If Harbor reports
`Responses /models preflight failed`, the adapter URL is unreachable, does not
return JSON, or returns an empty model list.

This handoff is a live-serving readiness path. It does not by itself establish
published benchmark conformance.

### Current Local Blocker Snapshot

Fresh local probes on 2026-08-16 confirm that the default ports in examples are
not currently a usable GLM-5.2 stack on this host. The Chat-only serving
verifier wrote `glm52-serving-results/20260816T181200Z-chat/` and exited 1:
`environment.json` passed, but `chat-models.json` warned and
`chat-health.json` failed because `http://127.0.0.1:8000/v1` refused
connections. The Responses-only serving verifier wrote
`glm52-serving-results/20260816T181200Z-responses/` and exited 1:
`environment.json` passed, but `responses-models.json` failed because
`http://127.0.0.1:8080/v1/models` returned HTTP 404 SearXNG HTML.

Treat those directories as blocker Contract Artifacts. They prove endpoint
misconfiguration on the current host, not GLM-5.2 readiness. Start Dynamo and
the adapter on known-free ports, then rerun the live verifier commands above
before attempting Harbor-backed or published-conformance evidence.

### Published Conformance Boundary

The checked-in published-score manifest at
`.scratch/glm52-local-serving/benchmarks/published-scores.yaml` intentionally
uses `TODO-primary-source`, `TODO` score, and `TODO` tolerance placeholders for
every suite. Do not replace those placeholders with secondary articles,
incompatible model-card rows, or fixture smoke outputs.

The current GLM-5.2 model card has primary-source numbers for conditions such
as `AIME 2026` and `Terminal Bench 2.1`, but those rows use different
benchmark revisions, prompts, decoding settings, judging, harnesses, or
execution backends than the local manifest. Keep them non-comparable unless the
published source also pins the same profile, prompt template, decoding profile,
benchmark revision, execution backend, metric, and tolerance. Until then,
conformance should fail before inference rather than report a pass/fail score.

## Recommended Deployment Order

Bring the stack up in layers and promote only after each layer is green:

1. **Dynamo/SGLang health:** deploy the NVIDIA recipe, port-forward the Dynamo
   frontend, and run `scripts/run_glm52_serving_verifier.sh --skip-responses`.
   A missing raw Chat `/models` endpoint is acceptable if Chat health and the
   Chat tool loop pass.
2. **Responses adapter:** put the adapter in front of Dynamo and run
   `scripts/run_glm52_serving_verifier.sh --skip-chat`. This is the Codex
   compatibility gate. `/v1/models`, streaming `/v1/responses`, function-call
   argument deltas, tool outputs, and the final complex task must pass.
3. **Codex client:** point `~/.codex/config.toml` at the adapter only after the
   Responses gate is green.
4. **Monarch control plane:** add Monarch actors around the adapter for
   endpoint probes, tool execution, telemetry emission, dashboard visibility,
   and supervision. Keep Dynamo/SGLang responsible for inference and KV-aware
   routing.

The first deployable production path is Codex -> Responses adapter ->
Dynamo/SGLang. Monarch improves confidence and operations around that path; it
should not be required for the first successful model-token flow.

## Cleanup and Crash Recovery

Account for every component before deploying. A crash-safe launcher should write
a deployment manifest under `.scratch/glm52-local-serving/run/` before creating
resources, then use that manifest for `status` and `cleanup` subcommands.

Minimum inventory:

```text
Kubernetes namespace
Hugging Face secret
model-cache PVC
model-download job
Dynamo/SGLang deployment and service
local kubectl port-forward process
Responses adapter process or service
Monarch control-plane job, if enabled
verifier artifacts
```

For throwaway local deployments, use a dedicated namespace such as `glm` and
delete the namespace during cleanup. For shared clusters, label every object and
delete only labelled resources:

```text
app.kubernetes.io/part-of=glm52-codex
app.kubernetes.io/managed-by=monarch-glm52-launcher
glm52.codex/deployment-id=<id>
```

Local processes, including `kubectl port-forward` and any local adapter process,
must have pidfiles under `.scratch/glm52-local-serving/run/`. Cleanup should
verify that a pid still belongs to the expected command before killing it.
Missing Kubernetes objects, dead pids, and already-removed pidfiles are cleanup
success states.

Preserve `glm52-serving-results/` by default. Failed deployment artifacts are
diagnostic evidence, not scratch state.

Use the host-side lifecycle helper for manifest status and cleanup:

```sh
scripts/run_glm52_deployment.sh status \
  --state .scratch/glm52-local-serving/run/deployment.json

scripts/run_glm52_deployment.sh cleanup \
  --state .scratch/glm52-local-serving/run/deployment.json

scripts/run_glm52_deployment.sh cleanup \
  --namespace glm \
  --selector app.kubernetes.io/part-of=glm52-codex
```

Do not run this cleanup helper through `scripts/run`. It must see host process
IDs for `kubectl port-forward` and local adapter services. The verifier wrapper
does enter the rootfs because it runs repo-local Python against external HTTP
endpoints; deployment cleanup is a separate host-control domain.

### Contract Artifacts

Successful and failed stages write JSON files in `glm52-serving-results/`:

```text
environment.json
chat-models.json
chat-health.json
chat-agent.json
responses-models.json
responses-agent.json
responses-terminal-bench.json
summary.json
```

`summary.json` is the top-level pass/fail artifact. The agent-stage artifacts
include the final answer, tool calls, tool outputs, and raw protocol events or
responses used to decide acceptance.

## Codex Provider Configuration

After the Responses adapter is green, Codex can point at the adapter:

```toml
model = "zai-org/GLM-5.2"
model_provider = "glm52"
model_context_window = 250000
model_supports_reasoning_summaries = false

[model_providers.glm52]
name = "GLM-5.2 / Dynamo"
base_url = "https://glm.example.com/v1"
wire_api = "responses"
env_key = "GLM_API_KEY"
stream_idle_timeout_ms = 300000
request_max_retries = 2
stream_max_retries = 2
```

For the four-B200 recipe, advertise a larger context only after the deployment
has been validated at that context length.
