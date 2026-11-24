# Decide Endpoint Roles and Readiness

Type: task
Status: resolved
Blocked by: 01

## Question

How should benchmark campaigns declare and validate model-under-test, judge,
reader, controller, and embedding endpoints?

## Context

MCP Atlas and LongMemEval-style systems can require multiple
OpenAI-compatible endpoints. Ginkgo already has a fortified local GLM-5.2
Responses path through:

```text
Responses adapter -> Dynamo -> SGLang
```

Benchmark runs need to distinguish the model under test from judge or helper
models so latency, failures, and quality are not conflated.

## Decision Needed

Define the endpoint registry section of the campaign manifest and the readiness
checks required before trials start.

Endpoint URLs must come from materialized serving config or component refs, not
invented fixed localhost ports. The registry may use `base_url_ref:
component://responses_adapter/openai_base_url` for the model-under-test and
resolve it to a concrete URL during campaign materialization. The campaign
materializer owns this `component://` resolution from the parent inference
materialized config; Insula's path resolver does not currently resolve
component refs. Readiness artifacts that live under `glm52-serving-results/`
must use a results-root reference, not `run://`, and must not insert a directory
segment that the serving producer does not write.

## Resolution

Campaign manifests declare an endpoint registry. Every trial references
endpoints by ID and role; suite adapters receive resolved endpoint records
rather than reading ambient environment variables or inventing ports.

Each endpoint record includes:

```yaml
id: glm52-responses-local
role: model_under_test
protocol: openai_responses
base_url_ref: component://responses_adapter/openai_base_url
model: zai-org/GLM-5.2
serving_engine: sglang+dynamo+responses-adapter
readiness_artifacts:
  sglang_repeat_summary: results://<repeat-id>/loop-summary.json
  serving_verifier_summary: results://<run-id>/summary.json
```

Allowed roles are:

```text
model_under_test
judge
reader
controller
embedding
tool_service
```

`component://` refs are resolved during campaign materialization from the
parent inference materialized config. Insula path resolution does not own this
ref class. `results://` refs resolve under the configured serving or benchmark
results root and must match files actually written by their producers.

Readiness requires:

- resolving every endpoint ref to one concrete URL;
- recording `/v1/models` or the protocol-equivalent model discovery result for
  OpenAI-compatible endpoints;
- issuing a minimal live generation probe for text-generation roles;
- issuing a minimal embedding probe for embedding roles;
- validating every declared readiness artifact before trials start;
- writing `endpoint-readiness.json` into the campaign artifact root.

GLM-5.2 benchmark traffic uses the Responses adapter. Lower-level SGLang or
Dynamo paths are allowed only for serving verifiers, not reportable agentic
benchmark trials.

Failures are classified by endpoint role. A judge, reader, controller,
embedding, or tool-service outage is not counted as a model-under-test failure,
but it remains in the campaign infrastructure or scorer denominator.

## Acceptance Criteria

- Every endpoint declares a role: model-under-test, judge, reader, controller,
  embedding, or tool-service.
- Every endpoint pins protocol, base URL source, model ID, serving engine when
  applicable, and readiness artifact.
- Local GLM-5.2 model traffic goes through the Responses adapter.
- Judge/helper endpoint failures are classified separately from
  model-under-test failures.
- The readiness gate records `/v1/models` and a minimal generation or embedding
  probe for each endpoint role that needs it.
