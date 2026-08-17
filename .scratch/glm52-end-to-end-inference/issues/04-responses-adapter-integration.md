# Responses Adapter Integration

Status: ready-for-agent

Type: task

Blocked by: 01, 02, 03

## Goal

Launch the local Responses adapter against the materialized Dynamo endpoint and
prove Responses API inference through non-streaming, streaming, and tool-call
paths.

## Requirements

- Consume the Responses adapter component slice from
  `materialized-inference.yaml`.
- Launch the adapter only after Dynamo is owned and its probes passed.
- Use the materialized Dynamo OpenAI base URL as the only upstream.
- Reject the adapter's ambient default port `8080`.
- Reject the adapter's ambient default chat base URL.
- Record adapter argv, env, stdout, stderr, endpoint URL, and process record.
- Probe adapter `GET /v1/models`.
- Probe non-streaming `POST /v1/responses`.
- Probe streaming `POST /v1/responses` SSE.
- Run the existing serving verifier's tool-call scenario against the adapter.
- Require the observed model name to match the SGLang served model name.
- Preserve raw adapter responses and upstream failures as Contract Artifacts.
- Tear the adapter down through the shared process-record contract.

## Exclusions

- Do not connect the adapter directly to SGLang in the default end-to-end
  topology.
- Do not treat fake Responses routing as live evidence.
- Do not run Harbor, SWE-bench, Terminal-Bench 2, or EvalPlus.

## Verification Evidence

- Unit tests for adapter command materialization from the parent schema.
- Unit tests that reject ambient `8080` and default chat URLs.
- Unit tests for non-stream, stream, and tool-call artifact recording using a
  controlled fake Dynamo upstream.
- Focused verifier tests showing the tool-call probe consumes the materialized
  Responses URL.

## Comments
