# Add GLM-5.2 Serving Verifier

Type: task
Status: ready-for-human
Blocked by:

## Current Status

The serving verifier, Responses adapter checks, deployment helper checks, and
failure-artifact paths are implemented and tested locally. The remaining work
needs a live Dynamo/SGLang GLM-5.2 Chat endpoint and a Responses adapter backed
by that endpoint. Current host probes show port 8000 is not an OpenAI-compatible
Chat endpoint and port 8080 is not the GLM-5.2 Responses adapter, so this ticket
is not currently ready for another local agent slice. Do not mark it resolved
until the raw Chat and live Responses verifier gates pass against GLM-5.2.

Fresh blocker artifacts from 2026-08-16 18:12 UTC confirm the same live
readiness gap. The Chat-only verifier command wrote
`glm52-serving-results/20260816T181200Z-chat/` and exited 1 with
`environment.json` passing, `chat-models.json` warning, and `chat-health.json`
failing because `http://127.0.0.1:8000/v1` refused connections. The
Responses-only verifier command wrote
`glm52-serving-results/20260816T181200Z-responses/` and exited 1 with
`environment.json` passing and `responses-models.json` failing because
`http://127.0.0.1:8080/v1/models` returned HTTP 404 SearXNG HTML. These result
directories are blocker evidence, not live GLM-5.2 readiness evidence.

## Requirements

- Add a scriptable verifier for GLM-5.2 served through Dynamo/SGLang and a
  Responses-compatible adapter.
- Validate plain Chat Completions health, Chat tool calling, Responses model
  discovery, Responses streaming tool calling, and final task correctness.
- Emit JSON artifacts under `glm52-serving-results/`.
- Keep the verifier independent from Monarch's Hermetic Rootfs because the
  target is an external Kubernetes serving stack.

## Exclusions

- Do not implement the adapter service.
- Do not require live cluster access for unit tests.

## Verification Evidence

- `python/tests/test_glm52_serving_verifier.py`
- `scripts/run_glm52_serving_verifier.sh --help`
- 2026-08-15 terminal bench conversation-error slice:
  - Red test observed:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_execute_terminal_tool_output_returns_conversation_error -q`
    failed during collection because `execute_terminal_tool_output` was missing.
  - Green test:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_execute_terminal_tool_output_returns_conversation_error -q`
    passed (`1 passed`).
  - Serving verifier tests:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q`
    passed (`13 passed`).
  - Focused GLM suite:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_deployment.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_harbor_agent.py -q`
    passed (`53 passed`).
  - Static checks:
    `scripts/run python -m py_compile scripts/glm52_serving_verifier.py scripts/glm52_responses_adapter.py scripts/glm52_deployment.py scripts/glm52_bwrap_task_runner.py scripts/glm52_benchmark_verifier.py scripts/glm52_harbor_agent.py && bash -n scripts/run_glm52_serving_verifier.sh scripts/run_glm52_responses_adapter.sh scripts/run_glm52_deployment.sh scripts/run_glm52_bwrap_task_runner.sh scripts/run_glm52_benchmark_verifier.sh && git diff --check`
    passed.
- 2026-08-15 serving archive-manifest slice:
  - Red test observed:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_write_serving_archive_manifest_records_relative_contract_artifacts -q`
    failed because `write_serving_archive_manifest` was missing.
  - Green test:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_write_serving_archive_manifest_records_relative_contract_artifacts -q`
    passed (`1 passed`).
  - Serving verifier tests:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q`
    passed (`14 passed`).
  - Focused GLM suite:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_deployment.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_harbor_agent.py -q`
    passed (`54 passed`).
  - Static checks:
    `scripts/run python -m py_compile scripts/glm52_serving_verifier.py scripts/glm52_responses_adapter.py scripts/glm52_deployment.py scripts/glm52_bwrap_task_runner.py scripts/glm52_benchmark_verifier.py scripts/glm52_harbor_agent.py && bash -n scripts/run_glm52_serving_verifier.sh scripts/run_glm52_responses_adapter.sh scripts/run_glm52_deployment.sh scripts/run_glm52_bwrap_task_runner.sh scripts/run_glm52_benchmark_verifier.sh && git diff --check`
    passed.
