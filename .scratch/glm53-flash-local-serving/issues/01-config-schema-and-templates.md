# Add GLM-5.3-Flash Config Schema and Templates

Type: task
Status: ready-for-agent
Blocked by:
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add portable GLM-5.3-Flash declared config templates for SGLang and parent
  inference under `ginkgo/configs/`, plus a model profile under
  `ginkgo/profiles/`.
- Use `glm53-flash-sglang-local` and `glm53-flash-inference-local` run groups.
- Use model id, path, served name, and expected model ids of
  `zai-org/GLM-5.3-Flash`.
- Record source metadata for architecture, 1M max position embeddings, MoE
  expert shape, vision encoder, and FP8 quantization.
- Preserve the GLM-5.2 logical-reference model:
  `repo://`, `cache://`, `temp://`, `run://`, `rootfs://`, and
  `component://`.
- Use strict run-owned loopback ports, avoid `8000`, `8080`, and `18080`, and
  keep `allow_fallback: false`.
- Declare forced-thinking profile settings: `temperature: 1`, `top_p: 0.95`,
  `reasoning_effort: max`, `thinking.type: enabled`, and
  `thinking.clear_thinking: false`.
- Declare `reasoning_parser: glm45`, `tool_call_parser: glm47`, multimodal
  support, and Responses adapter protocol requirements.
- Declare separate quantization/runtime fields: FP8 checkpoint format,
  loading/conversion mode, compute dtype, KV-cache dtype, and observed backend
  verdict.
- Declare nullable profile sections for KDA state pool, MTP, and speculative
  decoding so their enabled state and observed metrics can be recorded.
- Add a backend capability record shape for SGLang, plus deferred-record shapes
  for vLLM, TokenSpeed, and KTransformers. Only SGLang needs a complete observed
  record in the first acceptance path.

## Exclusions

- Do not add live model launch behavior in this ticket.
- Do not generalize the GLM-5.2 config runtime unless the GLM-5.3-Flash
  templates cannot validate without it.
- Do not encode workstation-specific absolute paths in declared configs.

## Acceptance Criteria

- Template validation rejects fallback mode, disallowed ports, absolute host
  paths, shell-string commands, missing parser settings, missing thinking
  settings, disabled thinking in the default profile, missing FP8 verdicts, and
  benchmark profiles without Responses enabled.
- The parent inference config composes SGLang and Responses through
  `component://` references, and exposes a profile-scoped Dynamo component for
  the later lossiness proof.
- Focused tests cover the GLM-5.3-Flash template fields and rejection cases.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_inference_runtime.py -q
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
```

Add the GLM-5.3-Flash schema tests first. Keep the GLM-5.2 command as
regression coverage when shared config/runtime code is touched.
