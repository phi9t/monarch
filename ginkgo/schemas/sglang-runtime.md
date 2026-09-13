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
- `runtime.device` is explicit. `cuda` requires a non-empty
  `runtime.cuda_visible_devices` and `sandbox.gpu: required`; `cpu` requires an
  empty `runtime.cuda_visible_devices`, `sandbox.gpu: none`, and no
  `CUDA_VISIBLE_DEVICES` in the materialized launch or sandbox env.
- SGLang schema-owned flags are materialized exactly once.
- `sandbox.kind` is `bwrap_rootfs`.
- SGLang uses `/cache/glm52/venvs/sglang/bin/python`, not host Python.
- `HF_HOME` is `/cache/glm52/hf-home`.
- `SGLANG_CACHE_DIR` is `/cache/glm52/sglang`.
- CPU SGLang launches still run inside the governed bwrap rootfs and use
  `--device cpu`; they do not project host NVIDIA devices or libraries.

## Readiness

Readiness requires model identity and inference. `/v1/models` alone is not
enough; the runtime must also prove `/generate`, `/v1/completions`, and
`/v1/chat/completions`.

## Teardown

Teardown signals only owned process groups after process-record validation.
Ports must be closed before a repeatability cycle passes.