- 2026-08-15 adapter environment-passthrough slice:
  - Coverage test:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py::test_build_parser_reads_documented_adapter_environment -q`
    passed (`1 passed`), covering
    `GLM52_RESPONSES_ADAPTER_HOST`, `GLM52_RESPONSES_ADAPTER_PORT`,
    `GLM52_MODEL`, `GLM52_CHAT_BASE_URL`, `GLM52_API_KEY_ENV`, and
    `GLM52_ADAPTER_TIMEOUT_SECONDS`.
  - Rootfs passthrough proof:
    `GLM52_RESPONSES_ADAPTER_HOST=0.0.0.0 GLM52_RESPONSES_ADAPTER_PORT=18080 GLM52_MODEL=zai-org/GLM-5.2-test GLM52_CHAT_BASE_URL=http://chat.example/v1 GLM52_API_KEY_ENV=GLM_TEST_API_KEY GLM52_ADAPTER_TIMEOUT_SECONDS=12.5 scripts/run python - <<'PY' ... PY`
    exited 0 and printed the same parsed values from inside the Hermetic
    Rootfs.
  - Focused GLM suite:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py -q`
    passed (`59 passed`).
  - Static checks:
    `scripts/run python -m py_compile scripts/glm52_responses_adapter.py scripts/glm52_serving_verifier.py scripts/glm52_benchmark_verifier.py scripts/glm52_bwrap_task_runner.py scripts/glm52_deployment.py scripts/glm52_harbor_agent.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py && bash -n scripts/run_glm52_responses_adapter.sh scripts/run_glm52_serving_verifier.sh scripts/run_glm52_benchmark_verifier.sh scripts/run_glm52_bwrap_task_runner.sh scripts/run_glm52_deployment.sh && git diff --check`
    passed.
- 2026-08-15 serving verifier API-key environment slice:
  - Red test observed:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_build_parser_reads_documented_api_key_environment -q`
    failed because the serving verifier ignored `GLM52_API_KEY_ENV` and always
    defaulted `--api-key-env` to `GLM_API_KEY`.
  - Green test:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_build_parser_reads_documented_api_key_environment -q`
    passed (`1 passed`).
  - Rootfs wrapper proof:
    `GLM52_API_KEY_ENV=GLM_TEST_API_KEY scripts/run_glm52_serving_verifier.sh --skip-chat --responses-base-url http://127.0.0.1:9/v1 --keep-going --results-dir glm52-serving-results/api-key-env-20260815T010800Z`
    wrote `environment.json` with `api_key_env=GLM_TEST_API_KEY`; the command
    exited 1 because no Responses endpoint was listening, with endpoint failures
    classified under `responses-models` and `responses-agent`.
  - Serving verifier tests:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q`
    passed (`15 passed`).
  - Focused GLM suite:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py -q`
    passed (`64 passed`).
  - Static checks:
    `scripts/run python -m py_compile scripts/glm52_responses_adapter.py scripts/glm52_serving_verifier.py scripts/glm52_benchmark_verifier.py scripts/glm52_bwrap_task_runner.py scripts/glm52_deployment.py scripts/glm52_harbor_agent.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py && bash -n scripts/run_glm52_responses_adapter.sh scripts/run_glm52_serving_verifier.sh scripts/run_glm52_benchmark_verifier.sh scripts/run_glm52_bwrap_task_runner.sh scripts/run_glm52_deployment.sh && git diff --check`
    passed.
