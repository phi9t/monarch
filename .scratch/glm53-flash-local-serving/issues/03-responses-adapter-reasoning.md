# Add GLM-5.3-Flash Responses Adapter Reasoning Mapping

Type: task
Status: ready-for-agent
Blocked by: 01
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add GLM-5.3-Flash profile support to the Responses-to-Chat adapter.
- Preserve Chat `message.reasoning_content` separately from final
  `message.content`.
- Preserve complete prior reasoning blocks for `previous_response_id`
  continuation when `thinking.clear_thinking: false`.
- Support non-streaming and streaming Responses output for final text,
  reasoning metadata, function calls, function-call arguments, tool outputs, and
  terminal response events.
- Support `tool_stream: true` for streaming tool-loop probes and retain a raw
  chunk transcript digest.
- Preserve tool-call ids, function names, and JSON-string arguments; reject
  invalid JSON instead of repairing it silently.
- Record raw Chat payload digests and adapter mapping decisions in diagnostic
  artifacts without leaking Chat-only fields into public Responses output unless
  deliberately exposed as metadata.
- Use `private_metadata` as the default reasoning policy: raw reasoning stays in
  the run-local store and local Contract Artifacts, while public final answer
  text excludes reasoning content.

## Exclusions

- Do not prompt-rewrite away forced thinking.
- Do not merge reasoning text into final output text.
- Do not bypass the Responses API for Codex or benchmark evidence.

## Acceptance Criteria

- Focused tests cover non-streaming reasoning separation, streaming reasoning
  deltas, tool-call argument streaming, tool-output continuation, and
  `previous_response_id` replay.
- Streaming tests prove incremental tool-call arguments reconstruct
  byte-for-byte into the final JSON string.
- The adapter fails loudly on missing required reasoning, reordered preserved
  reasoning history, invalid tool JSON, or unmappable Chat deltas.
- The GLM-5.2 adapter behavior remains unchanged unless explicitly covered by a
  shared regression test.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_responses_adapter.py -q
scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py -q
```

Add GLM-5.3-Flash adapter tests before implementation. Keep the GLM-5.2 command
as regression coverage when the implementation shares adapter code.
