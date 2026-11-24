# Inference Runtime Schema

The inference runtime schema owns the parent SGLang -> Dynamo -> Responses
lifecycle. It consumes the materialized SGLang backend contract and derives all
component URLs, ports, process records, logs, and artifact paths.

## Components

- `sglang_backend`: launches from the declared SGLang config, must pass its
  model and inference probes, and is torn down before the integrated
  Dynamo/SGLang worker starts.
- `dynamo_frontend`: launches only after
  `component://sglang_backend/openai_base_url` has produced same-run completion
  evidence and must not accept a fallback upstream URL.
- `responses_adapter`: launches only against
  `component://dynamo_frontend/openai_base_url` and must not accept a fallback
  upstream URL.

## Required Contract

- `fail_fast` is `true`.
- `allow_fallback` is `false`.
- Port allocation uses `strict_run_owned_range`.
- Component upstreams are materialized from component refs, not operator URLs.
- Process records are validated before teardown.
- A parent run summary must prove the same run ID, ports, model identity, and
  process ownership across all components.

## Evidence Boundary

The parent inference runtime can produce GLM completion evidence only when the
GLM profile runs real SGLang gate inference, Dynamo readiness through its
integrated SGLang worker, Responses non-streaming and streaming inference,
tool-call verification, and clean teardown in the same parent run.