- 2026-08-16 adapter malformed tool-call arguments slice:
  - Red tests observed:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py::test_chat_nonstream_response_rejects_malformed_tool_arguments -q`
    and
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py::test_chat_streaming_rejects_malformed_tool_arguments -q`
    failed with `Failed: DID NOT RAISE <class
    'glm52_responses_adapter.AdapterError'>`.
  - Green malformed-argument tests:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py::test_chat_nonstream_response_rejects_malformed_tool_arguments python/tests/test_glm52_responses_adapter.py::test_chat_streaming_rejects_malformed_tool_arguments -q`
    passed (`2 passed`).
  - Adapter tests:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py -q`
    passed (`8 passed`).
  - Focused GLM suite:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py -q`
    passed (`67 passed`).
  - Static checks:
    `scripts/run python -m py_compile scripts/glm52_responses_adapter.py scripts/glm52_serving_verifier.py scripts/glm52_benchmark_verifier.py scripts/glm52_bwrap_task_runner.py scripts/glm52_deployment.py scripts/glm52_harbor_agent.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py && bash -n scripts/run_glm52_responses_adapter.sh scripts/run_glm52_serving_verifier.sh scripts/run_glm52_benchmark_verifier.sh scripts/run_glm52_bwrap_task_runner.sh scripts/run_glm52_deployment.sh && git diff --check`
    passed.
- 2026-08-16 serving archive Contract Artifact hash slice:
  - Red test observed:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_write_serving_archive_manifest_records_relative_contract_artifacts -q`
    failed because `archive-manifest.json` did not include
    `contract_artifact_sha256`.
  - Green test:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_write_serving_archive_manifest_records_relative_contract_artifacts -q`
    passed (`1 passed`).
  - Serving verifier tests:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q`
    passed (`15 passed`).
  - Focused GLM suite:
    `scripts/run python -m pytest python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py -q`
    passed (`82 passed`).
  - Static checks:
    `scripts/run python -m py_compile scripts/glm52_benchmark_verifier.py scripts/glm52_bwrap_task_runner.py scripts/glm52_deployment.py scripts/glm52_harbor_agent.py scripts/glm52_responses_adapter.py scripts/glm52_serving_verifier.py python/tests/test_glm52_benchmark_verifier.py python/tests/test_glm52_bwrap_task_runner.py python/tests/test_glm52_deployment.py python/tests/test_glm52_harbor_agent.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_serving_verifier.py && bash -n scripts/run_glm52_benchmark_verifier.sh scripts/run_glm52_bwrap_task_runner.sh scripts/run_glm52_deployment.sh scripts/run_glm52_responses_adapter.sh scripts/run_glm52_serving_verifier.sh && git diff --check`
    passed.
- 2026-08-16 Responses error parser and free-port adapter probe slice:
  - Parser-fix coverage:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q`
    passed (`17 passed`).
  - The serving verifier now rejects Responses streaming `error` events and
    non-stream top-level error payloads with `VerificationError` messages
    beginning `Responses stream error:` and `Responses API error:`.
  - Free-port adapter probe:
    `glm52-serving-results/responses-free-port-probe-20260816T103034Z/`
    recorded `environment: pass` and `responses-models: pass`, proving adapter
    `/v1/models` worked on a random free port, but `responses-agent` failed with
    the misleading terminal gate message `expected at least 4 tool calls, got 0`.
  - Follow-up parser-fix probe:
    `glm52-serving-results/responses-free-port-error-probe-20260816T103839Z/`
    again recorded `environment: pass` and `responses-models: pass`, while
    `responses-agent` failed clearly with `Responses stream error: downstream
    Chat Completions stream error HTTP 501: ... Unsupported method ('POST')`.
    `responses-agent.json` records the same error.
  - Current blocker: `localhost:8000` is a non-GLM/non-Chat service, not a
    hidden terminal tool-count issue. Live provider readiness remains blocked
    until a real Dynamo/SGLang GLM-5.2 Chat Completions endpoint is available.
- 2026-08-16 deployment lifecycle cleanup evidence:
  - Fresh host-side status command:
    `scripts/run_glm52_deployment.sh status --state .scratch/glm52-local-serving/run/deployment.json`
    returned JSON showing both managed process components absent:
    `responses-adapter` and `dynamo-sglang` each had `status=absent`,
    `pid=null`, and `detail="pidfile is absent"`.
  - Fresh host-side dry-run cleanup command:
    `scripts/run_glm52_deployment.sh cleanup --state .scratch/glm52-local-serving/run/deployment.json --dry-run`
    returned `status=clean`, `dry_run=true`, and both process components
    `cleanup=already-clean`.
  - Interpretation: no managed local GLM Responses adapter or Dynamo/SGLang
    backend process is currently running under this deployment state, and
    cleanup is safe and idempotent. This is lifecycle cleanup evidence only; it
    is not live provider readiness evidence.
- 2026-08-16 serving environment run-mode artifact slice:
  - Red test observed:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_environment_artifact_records_run_mode_knobs -q`
    failed because `environment.json` did not record
    `timeout_seconds`, `max_tokens`, `max_turns`, `keep_going`,
    `terminal_bench`, `responses_stream`, or `responses_non_stream`.
  - Green focused test:
    `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_environment_artifact_records_run_mode_knobs -q`
    passed (`1 passed`).
  - This is artifact-quality coverage for interpreting verifier results. It
    does not change the live endpoint blocker status: a real Dynamo/SGLang
    GLM-5.2 Chat Completions endpoint and Responses adapter are still required
    for live readiness.
