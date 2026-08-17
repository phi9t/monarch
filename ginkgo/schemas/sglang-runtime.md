# SGLang Runtime Schema

The SGLang runtime schema owns the backend process declaration for GLM-5.2 and
lightweight smoke models. It is portable and must not contain concrete host
paths.

## Required Contract

- `fail_fast` is `true`.
- `allow_fallback` is `false`.
- `port_policy.mode` is `strict_run_owned_range`.
- `disallowed_ports` includes `8000`, `8080`, and `18080`.
- `model.served_model_name` appears in `model.expected_model_ids`.
- `runtime.kind` is `sglang_openai`.
- SGLang schema-owned flags are materialized exactly once.
- `sandbox.kind` is `bwrap_rootfs`.
- SGLang uses `/cache/glm52/venvs/sglang/bin/python`, not host Python.
- `HF_HOME` is `/cache/glm52/hf-home`.
- `SGLANG_CACHE_DIR` is `/cache/glm52/sglang`.

## Readiness

Readiness requires model identity and inference. `/v1/models` alone is not
enough; the runtime must also prove `/generate`, `/v1/completions`, and
`/v1/chat/completions`.

## Teardown

Teardown signals only owned process groups after process-record validation.
Ports must be closed before a repeatability cycle passes.