- 2026-08-16 Responses stream parser duplicate-text slice:
  - Red test observed:
    `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_serving_verifier.py::test_parse_responses_stream_does_not_duplicate_completed_text -q`
    failed because streamed delta text plus the completed response output parsed
    as `FINAL_SCORE: 19FINAL_SCORE: 19`.
  - Green focused parser command:
    `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_serving_verifier.py::test_parse_responses_stream_does_not_duplicate_completed_text python/tests/test_glm52_serving_verifier.py::test_parse_responses_stream_reconstructs_function_call python/tests/test_glm52_serving_verifier.py::test_parse_responses_stream_rejects_error_event -q`
    passed (`3 passed`).
  - The parser now uses completed-response text as a fallback when no text
    deltas were seen, while still reconciling function-call items from the
    completed response. This is verifier parser correctness only and does not
    change the live endpoint blocker status.
- 2026-08-16 Phase 1 focused-suite baseline:
  - Fresh prompt-listed focused suite:
    `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_deployment.py -q`
    passed (`38 passed`).
  - This covers local parser, adapter translation, and deployment helper tests,
    but it is not live provider readiness evidence. The live Dynamo/SGLang
    GLM-5.2 Chat endpoint and Responses adapter run remain blocked.
- 2026-08-16 18:12 UTC fresh live serving blocker artifacts:
  - Chat-only verifier command:
    `timeout 180s env GLM52_CHAT_BASE_URL=http://127.0.0.1:8000/v1 scripts/run_glm52_serving_verifier.sh --skip-responses --results-dir glm52-serving-results/20260816T181200Z-chat`
    exited 1 before the timeout and wrote Contract Artifacts under
    `glm52-serving-results/20260816T181200Z-chat/`. `environment.json` passed,
    `chat-models.json` recorded `warning` with connection refused,
    `chat-health.json` failed with connection refused, and `summary.json`
    failed. `archive-manifest.json` lists 4 Contract Artifacts and 4 SHA-256
    entries. This confirms the default Chat URL is not currently serving
    Dynamo/SGLang GLM-5.2.
  - Responses-only verifier command:
    `timeout 240s env GLM52_RESPONSES_BASE_URL=http://127.0.0.1:8080/v1 scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench --results-dir glm52-serving-results/20260816T181200Z-responses`
    exited 1 before the timeout and wrote Contract Artifacts under
    `glm52-serving-results/20260816T181200Z-responses/`. `environment.json`
    passed, `responses-models.json` failed with HTTP 404 SearXNG HTML, and
    `summary.json` failed. `archive-manifest.json` lists 3 Contract Artifacts
    and 3 SHA-256 entries. This confirms the default Responses URL is still not
    the GLM-5.2 Responses adapter.
  - Interpretation: these are fresh live-readiness blocker artifacts only. Keep
    this issue at `Status: ready-for-human`; do not mark it resolved until the
    raw Chat and live Responses verifier gates pass against a real GLM-5.2
    endpoint.
