# GLM-5.2 Local Serving Completion Audit

Checked: 2026-08-16

Status: not complete

## Load-First File Map

The execution prompt's load-first files and initial tickets are covered by this
audit as follows:

- `CONSTITUTION.md`: operating rules applied; no prompt-to-artifact evidence is
  taken as completion without real artifacts.
- `AGENTS.md`: Monarch rootfs, host-control, dirty-tree, and clean-context
  subagent rules applied.
- `CONTEXT.md`: repository domain context applied; Monarch remains support
  infrastructure, not the model-token hot path.
- `docs/adr/0001-bwrap-rootfs-for-local-runs.md`: local trusted Python and test
  commands use `scripts/run`; host-control Harbor/Docker execution is kept
  outside rootfs.
- `docs/adr/0002-python-isolation-reruns-for-local-run-classification.md`:
  failure-classification evidence is accepted only with matching isolated
  reruns or explicit classified artifacts.
- `.scratch/glm52-local-serving/spec.md`: current workstream state is
  `ready-for-human`; remaining work depends on live GLM serving, Harbor, or
  comparable conformance metadata.
- `.scratch/glm52-local-serving/control-plane-design.md`: deployment status and
  cleanup evidence is mapped under Phase 2 and the fresh deployment lifecycle
  section.
- `.scratch/glm52-local-serving/benchmark-spec.md`: benchmark run-state,
  cleanup-ledger, artifact-layout, Harbor, and conformance requirements are
  mapped under Phases 3 through 6.
- `docs/agentic-ai/glm52-local-serving.md`: external-backend handoff and known
  live-serving failure signatures are recorded as runbook evidence, not live
  readiness.
- Initial tickets `01` through `05`: current status and remaining blockers are
  mapped in the issue status map under `Remaining Required Work`.

Current live readiness blocker probes, 2026-08-16 15:47 UTC:

Raw Chat probe command:
`timeout 180s env GLM52_CHAT_BASE_URL=http://127.0.0.1:8000/v1 scripts/run_glm52_serving_verifier.sh --skip-responses --results-dir glm52-serving-results/20260816T154707Z-chat`

Result: verifier exit code 1; timeout did not fire. Contract artifacts were
written under `glm52-serving-results/20260816T154707Z-chat/`.
`environment.json` status is `pass` with
`chat_base_url=http://127.0.0.1:8000/v1`,
`responses_base_url=null`, `model=zai-org/GLM-5.2`, and
`api_key_present=false`. `summary.json` status is `fail`.
Stage statuses are: `environment=pass`, `chat-models=warning`, and
`chat-health=fail`. `chat-models.json` records `HTTP 404` with an HTML
`File not found` response. `chat-health.json` records `HTTP 501` with
`Unsupported method ('POST')`. This means the current default Chat candidate on
port 8000 is not an OpenAI-compatible GLM-5.2 Chat endpoint.

Responses probe command:
`timeout 240s env GLM52_RESPONSES_BASE_URL=http://127.0.0.1:8080/v1 scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench --results-dir glm52-serving-results/20260816T154707Z-responses`

Result: verifier exit code 1; timeout did not fire. Contract artifacts were
written under `glm52-serving-results/20260816T154707Z-responses/`.
`environment.json` status is `pass` with
`responses_base_url=http://127.0.0.1:8080/v1`,
`chat_base_url=null`, `model=zai-org/GLM-5.2`, and `api_key_present=false`.
`summary.json` status is `fail`. Stage statuses are:
`environment=pass` and `responses-models=fail`. `responses-models.json`
records `HTTP 404` with an HTML SearXNG page, including
`generator` content `searxng/2026.2.26+c3e3d2d85`. This means the current
default Responses candidate on port 8080 is a SearXNG service, not the
Responses adapter.

These probes produce fresh live-readiness blocker artifacts only. They do not
complete the GLM-5.2 local serving workstream because neither default candidate
URL is serving the expected Chat or Responses API.

Parent end-to-end runner update, 2026-08-17:

The GLM-5.2 parent inference runner now has a run-owned host-control Dynamo
venv path in the materialized schema. The declared parent config maps
`components.dynamo_frontend.topology.host_control_venv` to
`cache://glm52/venvs/dynamo`, and
`glm52-serving-results/prepare-dynamo-venv-20260817T165525Z/components/dynamo/dynamo-venv.json`
records a prepared venv at
`/var/tmp/monarch-glm52-local-serving-cache/glm52/venvs/dynamo` with
`ai-dynamo==1.4.0`, `ai-dynamo-runtime==1.4.0`, and successful import probes
for `dynamo.frontend` and `dynamo.sglang` through that venv's Python. The
parent materialized run
`glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z/` uses
strict run-owned ports `19000`, `19001`, and `19002`, and
`components/dynamo/environment.json` records `status=ok`,
`reason=python_module_importable`, `module=dynamo.frontend`, and
`popen_attempted=false`. This replaces the earlier active Dynamo blocker
`missing_module` / missing host-control package with a green prerequisite
artifact.

The same parent run is not completion evidence. It launched the owned SGLang
child run
`glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z-sglang/`,
and that child advertised `zai-org/GLM-5.2` from `/v1/models` on port `19000`,
but the real generation probe timed out after `300s`. The SGLang
`launch-summary.json` records `status=launch_failed`,
`error="generate probe timed out after 300s"`, a diagnostic `SIGQUIT` sent to
owned process group `2622371`, and a crash dump at
`crash-dumps/n116-077-207/crash_dump_2026-08-17_17-05-09.pkl`. The SGLang
stderr log records `Health check failed. Server couldn't get a response from
detokenizer for last 20 seconds`. Post-run cleanup was checked: `process.yaml`
records `status=stopped`, process group `2622371` is no longer present, and
`nvidia-smi --query-compute-apps` returned no active compute processes. This
is blocker evidence for parent-run SGLang generation health before Dynamo
frontend and worker launch, not live Dynamo, Responses, benchmark, EvalPlus, or
published conformance evidence.

Parent topology follow-up, 2026-08-17:

The failed parent SGLang child
`glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z-sglang/`
used an older active SGLang profile that lacked the `--moe-runner-backend
triton` argument present in the later successful SGLang-only repeat
`glm52-serving-results/glm52-sglang-local-repeat-20260817T155846Z-1cfe6ce1/`.
The active parent-referenced SGLang config now includes that proven runtime
argument. A fresh parent materialization,
`glm52-serving-results/glm52-inference-topology-materialize-20260817T171737Z/materialized.yaml`,
keeps strict ports `19000`, `19001`, and `19002`, derives a SGLang launch tail
ending in `--skip-server-warmup --moe-runner-backend triton`, and records the
Dynamo worker process record at
`repo://glm52-serving-results/<run-id>/components/dynamo/worker-process.json`.
The parent Dynamo launcher now starts the local topology as a `dynamo.sglang`
worker plus `dynamo.frontend`, not only the frontend. It also stops and marks
both owned Dynamo process records with `stop_reason=launch_failed` when the
Dynamo probe fails after startup. Verification through the `/data01` rootfs
reported `39 passed` for `python/tests/test_glm52_inference_runtime.py`. No
fresh live parent run was
attempted because a host GPU preflight showed GPU 4 occupied by non-owned pid
`2672717` (`/opt/tiger/b200/bin/python`, about `12898` MiB). This is
implementation and materialization evidence only; live Dynamo and Responses
proof still require a clean all-GPU window and a successful live parent run.

Current host-port freshness check, 2026-08-16 18:08 UTC:
A lightweight host-control GET probe checked `/v1/models` on the default local
Chat and Responses candidate ports. `http://127.0.0.1:8000/v1/models` and
`http://localhost:8000/v1/models` both refused connections (`Errno 111`), so
the earlier non-Chat service on port 8000 is no longer reachable and no
Dynamo/SGLang Chat endpoint is available there. `http://127.0.0.1:8080/v1/models`
and `http://localhost:8080/v1/models` still returned HTTP 404 with
`content-type=text/html; charset=utf-8`, `server=granian`, and SearXNG HTML in
the response body. This is a freshness probe only, not a serving-verifier
Contract Artifact; it confirms that live Chat and live Responses readiness
remain blocked.

Fresh serving-verifier blocker artifacts, 2026-08-16 18:12 UTC:

Chat-only command:
`timeout 180s env GLM52_CHAT_BASE_URL=http://127.0.0.1:8000/v1 scripts/run_glm52_serving_verifier.sh --skip-responses --results-dir glm52-serving-results/20260816T181200Z-chat`

Result: verifier exit code 1; timeout did not fire. Contract artifacts were
written under `glm52-serving-results/20260816T181200Z-chat/`.
`environment.json` status is `pass`; `chat-models.json` status is `warning`
with `request failed: <urlopen error [Errno 111] Connection refused>`;
`chat-health.json` status is `fail` with the same connection-refused error;
`summary.json` status is `fail`. `archive-manifest.json` lists 4 contract
artifacts and 4 SHA-256 entries. This confirms that the default Chat URL is not
currently serving Dynamo/SGLang GLM-5.2.

Responses-only command:
`timeout 240s env GLM52_RESPONSES_BASE_URL=http://127.0.0.1:8080/v1 scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench --results-dir glm52-serving-results/20260816T181200Z-responses`

Result: verifier exit code 1; timeout did not fire. Contract artifacts were
written under `glm52-serving-results/20260816T181200Z-responses/`.
`environment.json` status is `pass`; `responses-models.json` status is `fail`
with HTTP 404 SearXNG HTML; `summary.json` status is `fail`.
`archive-manifest.json` lists 3 contract artifacts and 3 SHA-256 entries. This
confirms that the default Responses URL is still not the GLM-5.2 Responses
adapter.

Serving verifier environment artifact slice, 2026-08-16:
The bounded artifact-quality slice adds run-mode interpretation knobs to
`environment.json`: `timeout_seconds`, `max_tokens`, `max_turns`,
`keep_going`, `terminal_bench`, `responses_stream`, and
`responses_non_stream`. The red focused test
`scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py::test_environment_artifact_records_run_mode_knobs -q`
failed because those fields were missing from the artifact. The green focused
test with the same command passed (`1 passed`) after the verifier recorded the
parsed run-mode values. This is metadata coverage only; it does not change the
live endpoint blocker status described above.

Responses stream parser artifact slice, 2026-08-16:
The bounded parser slice fixes a streamed Responses artifact issue where text
deltas and the final `response.completed.response.output` text were appended
together, doubling parsed final text. Red evidence:
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_serving_verifier.py::test_parse_responses_stream_does_not_duplicate_completed_text -q`
failed with parsed text `FINAL_SCORE: 19FINAL_SCORE: 19`. Green evidence: the
same regression plus adjacent stream function-call and stream-error parser tests
passed (`3 passed`). Completed-response text is now a fallback when no deltas
were seen, while completed function-call reconciliation remains intact. This is
verifier parser correctness only; it does not prove live GLM readiness.

Phase 1 focused-suite baseline, 2026-08-16:
The prompt-listed local Phase 1 suite
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_serving_verifier.py python/tests/test_glm52_responses_adapter.py python/tests/test_glm52_deployment.py -q`
reported `38 passed`. This refreshes local parser, adapter translation, and
deployment helper coverage after the serving verifier changes. It is still not
live provider readiness evidence because the current host probes show no
working GLM-5.2 Chat endpoint or Responses adapter at the default URLs.

06a HumanEval Responses adapter evidence:
The bounded 06a slice now routes exact single-suite `smoke --suite humaneval`
and `calibration --suite humaneval` runs through a Responses-backed adapter
path. Mixed HumanEval/MBPP suites and explicit `--pool code_sandbox` runs stay
on the existing bwrap code-generation path. The test evidence uses a fake local
`/v1/responses` server, not a live GLM endpoint, so this is adapter-path
evidence only and does not complete the execution prompt. The adapter posts the
HumanEval prompt to the configured Responses endpoint, passes the returned
completion into the bwrap fixture scorer, archives the codegen artifact, and
records `benchmark_scoring=fixture_harness`, `pass_at_1=null`, and fixture
scores of `1.0` or `0.0`. This is fixture-harness scoring only: it is not the
official HumanEval harness, not official HumanEval pass@1, and not published
conformance.

Samples record the provided Responses base URL as the endpoint, not `fixture`,
and preserve the case id, prompt, generated completion, profile, dataset and
harness revisions, prompt template hash, decoding profile, execution backend,
latency, and usage. Bad Responses endpoint behavior is classified as
infrastructure failure with `model_failures=0`; wrong generated code that fails
the fixture scorer is classified as `failure_category=model` with
`model_failures=1`, not as infrastructure. This does not add or imply any
published conformance claim.

Fresh main-thread verification for this slice:
the focused command with `-k
'humaneval_responses_run_scores_completion_with_bwrap_fixture_harness or
humaneval_responses_run_classifies_fixture_failure_as_model_failure or
mbpp_responses_run_classifies_fixture_failure_as_model_failure'` reported `3
passed`; the runner-level fixture-failure test
`test_codegen_smoke_reports_fixture_failure_as_scoreable_result` passed;
the full touched test files command reported `170 passed`; `scripts/run env
PYTHONDONTWRITEBYTECODE=1 python -m py_compile
scripts/glm52_benchmark_verifier.py
scripts/glm52_bwrap_task_runner.py
python/tests/test_glm52_benchmark_verifier.py
python/tests/test_glm52_bwrap_task_runner.py` exited zero; and `git diff
--check` exited zero. Remaining gaps include live GLM validation, official
HumanEval harness scoring, official HumanEval pass@1, and incomplete Harbor and
SWE-bench live execution.

EvalPlus handoff artifact update, 2026-08-16:
Exact single-suite HumanEval Responses runs now also write
`humaneval/official-harness.json` before archive manifest generation. The
artifact records `official_harness=evalplus`, `status=not_run`,
`metric=pass@1`, `pass_at_1=null`, the suite condition fields, the current
`fixture_harness` scoring mode, the archived generated-code artifact path, and
`conformance.claim=none`. `archive-manifest.json` lists
`humaneval/official-harness.json` as a Contract Artifact. This makes the
missing official EvalPlus execution explicit in run artifacts; it is not
official HumanEval pass@1 evidence.

Fresh main-thread verification for the handoff update:
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
'humaneval_responses_run_records_official_evalplus_handoff_artifact or
mbpp_responses_run_records_official_evalplus_handoff_artifact'` reported `2
passed`; the full benchmark verifier file reported `158 passed`; `scripts/run
env PYTHONDONTWRITEBYTECODE=1 python -m py_compile
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; `git diff --check
-- scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; and `rg -n "[ \t]+$"
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` found no trailing whitespace.

EvalPlus missing-prerequisite classification, 2026-08-16:
The HumanEval official-harness artifact now classifies the local official
EvalPlus attempt as `status=missing_prerequisite` when the rootfs Python
environment cannot import `evalplus`. The artifact keeps `metric=pass@1`,
`pass_at_1=null`, `benchmark_scoring=fixture_harness`,
`current_scoring=fixture_harness`, the archived generated-code artifact path,
and `conformance.claim=none`, and adds
`prerequisite={type: python_import, name: evalplus, status: missing}` with the
reason `evalplus package is not installed`. This makes the local official
harness blocker machine-readable; it still does not run EvalPlus or prove
official HumanEval pass@1.

Fresh main-thread verification for the classification update:
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
'missing_evalplus_official_harness_prerequisite'` reported `2 passed`; the
full benchmark verifier file reported `160 passed`; `scripts/run env
PYTHONDONTWRITEBYTECODE=1 python -m py_compile
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; `git diff --check
-- scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; and `rg -n "[ \t]+$"
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` found no trailing whitespace.

06b MBPP Responses adapter evidence:
The bounded 06b slice now routes exact single-suite `smoke --suite mbpp` and
`calibration --suite mbpp` runs through a Responses-backed adapter path. Mixed
HumanEval/MBPP suites and explicit `--pool code_sandbox` runs stay on the
existing bwrap code-generation path. The test evidence uses a fake local
`/v1/responses` server, not a live GLM endpoint, so this is adapter-path
evidence only and does not complete the execution prompt. The adapter posts the
MBPP prompt to the configured Responses endpoint, passes the returned
completion into the bwrap fixture scorer, archives the codegen artifact, and
records `benchmark_scoring=fixture_harness`, `pass_at_1=null`, and fixture
scores of `1.0` or `0.0`. This is fixture-harness scoring only: it is not the
official MBPP harness, not official MBPP pass@1, and not published conformance.

Samples record the provided Responses base URL as the endpoint, not `fixture`,
and preserve the case id, prompt, generated completion, profile, dataset and
harness revisions, prompt template hash, decoding profile, execution backend,
latency, and usage. Bad Responses endpoint behavior is classified as
infrastructure failure with `model_failures=0`; wrong generated code that fails
the fixture scorer is classified as `failure_category=model` with
`model_failures=1`, not as infrastructure. This does not add or imply any
published conformance claim.

Fresh main-thread verification for this slice:
the focused command with `-k
'humaneval_responses_run_scores_completion_with_bwrap_fixture_harness or
humaneval_responses_run_classifies_fixture_failure_as_model_failure or
mbpp_responses_run_classifies_fixture_failure_as_model_failure'` reported `3
passed`; the runner-level fixture-failure test
`test_codegen_smoke_reports_fixture_failure_as_scoreable_result` passed;
the full touched test files command reported `170 passed`; `scripts/run env
PYTHONDONTWRITEBYTECODE=1 python -m py_compile
scripts/glm52_benchmark_verifier.py
scripts/glm52_bwrap_task_runner.py
python/tests/test_glm52_benchmark_verifier.py
python/tests/test_glm52_bwrap_task_runner.py` exited zero; and `git diff
--check` exited zero. Remaining gaps include live GLM validation, official MBPP
harness scoring, official MBPP pass@1, and incomplete Harbor and SWE-bench live
execution.

EvalPlus handoff artifact update, 2026-08-16:
Exact single-suite MBPP Responses runs now also write
`mbpp/official-harness.json` before archive manifest generation. The artifact
records `official_harness=evalplus`, `status=not_run`, `metric=pass@1`,
`pass_at_1=null`, the suite condition fields, the current `fixture_harness`
scoring mode, the archived generated-code artifact path, and
`conformance.claim=none`. `archive-manifest.json` lists
`mbpp/official-harness.json` as a Contract Artifact. This makes the missing
official EvalPlus execution explicit in run artifacts; it is not official MBPP
pass@1 evidence.

Fresh main-thread verification for the handoff update:
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
'humaneval_responses_run_records_official_evalplus_handoff_artifact or
mbpp_responses_run_records_official_evalplus_handoff_artifact'` reported `2
passed`; the full benchmark verifier file reported `158 passed`; `scripts/run
env PYTHONDONTWRITEBYTECODE=1 python -m py_compile
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; `git diff --check
-- scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; and `rg -n "[ \t]+$"
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` found no trailing whitespace.

EvalPlus missing-prerequisite classification, 2026-08-16:
The MBPP official-harness artifact now classifies the local official EvalPlus
attempt as `status=missing_prerequisite` when the rootfs Python environment
cannot import `evalplus`. The artifact keeps `metric=pass@1`, `pass_at_1=null`,
`benchmark_scoring=fixture_harness`, `current_scoring=fixture_harness`, the
archived generated-code artifact path, and `conformance.claim=none`, and adds
`prerequisite={type: python_import, name: evalplus, status: missing}` with the
reason `evalplus package is not installed`. This makes the local official
harness blocker machine-readable; it still does not run EvalPlus or prove
official MBPP pass@1.

Fresh main-thread verification for the classification update:
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
'missing_evalplus_official_harness_prerequisite'` reported `2 passed`; the
full benchmark verifier file reported `160 passed`; `scripts/run env
PYTHONDONTWRITEBYTECODE=1 python -m py_compile
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; `git diff --check
-- scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; and `rg -n "[ \t]+$"
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` found no trailing whitespace.

EvalPlus execution-attempt branch, 2026-08-16:
HumanEval and MBPP official-harness artifacts now have an importable-`evalplus`
branch instead of falling through to `status=not_run`. When `evalplus` is
importable and a generated-code artifact was archived, the verifier writes an
EvalPlus samples JSONL file next to that artifact and invokes
`python -m evalplus.evaluate --dataset <humaneval|mbpp> --samples <file>
--base-only` with offline environment guards. The artifact records
`status=executed`, the subprocess command, return code, duration, stdout,
stderr, samples path, and generated-code artifact under
`official_attempt_evidence`. It still records `pass_at_1=null` and
`conformance.claim=none`; this is local execution-attempt evidence, not an
official pass@1 or published conformance claim.

Fresh main-thread verification for this branch:
the focused command
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
'evalplus_official_harness or
humaneval_responses_run_records_official_evalplus or
mbpp_responses_run_records_official_evalplus'` reported `6 passed, 157
deselected`; the full benchmark verifier file reported `163 passed`; and
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m py_compile
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero. The current rootfs
still cannot import `evalplus`, so real local official-harness scoring remains
blocked until an EvalPlus-capable offline environment is available.

06f needle-smoke Responses adapter evidence:
The bounded 06f slice now includes a calibration-only Responses adapter path:
`calibration --suite needle-smoke` accepts `--responses-base-url` and routes
exactly that single-suite calibration through the Responses-backed needle-smoke
writer in calibration mode. Mixed calibration suites and non-needle suites
remain on the existing fixture/static paths. The test evidence uses a fake
in-test `/v1/responses` server, not a live GLM endpoint, so this is adapter-path
evidence only and the audit remains incomplete. The calibration run writes
calibration-mode Contract Artifacts:
`needle-smoke/samples.jsonl`, `needle-smoke/metrics.json`,
`needle-smoke/failures.jsonl`, `environment.json`,
`benchmark-manifest.json`, `run.json`, `summary.json`, and
`archive-manifest.json`. Samples record the provided Responses base URL as the
endpoint, not `fixture`, and preserve profile, dataset and harness revisions,
prompt template hash, decoding profile, execution backend, latency, and usage.
This does not add or imply any published conformance claim. The bad-endpoint
regression classifies a broken Responses endpoint as `environment_failed` with
infrastructure failures greater than zero and `model_failures=0`.

Fresh main-thread verification for this slice:
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py::test_needle_smoke_calibration_real_adapter_uses_responses_endpoint python/tests/test_glm52_benchmark_verifier.py::test_needle_smoke_calibration_real_adapter_classifies_responses_failure -q`
reported `2 passed`; the same environment over
`python/tests/test_glm52_benchmark_verifier.py` reported `127 passed`;
`scripts/run python -m py_compile scripts/glm52_benchmark_verifier.py python/tests/test_glm52_benchmark_verifier.py`
exited zero; scoped `git diff --check` produced no output; and the scoped
trailing-whitespace `rg` check found no matches, with exit 1 expected for no
matches. Remaining 06f gaps include live GLM validation for needle-smoke. Live
endpoints, Harbor, and SWE-bench blockers remain incomplete.

06c GSM8K Responses adapter evidence:
The bounded 06c slice now routes exact single-suite `smoke --suite gsm8k` and
`calibration --suite gsm8k` runs through a Responses-backed adapter path using
a materialized local GSM8K JSONL cache sample. Mixed suites and non-GSM8K
suites remain on the existing fixture/static paths. The test evidence uses a
fake local `/v1/responses` server, not a live GLM endpoint, so this is
adapter-path evidence only and does not complete the execution prompt. The
adapter posts the GSM8K question to the configured Responses endpoint, extracts
and scores the final answer from model output with the GSM8K `####` parser, and
does not use the gold answer as model response evidence. Samples record the
provided Responses base URL as the endpoint, not `fixture`, and preserve the
dataset sample id, prompt, expected answer, extracted answer, normalization,
profile, dataset and harness revisions, prompt template hash, decoding profile,
execution backend, latency, and usage. Bad endpoint behavior is classified as
infrastructure failure; malformed or wrong model output is classified as model
failure. This does not add or imply any published conformance claim.

Fresh main-thread verification for this slice:
the focused GSM8K command with `-k
'gsm8k_single_suite_real_adapter_uses_responses_endpoint or
gsm8k_calibration_real_adapter_classifies_responses_failure or
gsm8k_calibration_real_adapter_classifies_bad_model_answer or
gsm8k_mixed_calibration_preserves_fixture_path'` reported `5 passed, 127
deselected`; the full `python/tests/test_glm52_benchmark_verifier.py` run
reported `132 passed`; `scripts/run python -m py_compile
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; scoped
`git diff --check` exited zero; and the scoped trailing-whitespace `rg` check
found no matches, with exit 1 expected for no matches. Generated `.pyc` files
from the compile check were removed. Remaining gaps include live GLM validation
for GSM8K, official GSM8K scoring over a live endpoint, and incomplete Harbor
and SWE-bench live execution.

06d AIME Responses adapter evidence:
The bounded 06d slice now routes exact single-suite `smoke --suite aime` and
`calibration --suite aime` runs through a Responses-backed adapter path using a
materialized local AIME JSONL cache sample. Mixed suites and non-AIME suites
remain on the existing fixture/static paths. The test evidence uses a fake
local `/v1/responses` server, not a live GLM endpoint, so this is adapter-path
evidence only and does not complete the execution prompt. The adapter posts the
AIME problem/prompt to the configured Responses endpoint, extracts and scores
the final integer answer from model output with
`extract_static_final_answer("aime", ...)`, and does not use the gold answer as
model response evidence. Missing AIME cache samples raise
`BenchmarkVerifierError` instead of falling back to fixture evidence for exact
single-suite AIME.

Samples record the provided Responses base URL as the endpoint, not `fixture`,
and preserve the dataset sample id, prompt, expected answer, extracted answer,
normalization, profile, dataset and harness revisions, prompt template hash,
decoding profile, execution backend, latency, and usage. Bad endpoint behavior
is classified as infrastructure failure; malformed or wrong model output is
classified as model failure. This does not add or imply any published
conformance claim.

Fresh main-thread verification for this slice:
the focused AIME command with `-k
'aime_single_suite_real_adapter or
aime_real_adapter_classifies_responses_failure or
aime_calibration_real_adapter_classifies_bad_model_answer or
aime_mixed_calibration_preserves_fixture_path'` reported `7 passed, 132
deselected`; the full `python/tests/test_glm52_benchmark_verifier.py` run
reported `139 passed`; `scripts/run python -m py_compile
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; scoped
`git diff --check` exited zero; and the scoped trailing-whitespace `rg` check
found no matches, with exit 1 expected for no matches. Generated `.pyc` files
from the compile check were removed. Remaining gaps include live GLM validation
for AIME, official AIME scoring over a live endpoint, and incomplete Harbor and
SWE-bench live execution.

06e RULER Responses adapter evidence:
The bounded 06e slice now routes exact single-suite `smoke --suite ruler` and
`calibration --suite ruler` runs through a Responses-backed adapter path using
a materialized local RULER JSONL cache sample. Mixed suites and non-RULER
suites remain on the existing fixture/static paths. The test evidence uses a
fake local `/v1/responses` server, not a live GLM endpoint, so this is
adapter-path evidence only and does not complete the execution prompt. The
adapter posts the RULER prompt, context, question, and input to the configured
Responses endpoint, then exact-matches stripped model output against the
expected answer. It does not use the expected answer as model response
evidence. Missing RULER cache samples raise `BenchmarkVerifierError` instead
of falling back to fixture evidence for exact single-suite RULER.

Samples record the provided Responses base URL as the endpoint, not `fixture`,
and preserve the dataset sample id, prompt, expected answer, extracted answer,
parsed answer, profile, dataset and harness revisions, prompt template hash,
decoding profile, execution backend, latency, and usage. A bad endpoint is
classified as infrastructure failure; wrong model output is classified as model
failure. This does not add or imply any published conformance claim.

Fresh main-thread verification for this slice:
the focused RULER command with `-k
'ruler_single_suite_real_adapter or ruler_mixed_smoke_stays_on_fixture_path'`
reported `6 passed, 139 deselected`; the full
`python/tests/test_glm52_benchmark_verifier.py` run reported `145 passed`;
`scripts/run python -m py_compile scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; scoped
`git diff --check` exited zero; and the scoped trailing-whitespace `rg` check
found no matches, with exit 1 expected for no matches. Generated `.pyc` files
from the compile check were removed. Remaining gaps include live GLM validation
for RULER, official RULER scoring over a live endpoint, and incomplete Harbor
and SWE-bench live execution.

SWE-bench image-source check:
`.scratch/glm52-local-serving/swebench-image-source-check.md` records the
primary-source image provenance check. The first smoke instance is now selected
from the materialized dataset cache: `astropy__astropy-12907`, whose row image
is `swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest`. Host Docker
registry metadata resolves that tag to immutable index digest
`sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88`.

SWE-bench resolver seam:
`scripts/glm52_benchmark_verifier.py` now has
`resolve_swe_bench_smoke_image_metadata(config, lock)`, a pure local helper
that accepts only selected smoke instances whose official row image and exact
`repo@sha256:<64 hex>` digest are declared. It does not fetch Hugging Face,
Docker, or Harbor; it is a metadata preflight seam, not a full SWE-bench
implementation.

SWE-bench prepare artifact wiring:
`prepare.json` now includes `swe_bench_smoke_image_preflight` when the selected
manifest contains `swe-bench-verified`. The section is derived from
`resolve_swe_bench_smoke_image_metadata(config, lock)` and the current Harbor
SWE-bench smoke config/lock files. The checked-in config/lock now produce a
`pass` metadata record for `astropy__astropy-12907`. Generic suite-level image
preflight skips `swe-bench-verified` because SWE-bench's image contract is
per-instance and handled by the dedicated section. This remains metadata
preflight only and does not prove a live SWE-bench execution.

SWE-bench dataset revision and smoke metadata:
The checked-in manifest and Harbor SWE-bench config/lock now use
the HuggingFace dataset revision
`78f471bf655a3137b2e8a75af1501690ec009ec3` for
`SWE-bench/SWE-bench_Verified`, while preserving the SWE-bench harness Git pin
`4e6126978a16bdfebc6538db8f28cacc2c8b77dc` separately. The smoke config/lock
pin `astropy__astropy-12907`, its dataset row image, and the immutable Docker
index digest for that image. This does not add published conformance claims.

Runbook update: `docs/agentic-ai/glm52-local-serving.md` now records the
external-backend handoff for live GLM-5.2 serving. It states that Monarch does
not start Dynamo/SGLang, calls out occupied local defaults observed on this
host, gives free-port adapter, serving-verifier, and Harbor Terminal-Bench 2
smoke commands, and records the expected artifacts and known failure
signatures. This is documentation of the handoff only, not live conformance
evidence.

Wizard update: `.scratch/glm52-local-serving/wizards/glm52-live-backend-handoff.sh`
now walks an operator through the same external-backend handoff, including
endpoint capture, optional scratch-only `GLM_API_KEY` capture, raw Chat health,
adapter launch, serving verifier, Harbor Terminal-Bench 2 smoke, and known
failure signatures. The wizard was statically checked only; it was not run
end-to-end and is not live readiness evidence.

Harbor URL artifact split:
Harbor smoke artifacts now preserve both endpoint views: the host-facing
`responses_base_url` used for `/models` preflight and the container-facing
`harbor_agent_responses_base_url` passed to `GLM52HarborAgent`. Normalized
Harbor trial records fall back to the job-config agent URL, or a derived
container-facing URL, before appending `/responses`. Raw `harbor-raw/trials.jsonl`
is still copied as Harbor source output and is not rewritten.

SWE-bench Harbor smoke config default:
`smoke --suite swe-bench-verified` now selects
`.scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml`
when `--harbor-smoke-config` is omitted, while Terminal-Bench 2 still defaults
to the Terminal-Bench smoke config and explicit `--harbor-smoke-config`
overrides remain honored. This prevents the SWE-bench Harbor path from
mis-reading the Terminal-Bench config before it reaches the classified
environment-failure artifact path.

Fresh main-thread verification for this guardrail:
`scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p
no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q -k
'swe_bench_verified_harbor_smoke_config'` reported `2 passed`; the nearby
Harbor/SWE/Terminal subset with `-k 'harbor_smoke_config or swe_bench_smoke or
terminal_bench_smoke'` reported `24 passed`; the full benchmark verifier file
reported `161 passed`; `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m
py_compile scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; `git diff --check
-- scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` exited zero; and `rg -n "[ \t]+$"
scripts/glm52_benchmark_verifier.py
python/tests/test_glm52_benchmark_verifier.py` found no trailing whitespace.
This is config-selection and classified-artifact guardrail evidence only; it
does not prove live Harbor or SWE-bench execution.

Run-scoped non-live artifact check for this guardrail:

```sh
timeout 240s env PATH="$PWD/.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH" \
  GLM52_RESPONSES_BASE_URL=http://127.0.0.1:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite swe-bench-verified \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --local-container-runtime docker \
    --run-id swebench-smoke-default-config-20260816T172813Z \
    --results-root glm52-benchmark-results \
    --run-root .scratch/glm52-local-serving/run
# exit 2
```

The run wrote
`glm52-benchmark-results/swebench-smoke-default-config-20260816T172813Z/`.
`summary.json` reports `status=environment_setup_failed`; the
`swe-bench-verified` suite reports `state=environment_setup_failed`,
`infrastructure_failures=1`, and `model_failures=0`. The reason is
`Responses /models preflight failed for http://127.0.0.1:8080/v1/models: HTTP
Error 404: Not Found`. The copied Harbor config is
`harbor/configs/swe-bench-verified-smoke.yaml`, with sha256
`7281754e87daf535476ab827e8e898f79f1bd742d838f05f4f74283796112ce5`; no
Terminal-Bench config was copied for this run. `archive-manifest.json` lists
and hashes `harbor/configs/swe-bench-verified-smoke.yaml`. This remains
classified environment setup failure evidence only, not live Harbor execution,
SWE-bench success, model-quality evidence, or published conformance.

This audit maps the execution prompt acceptance ladder to durable artifacts in
this checkout. It is not a completion claim. It records what has been verified
locally and what still needs live GLM-5.2, Harbor, or comparable
primary-source benchmark inputs.

Current live endpoint probe:
At `2026-08-16T15:41:41Z`, a host-side `/models` probe checked the common
candidate ports because host process and port discovery is outside
`scripts/run`. `http://127.0.0.1:8000/v1/models` and
`http://localhost:8000/v1/models` returned HTTP 404 `File not found`;
`http://127.0.0.1:8080/v1/models` and `http://localhost:8080/v1/models`
returned HTTP 404 `Not Found`; and `http://127.0.0.1:18081/v1/models` plus
`http://localhost:18081/v1/models` refused the connection. None of these
endpoints currently proves a Dynamo/SGLang GLM-5.2 Chat server or the
Responses adapter. Live raw Chat, live Responses, live benchmark scoring, and
Harbor smoke remain blocked until a valid Chat endpoint and adapter are
running on known ports. A host-control check in this checkout found
`/usr/bin/docker` available with Docker Engine 26.1.4 and the scratch Harbor
CLI at `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor` reporting
version `0.21.0`; this does not unblock Harbor because the required
Responses adapter URL is still not valid.

## Latest Local Verification

```sh
scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 101 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_calibration_uses_materialized_gsm8k_dataset_cache \
  python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_emits_math_answer_artifacts \
  -q
# 2 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 150 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 178 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_scores_cover_default_conformance_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_score_conditions_match_benchmark_manifest \
  -q
# 4 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 123 passed

scripts/run python scripts/glm52_benchmark_verifier.py conformance \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml \
  --run-id conformance-condition-guard-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/conformance-condition-guard-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/conformance-condition-guard-20260816T000000Z/run
# exit 2: published score for needle-smoke missing fields: score, source_type,
# source_url, tolerance, tolerance_basis; no result or run-root files written

scripts/run python -m py_compile \
  scripts/glm52_responses_adapter.py \
  scripts/glm52_serving_verifier.py \
  scripts/glm52_benchmark_verifier.py \
  scripts/glm52_bwrap_task_runner.py \
  scripts/glm52_deployment.py \
  scripts/glm52_harbor_agent.py \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py

bash -n \
  scripts/run_glm52_responses_adapter.sh \
  scripts/run_glm52_serving_verifier.sh \
  scripts/run_glm52_benchmark_verifier.sh \
  scripts/run_glm52_bwrap_task_runner.sh \
  scripts/run_glm52_deployment.sh

git diff --check
# exit 0

scripts/run python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/tmp/conformance-layout-20260816T044200Z/benchmark-manifest.yaml \
  --run-id prepare-layout-20260816T051500Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-layout-20260816T051500Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-layout-20260816T051500Z/run \
  --skip-endpoints
# status=prepared

find .scratch/glm52-local-serving/tmp/prepare-layout-20260816T051500Z/results/prepare-layout-20260816T051500Z \
  -maxdepth 1 -type f -printf '%f\n' | sort
# archive-manifest.json
# benchmark-manifest.json
# environment.json
# prepare.json
# run.json

scripts/run python - <<'PY'
import json
from pathlib import Path
result_dir = Path(".scratch/glm52-local-serving/tmp/prepare-layout-20260816T051500Z/results/prepare-layout-20260816T051500Z")
data = json.loads((result_dir / "archive-manifest.json").read_text())
print(data["contract_artifacts"])
PY
# ['benchmark-manifest.json', 'environment.json', 'prepare.json', 'run.json']

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_resumes_completed_matching_fixture_suite \
  -q
# 1 passed

scripts/run python scripts/glm52_benchmark_verifier.py smoke \
  --suite ruler \
  --manifest .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id resume-fixture-20260816T052500Z \
  --results-root .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/results \
  --run-root .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/run
# first run status=pass

scripts/run python scripts/glm52_benchmark_verifier.py smoke \
  --suite ruler \
  --manifest .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/benchmark-manifest.yaml \
  --execution-backend bwrap_rootfs \
  --run-id resume-fixture-20260816T052500Z \
  --results-root .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/results \
  --run-root .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/run
# second run status=pass; run state suite_status=resumed and preserved the
# existing samples.jsonl sentinel

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_runs_local_fixture_checks \
  python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_does_not_require_bwrap_for_trusted_fixtures \
  python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_classifies_missing_harbor \
  -q
# 3 passed

scripts/run python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/tmp/gold-path-prepare-20260816T053200Z/benchmark-manifest.yaml \
  --run-id gold-path-prepare-20260816T053200Z \
  --results-root .scratch/glm52-local-serving/tmp/gold-path-prepare-20260816T053200Z/results \
  --run-root .scratch/glm52-local-serving/tmp/gold-path-prepare-20260816T053200Z/run \
  --skip-endpoints
# status=prepared; gold_path_preflight includes passed local fixtures for
# AIME, GSM8K, and needle-smoke

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_backend_override_before_artifacts \
  -q
# 1 passed

scripts/run python scripts/glm52_benchmark_verifier.py conformance \
  --manifest .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/benchmark-manifest.yaml \
  --published-scores .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/published-scores.yaml \
  --suite humaneval \
  --execution-backend host_subprocess \
  --run-id conformance-override-20260816T054200Z \
  --results-root .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/results \
  --run-root .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/run
# exit 2: backend override is not allowed in conformance mode
# no result directory, benchmark run state, or cleanup state was written

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_supports_scripts_run_fixture_backend \
  -q
# 1 passed

scripts/run python scripts/glm52_benchmark_verifier.py smoke \
  --suite ruler \
  --manifest .scratch/glm52-local-serving/tmp/scripts-run-smoke-20260816T055000Z/benchmark-manifest.yaml \
  --execution-backend scripts_run \
  --run-id scripts-run-smoke-20260816T055000Z \
  --results-root .scratch/glm52-local-serving/tmp/scripts-run-smoke-20260816T055000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/scripts-run-smoke-20260816T055000Z/run
# status=pass; summary execution_backend=scripts_run; run state completed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_supports_local_docker_fixture_backend \
  -q
# red: environment.json did not record execution_backend for fixture smoke runs

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_supports_local_docker_fixture_backend \
  -q
# 1 passed

scripts/run python scripts/glm52_benchmark_verifier.py smoke \
  --suite ruler \
  --manifest .scratch/glm52-local-serving/tmp/local-docker-smoke-20260816T062000Z/benchmark-manifest.yaml \
  --execution-backend local_docker \
  --run-id local-docker-smoke-20260816T062000Z \
  --results-root .scratch/glm52-local-serving/tmp/local-docker-smoke-20260816T062000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/local-docker-smoke-20260816T062000Z/run
# status=pass; summary and environment execution_backend=local_docker;
# run state completed; archive lists summary.json, environment.json, and run.json

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  -q
# red: failed before prepare had SWE-bench smoke image config/lock wiring

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  -q
# red: failed until the builder resolved default config/lock paths at call time

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_swe_bench_smoke_image_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_current_swe_bench_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_write_prepare_artifact_records_placeholder_swe_bench_image_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_blocks_current_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_records_selected_digest_rows \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_requires_exact_digest_ref \
  -q
# 6 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 115 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --run-id prepare-swebench-current-20260816T000000Z \
  --results-root /tmp/glm52-prepare-swebench-results \
  --run-root /tmp/glm52-prepare-swebench-run \
  --skip-endpoints
# exit 2: current checked-in SWE-bench dataset_source revision is still a
# placeholder/non-materializable input for Hugging Face cache preparation

scripts/run python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-image-preflight-real-20260816T114600Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-image-preflight-real-20260816T114600Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-image-preflight-real-20260816T114600Z/run
# exit 2: Revision not found in dataset 'SWE-bench/SWE-bench_Verified';
# suite-level container_image validation no longer hides this source blocker

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct \
  -q
# red: failed because the checked-in SWE-bench dataset_revision still used the
# SWE-bench harness Git commit

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct \
  -q
# 1 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_harbor_placeholders_preserve_guardrails \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_manifest_keeps_dataset_and_harness_revisions_distinct \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_current_swe_bench_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_write_prepare_artifact_records_placeholder_swe_bench_image_preflight \
  python/tests/test_glm52_benchmark_verifier.py::test_resolve_swe_bench_smoke_image_metadata_blocks_current_placeholders \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  -q
# 6 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 HF_HOME=.scratch/glm52-local-serving/tmp/hf-home python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-hf-revision-20260816T000000Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-20260816T000000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-20260816T000000Z/run
# status=prepared

scripts/run env PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
import json
from pathlib import Path
p = Path(".scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-20260816T000000Z/results/prepare-swebench-hf-revision-20260816T000000Z/prepare.json")
data = json.loads(p.read_text())
print(data["cache_preflight"][0]["dataset_source_revision"])
print(data["cache_preflight"][0]["harness_source_revision"])
print(data["swe_bench_smoke_image_preflight"][0]["status"])
print(data["swe_bench_smoke_image_preflight"][0]["missing"])
PY
# 78f471bf655a3137b2e8a75af1501690ec009ec3
# 4e6126978a16bdfebc6538db8f28cacc2c8b77dc
# missing_prerequisite
# ['smoke_instances']

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 116 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 HF_HOME=.scratch/glm52-local-serving/tmp/hf-home python scripts/glm52_benchmark_verifier.py prepare \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --suite swe-bench-verified \
  --skip-endpoints \
  --run-id prepare-swebench-hf-revision-main-20260816T115900Z \
  --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-main-20260816T115900Z/results \
  --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-main-20260816T115900Z/run
# status=prepared; prepare.json records dataset_source_revision
# 78f471bf655a3137b2e8a75af1501690ec009ec3, harness_source_revision
# 4e6126978a16bdfebc6538db8f28cacc2c8b77dc, empty suite-level
# image_preflight, and SWE-bench smoke image preflight
# missing_prerequisite for smoke_instances

# Superseded current-state note: the checked-in Harbor SWE-bench smoke config
# and lock now pin astropy__astropy-12907 plus its exact Docker digest. Fresh
# prepare evidence below records swe_bench_smoke_image_preflight status=pass;
# this older transcript is retained only as historical red-green evidence.

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
# exit 0

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_harbor_smoke_config_has_pinned_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_swe_bench_harbor_smoke_config_is_loadable \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_classifies_bad_responses_models_endpoint_before_fixture_smoke \
  -q
# 5 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 119 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-container-runtime docker \
  --run-id swebench-smoke-env-preflight-main-20260816T122000Z \
  --results-root .scratch/glm52-local-serving/tmp/swebench-smoke-env-preflight-main-20260816T122000Z/results \
  --run-root .scratch/glm52-local-serving/tmp/swebench-smoke-env-preflight-main-20260816T122000Z/run
# exit 2: status=environment_setup_failed; reason="harbor executable not found"
# summary.json, run.json, environment.json, benchmark-manifest.json,
# harbor/trials.jsonl, harbor/configs/swe-bench-verified-smoke.yaml, and
# archive-manifest.json were written under the run result directory
```

Additional focused evidence for the latest benchmark verifier slice:

```sh
scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_checked_in_harbor_smoke_config_has_pinned_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_rejects_unresolved_legacy_harbor_dataset \
  python/tests/test_glm52_benchmark_verifier.py::test_load_harbor_smoke_config_requires_pinned_tasks \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  -q
# red before implementation: 4 failed for the old terminal-bench-2 binding,
# missing legacy rejection, and old JobConfig dataset/version fields
# green after implementation: 4 passed

.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor download \
  terminal-bench@2.0 \
  --repo harbor-framework/harbor@9dd349f28b969268aef419e910e1998149b612a5
# Successfully downloaded 89 task(s)

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_records_declared_image_digest \
  -q
# red: declared-image suites still returned digest_pending

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_records_declared_image_digest \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 46 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_cache_preflight_records_available_materialized_caches \
  -q
# red: cache preflight always reported planned, even for materialized caches

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_build_cache_preflight_records_available_materialized_caches \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 47 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_defaults_to_manifest_bwrap_fixture_suites \
  -q
# red: smoke required --suite and had no default manifest for the documented
# `smoke --run-id ...` command shape

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_defaults_to_manifest_bwrap_fixture_suites \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 48 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_calibration_command_defaults_to_checked_in_manifest \
  -q
# red: calibration required --manifest despite the documented command shape

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_calibration_command_defaults_to_checked_in_manifest \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 49 passed

scripts/run python -m pytest \
  python/tests/test_glm52_deployment.py::test_cleanup_ledger_reports_containers_and_ports_in_dry_run \
  -q
# red: cleanup-ledger status returned only bwrap_tasks, so recorded containers
# and ports were invisible to deployment status and cleanup dry-run

scripts/run python -m pytest \
  python/tests/test_glm52_deployment.py::test_cleanup_ledger_reports_containers_and_ports_in_dry_run \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_deployment.py -q
# 11 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 91 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# red before implementation:
# AttributeError: module 'glm52_benchmark_verifier' has no attribute
# 'materialize_prepare_caches'
# then command-level red:
# needle-smoke cache_preflight status remained planned instead of available

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 51 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 93 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  -q
# red: git dataset_source and harness_source entries were recorded in
# cache_preflight but not cloned or checked out, so caches stayed planned

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 3 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 52 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 94 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  -q
# red: http_archive sources were only recorded in cache_preflight; they were
# not downloaded or extracted, so caches stayed planned

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 53 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 95 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  -q
# red: unsupported dataset_source.type: 'huggingface_or_swebench'

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_copies_local_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_clones_pinned_git_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_extracts_http_archive_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  -q
# 5 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 54 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 96 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  -q
# red: prepare wrote status=prepared for @pinned-placeholder suite revisions

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_writes_run_state_and_cleanup_ledger \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  -q
# 4 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 55 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 97 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_source_revision_mismatch \
  -q
# red: prepare wrote status=prepared when a suite advertised one
# dataset_revision but dataset_source.revision named a different fetched
# revision

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_source_revision_mismatch \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_writes_run_state_and_cleanup_ledger \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_placeholder_suite_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_source_revision_mismatch \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_materializes_local_cache_sources \
  python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_records_container_runtime_preflight \
  -q
# 5 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 56 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 98 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_placeholder_suite_revisions \
  -q
# red: conformance wrote status=validated when selected suite and published
# score revisions matched on @pinned-placeholder values

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_placeholder_suite_revisions \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 2 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 57 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 99 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_container_image_for_docker_suites \
  -q
# red: conformance wrote status=validated for a harbor_local_docker suite with
# no container_image

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_comparable_score \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_container_image_for_docker_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 3 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 58 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 100 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_source_metadata \
  -q
# red: conformance wrote status=validated for a suite with pinned revisions but
# no dataset_source or harness_source metadata

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_missing_published_score_fields \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_profile_mismatch \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_decoding_profile_mismatch \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_comparable_score \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_defaults_to_all_manifest_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_container_image_for_docker_suites \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_source_metadata \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact \
  -q
# 8 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 59 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 101 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_mutable_container_image_tags \
  -q
# red: conformance wrote status=validated for a harbor_local_docker suite whose
# container_image was only a mutable tag

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_mutable_container_image_tags \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 60 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 102 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  -q
# red before implementation:
# ERROR: not found: ... test_published_score_manifest_validation

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation \
  -q
# 1 passed

scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q
# 61 passed

scripts/run python -m pytest \
  python/tests/test_glm52_responses_adapter.py \
  python/tests/test_glm52_serving_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py \
  python/tests/test_glm52_bwrap_task_runner.py \
  python/tests/test_glm52_deployment.py \
  python/tests/test_glm52_harbor_agent.py \
  -q
# 103 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_preflights_unresolved_registry_dataset_before_harbor_launch \
  -q
# 1 passed

scripts/run python -m pytest \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_missing_harbor \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_writes_failure_run_state \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_records_environment_artifact \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_preflights_unresolved_registry_dataset_before_harbor_launch \
  -q
# 6 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
# exit 0

PATH=.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH \
  GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --pool harbor_terminal \
    --local-container-runtime docker \
    --run-id tbench2-registry-preflight-20260816T000001Z
# exit 2: status=environment_setup_failed before Harbor launch because
# terminal-bench-2@d28711d0da2675d0bb1d56de45ae5df6082438a3 is unresolved in
# the Harbor registry
```

## Prompt-to-Artifact Phase Checklist

This checklist maps the execution prompt's work-order phases to concrete
evidence in this audit. It is not a completion claim.

Phase 0, Baseline Orientation: verified for the current checkout.

- Prompt gate: inspect git status and preserve unrelated work. Evidence: dirty
  checkout state is recorded in this audit and preserved; unrelated tracked
  files are not reverted.
- Prompt gate: read the load-first files and target tickets. Evidence: this
  audit references the prompt, spec, design, benchmark spec, docs guide, and
  issues 01 through 06; the issue status map under `Remaining Required Work`
  records current ownership.
- Prompt command: focused Phase 0 test suite for serving verifier, Responses
  adapter, and deployment helper. Evidence: the Phase 1 focused-suite baseline
  records the prompt-listed suite as `38 passed`.
- Completion gate: state the active ticket, present files, and first red
  command. Evidence: each issue file records red/green slices and current
  blocker state.

Phase 1, Serving and Adapter Readiness: partial.

- Prompt command: `python3 -m py_compile` for serving verifier, Responses
  adapter, and deployment helper. Evidence: latest local verification records
  the corresponding compile checks passing for the GLM scripts and tests.
- Prompt command: `bash -n` for the serving, adapter, and deployment wrappers.
  Evidence: latest local verification records wrapper syntax checks passing.
- Prompt command: focused pytest for serving verifier, Responses adapter, and
  deployment helper. Evidence: Phase 1 focused-suite baseline records
  `38 passed`; later focused GLM suites record larger passing counts.
- Prompt live command: launch the Responses adapter against
  `GLM52_CHAT_BASE_URL=http://localhost:8000/v1`. Status: blocked by the
  absence of a live Dynamo/SGLang GLM-5.2 Chat endpoint.
- Prompt live command: run `scripts/run_glm52_serving_verifier.sh
  --terminal-bench` against Chat and Responses URLs. Status: blocked; recorded
  probes show port 8000 returns non-Chat errors and port 8080 is not the
  GLM-5.2 Responses adapter.
- Completion gate: focused tests pass and live run passes or is explicitly
  blocked. Status: local tests pass; live readiness is explicitly blocked.

Phase 2, Crash-Recoverable Deployment State: verified locally for recorded
state.

- Prompt command: `scripts/run python -m pytest
  python/tests/test_glm52_deployment.py -q`. Evidence: deployment tests are
  recorded as passing, including the latest local `11 passed` run.
- Prompt command: `scripts/run_glm52_deployment.sh status --state
  .scratch/glm52-local-serving/run/deployment.json`. Evidence: `Fresh
  Deployment Lifecycle Evidence` records absent pidfiles for the fixture
  deployment state.
- Prompt command: `scripts/run_glm52_deployment.sh cleanup --state
  .scratch/glm52-local-serving/run/deployment.json --dry-run`. Evidence: the
  same section records `status=clean`, `dry_run=true`, and already-clean
  component cleanup.
- Completion gate: stale and mismatched resources are handled safely. Status:
  verified for recorded state, bwrap task cleanup, containers, and port dry-run
  visibility; this does not prove live serving readiness.

Phase 3, bwrap Task Backend: verified locally for the task-sandbox contract.

- Prompt command: `scripts/run python -m pytest
  python/tests/test_glm52_bwrap_task_runner.py -q`. Evidence: the bwrap runner
  file is recorded as passing with `12 passed`, and the broader GLM suites pass
  with the bwrap tests included.
- Prompt command: `scripts/run_glm52_benchmark_verifier.sh smoke --suite
  bwrap-sandbox-smoke --pool code_sandbox --execution-backend bwrap_rootfs`.
  Evidence: `bwrap-smoke-20260816T033508Z` records smoke artifacts proving
  task-root layout, checkout-write denial, network denial, and cleanup ledger
  behavior.
- Completion gate: in-task writes work, checkout writes fail, and network
  access fails when disabled. Status: verified for the local bwrap contract;
  this does not replace official Docker-backed benchmark environments.

Phase 4, Local Benchmark Verifier: partial.

- Prompt command: `scripts/run python -m pytest
  python/tests/test_glm52_benchmark_verifier.py -q`. Evidence: multiple full
  benchmark verifier runs are recorded, with the latest counts increasing as
  guardrails were added.
- Prompt command: `scripts/run_glm52_benchmark_verifier.sh smoke --suite
  needle-smoke --execution-backend bwrap_rootfs`. Evidence:
  `needle-smoke-20260816T033636Z` records run-scoped smoke artifacts, summary,
  environment, run state, and archive manifest.
- Prompt gate: missing manifest fields fail before inference in conformance
  mode. Evidence: conformance dry-runs reject incomplete published-score
  manifests before model calls and write no result or run-root files for early
  input errors.
- Prompt gate: infrastructure failures are not counted as model failures.
  Evidence: Harbor and endpoint failures are classified as
  `environment_setup_failed` or infrastructure failures with `model_failures=0`.
- Completion gate: complete smoke artifacts exist, but live GLM-backed
  benchmark runs, official Docker/Harbor-backed suites, and published
  conformance remain blocked.

Phase 5, Harbor Agent and Terminal-Bench 2: partial.

- Prompt command: `scripts/run python -m pytest
  python/tests/test_glm52_harbor_agent.py -q`. Evidence: Harbor agent tests are
  recorded as passing, including `8 passed`, and broader GLM suites include the
  Harbor agent tests.
- Prompt command: Terminal-Bench 2 Harbor smoke through
  `scripts/run_glm52_benchmark_verifier.sh smoke --suite terminal-bench-2
  --pool harbor_terminal --local-container-runtime docker`. Evidence:
  `tbench2-smoke-20260816T155253Z` and earlier runs write classified
  environment-failure artifacts, copied Harbor config, trial metadata, and
  archive manifests.
- Completion gate: at least one pinned Terminal-Bench 2 smoke task runs through
  Harbor, or the run fails with classified setup failure. Status: classified
  setup-failure evidence exists; a real Harbor Terminal-Bench 2 task has not
  completed against a GLM-backed Responses URL.

Phase 6, Published Conformance Manifests: verified guardrail, blocked
conformance.

- Prompt command: `scripts/run python -m pytest
  python/tests/test_glm52_benchmark_verifier.py::test_published_score_manifest_validation
  -q`. Evidence: the test was added after an initial collection failure and is
  recorded as passing.
- Prompt command: conformance dry-run with checked-in benchmark and
  published-score manifests. Evidence: dry-runs reject missing or placeholder
  published-score fields before model calls; `conformance-dry-run-20260816T034900Z`
  records the incomplete-manifest blocker without producing benchmark results.
- Completion gate: complete manifests must record enough metadata to reproduce
  the claimed condition. Status: blocked; current primary-source scores are
  non-comparable or placeholder-only, so no published conformance claim is
  supported.

## Commands Cheat Sheet Evidence Map

This map covers the operator commands listed in the execution prompt's
`Commands Cheat Sheet`.

- Start the adapter with `scripts/run_glm52_responses_adapter.sh --host
  127.0.0.1 --port 8080`: blocked for the default URL because the observed
  `localhost:8000` service is not a GLM-5.2 Chat endpoint. Free-port adapter
  evidence proves `/v1/models` can work, but the adapter still fails when its
  upstream Chat URL points at the non-GLM service.
- Run the full serving verifier with `scripts/run_glm52_serving_verifier.sh
  --terminal-bench`: blocked. `serving-live-probe-20260816T034600Z` and
  `serving-live-probe-20260816T150000Z` record Chat 404/501 failures and no
  live pass.
- Run Responses-only terminal bench with `scripts/run_glm52_serving_verifier.sh
  --skip-chat --terminal-bench`: blocked. `responses-live-probe-*` artifacts
  show port 8080 serves SearXNG HTML, not the GLM-5.2 Responses adapter; the
  free-port adapter probe then fails on the bad upstream Chat service.
- Check cleanup state with `scripts/run_glm52_deployment.sh status --state
  .scratch/glm52-local-serving/run/deployment.json`: verified locally. Fresh
  deployment lifecycle evidence records absent pidfiles for the fixture
  deployment state.
- Dry-run cleanup with `scripts/run_glm52_deployment.sh cleanup --state
  .scratch/glm52-local-serving/run/deployment.json --dry-run`: verified
  locally. Fresh deployment lifecycle evidence records `status=clean`,
  `dry_run=true`, and reverse-order already-clean components.
- Run all focused local tests for serving verifier, Responses adapter, and
  deployment helper: verified locally. Phase 1 baseline records `38 passed`,
  with later broader GLM suites also passing.

## Current Artifact Existence Check

Checked on 2026-08-16 after the prompt-to-artifact maps were added. This is a
filesystem consistency check for key artifacts already cited by the audit.

- `glm52-serving-results/20260816T154707Z-chat/summary.json` exists with
  `status=fail`; its archive manifest lists 4 contract artifacts and 4 matching
  SHA-256 entries.
- `glm52-serving-results/20260816T154707Z-responses/summary.json` exists with
  `status=fail`; its archive manifest lists 3 contract artifacts and 3 matching
  SHA-256 entries.
- `glm52-serving-results/20260816T181200Z-chat/summary.json` exists with
  `status=fail`; its archive manifest lists 4 contract artifacts and 4 matching
  SHA-256 entries.
- `glm52-serving-results/20260816T181200Z-responses/summary.json` exists with
  `status=fail`; its archive manifest lists 3 contract artifacts and 3 matching
  SHA-256 entries.
- `glm52-benchmark-results/bwrap-smoke-20260816T033508Z/summary.json` exists
  with `status=pass`, `mode=smoke`; its archive manifest lists 3 contract
  artifacts and 3 matching SHA-256 entries.
- `glm52-benchmark-results/needle-smoke-20260816T033636Z/summary.json` exists
  with `status=pass`, `mode=smoke`; its archive manifest lists 7 contract
  artifacts and 7 matching SHA-256 entries.
- `glm52-benchmark-results/calibration-core-20260816T034300Z/summary.json`
  exists with `status=pass`, `mode=calibration`; its archive manifest lists 19
  contract artifacts and 19 matching SHA-256 entries.
- `glm52-benchmark-results/tbench2-smoke-20260816T155253Z/summary.json` exists
  with `status=environment_setup_failed`, `mode=smoke`; its archive manifest
  lists 6 contract artifacts and 6 matching SHA-256 entries.
- `glm52-benchmark-results/swebench-smoke-default-config-20260816T172813Z/summary.json`
  exists with `status=environment_setup_failed`, `mode=smoke`; its archive
  manifest lists 6 contract artifacts and 6 matching SHA-256 entries.
- `.scratch/glm52-local-serving/run/deployment.json` exists with
  `deployment_id=glm52-local-serving-fixture`.

Archive integrity check: recomputing SHA-256 over every
`contract_artifact_sha256` entry in the nine checked result directories above
matched the recorded hashes. Totals: 55 checked artifact files, 0 missing, and
0 mismatched.

Run-state and cleanup-ledger check:

- `bwrap-smoke-20260816T033508Z`: cleanup ledger exists at
  `.scratch/glm52-local-serving/run/cleanup-bwrap-smoke-20260816T033508Z.json`.
  No `benchmark-*.json` state file or lock exists for this specialized
  bwrap-sandbox smoke run.
- `needle-smoke-20260816T033636Z`: benchmark state, cleanup ledger, and lock all
  exist. Benchmark state records `status=completed` and `mode=smoke`.
- `calibration-core-20260816T034300Z`: benchmark state, cleanup ledger, and
  lock all exist. Benchmark state records `status=completed` and
  `mode=calibration`.
- `tbench2-smoke-20260816T155253Z`: benchmark state, cleanup ledger, and lock
  all exist. Benchmark state records `status=environment_setup_failed` and
  `mode=smoke`.
- `swebench-smoke-default-config-20260816T172813Z`: benchmark state, cleanup
  ledger, and lock all exist. Benchmark state records
  `status=environment_setup_failed` and `mode=smoke`.

## Acceptance Ladder

1. Focused unit tests pass for adapter, serving verifier, and deployment helper.

   Status: verified locally.

   Evidence:
   - `python/tests/test_glm52_responses_adapter.py`
   - `python/tests/test_glm52_serving_verifier.py`
   - `python/tests/test_glm52_deployment.py`
   - Latest focused GLM suite: `103 passed`.
   - Serving verifier `archive-manifest.json` now records
     `contract_artifact_sha256`, a file-byte SHA-256 map keyed by the same
     relative paths listed in `contract_artifacts`.
   - Parser-fix regression:
     `scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q`
     passed (`17 passed`). The serving verifier now rejects Responses streaming
     `error` events and non-stream top-level error payloads with
     `VerificationError` messages beginning `Responses stream error:` and
     `Responses API error:`.

2. Live raw Chat verifier passes against Dynamo/SGLang.

   Status: blocked.

   Evidence:
   - Serving verifier and wrapper exist.
   - No live Dynamo/SGLang GLM-5.2 endpoint was available in this environment.
   - Endpoint-failure artifact exists under
     `glm52-serving-results/api-key-env-20260815T010800Z/`, but that is a
     failure classification proof, not a live pass.
   - Fresh live probe evidence:
     `GLM52_CHAT_BASE_URL=http://localhost:8000/v1 GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 scripts/run_glm52_serving_verifier.sh --terminal-bench --results-dir glm52-serving-results/serving-live-probe-20260816T034600Z`
     exited `1`. `chat-models` returned HTTP 404 and `chat-health` returned
     HTTP 501 `Unsupported method ('POST')`, so the process on port 8000 is not
     a working Dynamo/SGLang Chat endpoint.
   - `glm52-serving-results/serving-live-probe-20260816T034600Z/` contains
     `environment.json`, `chat-models.json`, `chat-health.json`,
     `summary.json`, and `archive-manifest.json`; the archive hashes every
     contract artifact and records `summary_status=fail`.
   - Refreshed live probe:
     `GLM52_CHAT_BASE_URL=http://localhost:8000/v1 GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 scripts/run_glm52_serving_verifier.sh --terminal-bench --results-dir glm52-serving-results/serving-live-probe-20260816T150000Z`
     also exited `1`. `chat-models` still returned HTTP 404 HTML, and
     `chat-health` still returned HTTP 501 `Unsupported method ('POST')`, so
     the process on port 8000 remains a non-GLM/non-Chat service.
   - `glm52-serving-results/serving-live-probe-20260816T150000Z/` contains
     `environment.json`, `chat-models.json`, `chat-health.json`,
     `summary.json`, and `archive-manifest.json`; the archive hashes every
     contract artifact and records `summary_status=fail`.

3. Live Responses verifier passes against the adapter.

   Status: blocked.

   Evidence:
   - Responses adapter unit coverage includes models, request conversion,
     streaming conversion, continuation, environment passthrough, and malformed
     tool-call argument rejection.
   - No live adapter connected to GLM-5.2 was available for an end-to-end
     verifier pass.
   - The fresh `serving-live-probe-20260816T034600Z` run stopped at failed raw
     Chat health before Responses verification, so it provides no live
     Responses pass evidence.
   - Fresh Responses-only probe evidence:
     `GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench --results-dir glm52-serving-results/responses-live-probe-20260816T035200Z`
     exited `1`. `responses-models` returned HTTP 404 with SearXNG HTML
     (`generator=searxng/2026.2.26...`), so the process on port 8080 is not the
     GLM-5.2 Responses adapter.
   - `glm52-serving-results/responses-live-probe-20260816T035200Z/` contains
     `environment.json`, `responses-models.json`, `summary.json`, and
     `archive-manifest.json`; the archive hashes every contract artifact and
     records `summary_status=fail`.
   - Refreshed Responses-only probe:
     `GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 scripts/run_glm52_serving_verifier.sh --skip-chat --terminal-bench --results-dir glm52-serving-results/responses-live-probe-20260816T150000Z`
     also exited `1`. `responses-models` still returned HTTP 404 with SearXNG
     HTML (`generator=searxng/2026.2.26...`), so port 8080 remains a search
     service, not the GLM-5.2 Responses adapter.
   - `glm52-serving-results/responses-live-probe-20260816T150000Z/` contains
     `environment.json`, `responses-models.json`, `summary.json`, and
     `archive-manifest.json`; the archive hashes every contract artifact and
     records `summary_status=fail`.
   - Free-port adapter probe evidence:
     `glm52-serving-results/responses-free-port-probe-20260816T103034Z/`
     records `environment: pass` and `responses-models: pass`, proving adapter
     `/v1/models` worked on a random free port. The run still exited fail at the
     terminal Responses gate with the misleading verifier message
     `expected at least 4 tool calls, got 0`.
   - Parser-fix follow-up evidence:
     `glm52-serving-results/responses-free-port-error-probe-20260816T103839Z/`
     records `environment: pass`, `responses-models: pass`, and
     `responses-agent: fail` with
     `Responses stream error: downstream Chat Completions stream error HTTP 501:
     ... Unsupported method ('POST')`. The matching
     `responses-agent.json` contains the same clear error. This proves the
     current blocker is the non-GLM/non-Chat service on `localhost:8000`, not a
     hidden terminal tool-count issue.
   - Live provider readiness remains blocked until a real Dynamo/SGLang GLM-5.2
     Chat Completions endpoint is available behind the adapter.

4. Terminal bench smoke passes.

   Status: blocked.

   Evidence:
   - Harbor agent helper and Terminal-Bench 2 smoke config exist under
     `.scratch/glm52-local-serving/harbor/`.
   - Missing Harbor is classified as `environment_setup_failed` rather than a
     model failure in existing result directories.
   - Fresh prompt command evidence:
     `GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 scripts/run_glm52_benchmark_verifier.sh smoke --suite terminal-bench-2 --pool harbor_terminal --local-container-runtime docker --run-id tbench2-smoke-20260816T034000Z`
     exited `2` with `status=environment_setup_failed` and reason
     `harbor executable not found`.
   - `glm52-benchmark-results/tbench2-smoke-20260816T034000Z/` includes
     `summary.json`, `run.json`, `environment.json`, `benchmark-manifest.json`,
     `harbor/trials.jsonl`, `harbor/configs/terminal-bench-2-smoke.yaml`, and
     `archive-manifest.json`.
   - That run's `archive-manifest.json` records `contract_artifact_sha256` for
     `run.json`, `environment.json`, `summary.json`, the copied manifest, the
     Harbor smoke config, and `harbor/trials.jsonl`.
   - No real Harbor Terminal-Bench 2 task ran.

5. Deployment status and cleanup dry-run work from recorded state.

   Status: verified locally for recorded state, bwrap task cleanup, and
   recorded container/port visibility.

   Evidence:
   - `.scratch/glm52-local-serving/run/deployment.json`
   - `scripts/run_glm52_deployment.sh status --state "$state"` reported a
     throwaway bwrap task root as recorded.
   - `scripts/run_glm52_deployment.sh cleanup --state "$state"` removed the
     throwaway task root and reported `status=clean` and `cleanup=removed`.
   - `python/tests/test_glm52_deployment.py::test_cleanup_ledger_removes_bwrap_task_root`
     passed.
   - Cleanup-ledger `manifest_status()` now reports recorded `containers` and
     `ports` alongside `bwrap_tasks`.
   - Cleanup dry-run now reports recorded ports first as `manual-review` with
     `port ownership must be confirmed before cleanup`, and recorded
     containers as `would-remove`. Non-dry-run cleanup remains conservative for
     these host-owned resources and does not kill port owners or remove
     containers without stronger ownership checks.
   - Fresh host-side prompt command evidence:
     `scripts/run_glm52_deployment.sh status --state .scratch/glm52-local-serving/run/deployment.json`
     reports `deployment_id=glm52-local-serving-fixture`,
     `namespace=glm52-local`, and absent pidfiles for both recorded processes.
   - Fresh host-side prompt command evidence:
     `scripts/run_glm52_deployment.sh cleanup --state .scratch/glm52-local-serving/run/deployment.json --dry-run`
     reports `status=clean`, `dry_run=true`, and reverse-order
     `already-clean` results for `dynamo-sglang` then `responses-adapter`.
   - `python/tests/test_glm52_deployment.py` passed (`11 passed`).

6. Bwrap sandbox smoke passes.

   Status: verified locally.

   Evidence:
   - `glm52-benchmark-results/bwrap-smoke-20260815T215317Z/summary.json`
   - `glm52-benchmark-results/bwrap-smoke-20260816T033508Z/summary.json`
   - `glm52-benchmark-results/bwrap-archive-artifacts-20260815T010000Z/`
     preserves smoke and cleanup contract artifacts.
   - Fresh bwrap smoke evidence:
     `scripts/run_glm52_benchmark_verifier.sh smoke --suite bwrap-sandbox-smoke --pool code_sandbox --execution-backend bwrap_rootfs --run-id bwrap-smoke-20260816T033508Z`
     exited zero with `status=pass`.
   - `glm52-benchmark-results/bwrap-smoke-20260816T033508Z/artifacts/smoke-artifact.json`
     records `work_write=pass`, `output_write=pass`, `checkout_write=denied`,
     and `network=denied`.
   - `glm52-benchmark-results/bwrap-smoke-20260816T033508Z/archive-manifest.json`
     records `contract_artifact_sha256` for `summary.json`,
     `artifacts/smoke-artifact.json`, and `artifacts/cleanup.json`.
   - Bwrap task-root `task.json` now records the original source `input_dir`
     plus task-local `task_input_dir`, `work_dir`, `output_dir`, and `tmp_dir`
     so each sandbox run carries the concrete task-spec directories named by
     the execution prompt.
   - Bwrap task-root preparation now rejects malformed
     `environment_allowlist` variable names before writing `task.json` or
     constructing a `bwrap --setenv` command. Regression coverage:
     `python/tests/test_glm52_bwrap_task_runner.py::test_prepare_task_root_rejects_invalid_environment_allowlist`
     first failed because `BAD-NAME` was accepted, then passed.
   - Bwrap task-root preparation now rejects path-like `run_id` and `task_id`
     values before writing `task.json`; covered cases include `../escape`,
     `.`, and `..`. Regression coverage:
     `python/tests/test_glm52_bwrap_task_runner.py::test_prepare_task_root_rejects_path_like_task_identifiers`
     first failed with `DID NOT RAISE`, then passed.
   - `python/tests/test_glm52_bwrap_task_runner.py` passed (`12 passed`).

7. Benchmark smoke writes complete artifacts.

   Status: verified locally for fixture/static and bwrap code-generation smoke
   paths, not for live model inference.

   Evidence:
   - `glm52-benchmark-results/archive-manifest-20260815T000000Z/`
   - `glm52-benchmark-results/needle-three-position-20260815T000000Z/`
   - `glm52-benchmark-results/needle-smoke-20260816T033636Z/`
   - `glm52-benchmark-results/math-static-smoke-20260815T000000Z/`
   - Fresh Phase 4 prompt command evidence:
     `GLM52_CHAT_BASE_URL=http://localhost:8000/v1 scripts/run_glm52_benchmark_verifier.sh smoke --suite needle-smoke --execution-backend bwrap_rootfs --run-id needle-smoke-20260816T033636Z`
     exited zero with `status=pass`.
   - `glm52-benchmark-results/needle-smoke-20260816T033636Z/summary.json`
     records `mode=smoke`, `execution_backend=bwrap_rootfs`, `status=pass`,
     `tasks_total=3`, `tasks_passed=3`, `model_failures=0`, and
     `infrastructure_failures=0`.
   - The run-scoped artifact set includes `run.json`, `environment.json`,
     `benchmark-manifest.json`, `needle-smoke/samples.jsonl`,
     `needle-smoke/metrics.json`, `needle-smoke/failures.jsonl`,
     `summary.json`, and `archive-manifest.json`.
   - `needle-smoke/samples.jsonl` records beginning, middle, and end needle
     positions with manifest-derived `profile`, `dataset_revision`,
     `harness_revision`, `decoding_profile`, `prompt_sha256`, `latency_seconds`,
     `usage`, and `state=passed`.
   - `archive-manifest.json` records `contract_artifact_sha256` for every
     run-scoped contract artifact.
   - bwrap code-generation smoke now records per-sample latency from the task
     runner and copies per-task codegen artifacts into run-scoped
     `<suite>/artifacts/`.
   - The prepare command now accepts `--run-root` and writes
     `benchmark-<run-id>.json` plus `cleanup-<run-id>.json` for the prepare
     stage.
   - Fixture smoke/calibration run records can now preserve
     `serving_summary_path`, `responses_base_url`, and `chat_base_url` in both
     result-local `run.json` and run-root `benchmark-<run-id>.json` when those
     serving inputs are supplied.
   - Benchmark run-root lock artifacts are now written as
     `benchmark-<run-id>.lock` alongside `benchmark-<run-id>.json` and
     `cleanup-<run-id>.json` for the local run-state writers exercised by
     fixture, bwrap codegen, Harbor, prepare, and conformance paths.
   - Benchmark run-root locks for terminal fixture/static smoke, bwrap codegen
     smoke, and Harbor smoke paths are now finalized after terminal artifacts
     are written. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_writes_run_lock`,
     `python/tests/test_glm52_benchmark_verifier.py::test_write_bwrap_codegen_smoke_run_records_task_roots`,
     and
     `python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials`
     first caught a stale `status=running` lock and now pass.
   - Fresh command-level proof:
     `GLM52_CHAT_BASE_URL=http://localhost:8000/v1 scripts/run_glm52_benchmark_verifier.sh smoke --suite needle-smoke --execution-backend bwrap_rootfs --run-id needle-smoke-lock-20260816T042300Z`
     exited zero. Its run-root lock
     `.scratch/glm52-local-serving/run/benchmark-needle-smoke-lock-20260816T042300Z.lock`
     records `status=completed`, `completed_at`, `benchmark_state_path`,
     `cleanup_state_path`, and
     `result_dir=glm52-benchmark-results/needle-smoke-lock-20260816T042300Z`.
     The matching run-root benchmark state records `status=completed`.
   - Fixture/static smoke resumability is now covered through the public CLI
     path. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_resumes_completed_matching_fixture_suite`
     passed, proving that a second `smoke` command with the same run ID and
     matching manifest hashes preserves existing completed suite artifacts and
     records the suite as `status=resumed` in run state.
   - Fresh command-level resume proof:
     `scripts/run python scripts/glm52_benchmark_verifier.py smoke --suite ruler --manifest .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/benchmark-manifest.yaml --execution-backend bwrap_rootfs --run-id resume-fixture-20260816T052500Z --results-root .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/results --run-root .scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/run`
     exited zero twice. Between runs, `ruler/samples.jsonl` was marked with a
     `resume sentinel pass` string. After the second run, the sentinel remained
     present, `.scratch/glm52-local-serving/tmp/resume-fixture-20260816T052500Z/run/benchmark-resume-fixture-20260816T052500Z.json`
     recorded the suite as `status=resumed`, and `summary.json` still recorded
     `status=pass`.
   - GSM8K calibration now consumes a materialized local JSONL dataset cache
     when present. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_calibration_uses_materialized_gsm8k_dataset_cache`
     passed together with the fallback fixture coverage
     `python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_emits_math_answer_artifacts`.
     The cache-backed sample preserves the local sample id
     `gsm8k-local-0001`, question `What is 40 plus 2?`, expected answer `42`,
     extracted answer `42`, and `endpoint=fixture`; its metrics record one
     passed task with zero model and infrastructure failures, its
     `failures.jsonl` is empty, and its archive manifest records
     `summary_status=pass`. When no cache is present, the existing fixture path
     still emits GSM8K and AIME math answer artifacts.
   - Fixture/static resume now also refuses to reuse artifacts across different
     run modes. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_fixture_benchmark_run_does_not_resume_when_mode_changes`
     first failed because a calibration run with the same run ID reused a
     completed smoke sample, then passed after the resume guard began matching
     the recorded `mode`. Command-level evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py smoke --suite ruler --manifest .scratch/glm52-local-serving/tmp/resume-mode-guard-20260816T071000Z/benchmark-manifest.yaml --execution-backend bwrap_rootfs --run-id resume-mode-guard-20260816T071000Z --results-root .scratch/glm52-local-serving/tmp/resume-mode-guard-20260816T071000Z/results --run-root .scratch/glm52-local-serving/tmp/resume-mode-guard-20260816T071000Z/run`
     exited zero, `ruler/samples.jsonl` was marked with `stale smoke pass`, and
     then
     `scripts/run python scripts/glm52_benchmark_verifier.py calibration --suite ruler --manifest .scratch/glm52-local-serving/tmp/resume-mode-guard-20260816T071000Z/benchmark-manifest.yaml --execution-backend bwrap_rootfs --run-id resume-mode-guard-20260816T071000Z --results-root .scratch/glm52-local-serving/tmp/resume-mode-guard-20260816T071000Z/results --run-root .scratch/glm52-local-serving/tmp/resume-mode-guard-20260816T071000Z/run`
     exited zero. The final sample no longer contains the stale smoke marker,
     run state records `mode=calibration`, and the suite records
     `status=completed`, not `resumed`.
   - Prepare artifacts now include `container_runtime_preflight` for
     Docker-backed suites, recording the selected local runtime plus JSON
     `version` and `info` details when the runtime is reachable.
   - Prepare cache preflight now records whether each suite's dataset and
     harness cache directories exist, and marks cache status `available` only
     when both materialized directories are present. Missing cache inputs remain
     `planned`.
   - Prepare cache handling now has a source-backed materialization path for
     explicit `local_path` `dataset_source` and `harness_source` entries. The
     prepare command copies those sources into the configured benchmark cache
     under the run root's sibling `benchmarks/` directory and records
     `dataset_source_type`, `dataset_source_sha256`, `harness_source_type`, and
     `harness_source_sha256` in `cache_preflight`. Placeholder or source-less
     manifest entries remain `planned` instead of pretending that upstream
     datasets were fetched.
   - Prepare cache handling also supports pinned `git` `dataset_source` and
     `harness_source` entries by running `git clone --no-checkout` followed by
     `git checkout --detach <revision>`, then recording
     `dataset_source_revision` and `harness_source_revision` in
     `cache_preflight`.
   - Prepare cache handling also supports `http_archive` `dataset_source` and
     `harness_source` entries by downloading the pinned URL, validating the
     downloaded bytes against the declared SHA-256, extracting the tar archive
     with data-filtered tar extraction, and recording the source SHA-256 in
     `cache_preflight`.
   - Prepare cache handling also supports `huggingface` and
     `huggingface_or_swebench` `dataset_source` and `harness_source` entries by
     invoking Hugging Face download tooling with a concrete repo/dataset id,
     pinned revision, repo type, and local cache directory. The implementation
     prefers modern `hf download` and falls back to legacy `huggingface-cli`
     when needed. Placeholder revisions remain invalid.
   - Prepare now rejects placeholder suite `dataset_revision` and
     `harness_revision` values, including `@pinned-placeholder`, before writing
     `status: prepared`, run state, or cleanup ledgers. This prevents the
     checked-in placeholder benchmark manifest from producing a misleading
     successful prepare artifact.
   - Prepare now rejects source metadata whose explicit `revision` disagrees
     with the suite-level `dataset_revision` or `harness_revision`, accepting
     either an exact match or the suffix after `@`. This prevents artifacts from
     advertising one benchmark revision while fetching a different source
     revision.
   - Prepare image preflight now records immutable Docker image provenance for
     suites that declare `container_image`: selected runtime, source image
     reference, local image ID, and repo digest from the selected runtime's
     `image inspect` output. Suites without a declared image are classified as
     `invalid_container_image` rather than fabricating image provenance.
   - Prepare image preflight now rejects missing, mutable, or placeholder
     `container_image` declarations before running `docker image inspect` or
     equivalent runtime inspection. Regression coverage includes:
     `python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_artifacts`
     first failed because prepare printed `status=prepared`, then passed after
     the command raised before writing `prepare.json`, benchmark state, or
     cleanup state. Regression coverage also includes:
     `python/tests/test_glm52_benchmark_verifier.py::test_build_image_preflight_rejects_mutable_container_image`
     first failed because the verifier attempted to inspect a tag-only image
     reference, then passed after such suites were classified as
     `invalid_container_image`.
   - The prepare command now treats those invalid image preflight records as a
     hard pre-artifact failure rather than writing `status=prepared` artifacts
     with invalid Docker/Harbor image declarations. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_mutable_container_image_before_artifacts`
     first failed because prepare printed `status=prepared`, then passed after
     the command raised before writing `prepare.json`, benchmark state, or
     cleanup state.
   - Prepare now validates Docker/Harbor image declarations before
     materializing benchmark source caches. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_rejects_missing_container_image_before_source_fetch`
     first failed because `materialize_prepare_caches()` ran before the missing
     `container_image` guard, then passed after image preflight validation moved
     ahead of source materialization. This keeps missing official image pins as
     the fast failure for container-backed suites and avoids fetching upstream
     benchmark sources before the manifest can name the required image.
   - Prepare now accepts repeated `--suite` selectors and filters the manifest
     before image preflight and cache materialization. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_prepare_command_filters_selected_suites_before_image_preflight`
     first failed because `prepare --suite needle-smoke` was rejected by
     argparse, then passed after prepare reused the manifest suite-selection
     helper and selected artifacts stopped requiring full default-suite
     coverage. Command evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --suite needle-smoke --run-id prepare-needle-selected-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/prepare-needle-selected-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-needle-selected-20260816T000000Z/run --skip-endpoints`
     exited zero. Its `prepare.json` records `suites: ["needle-smoke"]`,
     an available local-path cache for `needle-smoke`, and an empty
     `image_preflight`; the copied `benchmark-manifest.json` contains only the
     selected suite.
   - Selected prepare has now also materialized real pinned Git sources for the
     checked-in `ruler` suite. Command evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --suite ruler --run-id prepare-ruler-selected-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/prepare-ruler-selected-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-ruler-selected-20260816T000000Z/run --skip-endpoints`
     exited zero. Its `prepare.json` records only `ruler`, available Git
     dataset and harness caches, and an empty `image_preflight`. Direct Git
     inspection showed dataset HEAD
     `c3f5e3b4f87f97e048793bb510a3a6b19a46bf3a` and harness HEAD
     `8a07e1110d060de48cfc7a9a7987b7659060b60b`, matching the checked-in
     manifest pins.
   - Selected prepare for the checked-in `humaneval` suite now materializes the
     pinned Hugging Face dataset source and pinned EvalPlus harness source.
     Local rootfs environment repair installed Hugging Face tooling with
     `scripts/run env UV_CACHE_DIR=/tmp/glm52-uv-cache uv pip install huggingface-hub`,
     which installed `huggingface-hub==1.27.0` and `hf` at
     `/workspace/monarch/.venv-rootfs/bin/hf`. The legacy
     `huggingface-cli` binary exists in that version but prints
     `huggingface-cli is deprecated and no longer works. Use hf instead.`, so
     the verifier now prefers `hf download` and keeps `huggingface-cli` only as
     a fallback for older environments. Command evidence:
     `scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --suite humaneval --run-id prepare-humaneval-selected-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/prepare-humaneval-selected-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-humaneval-selected-20260816T000000Z/run --skip-endpoints`
     exited zero with `status=prepared`. Its artifact
     `.scratch/glm52-local-serving/tmp/prepare-humaneval-selected-20260816T000000Z/results/prepare-humaneval-selected-20260816T000000Z/prepare.json`
     records only `humaneval`, `dataset_source_type: huggingface`,
     `dataset_source_revision:
     7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544`,
     `harness_source_type: git`, `harness_source_revision:
     26d6d00bb1fd0fa37f39c99d5290da67891d1c5e`, and an empty
     `image_preflight`. Direct inspection showed the dataset cache contains
     `.cache`, `.gitattributes`, `README.md`, and `openai_humaneval`; the
     EvalPlus harness cache HEAD is
     `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e`.
   - Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_reports_missing_huggingface_tool`
     first failed with an uncaught `FileNotFoundError`, then passed after the
     Hugging Face download path wrapped missing executables as
     `BenchmarkVerifierError`.
     `python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_falls_back_to_legacy_huggingface_cli`
     covers the legacy fallback path, and
     `python/tests/test_glm52_benchmark_verifier.py::test_materialize_prepare_caches_downloads_huggingface_sources`
     now expects modern `hf download` without the removed
     `--local-dir-use-symlinks` option.
   - Selected prepare now also materializes the remaining checked-in
     bwrap-backed Hugging Face source pins for `mbpp`, `gsm8k`, and `aime`.
     Command evidence:
     `scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --suite mbpp --run-id prepare-mbpp-selected-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/prepare-mbpp-selected-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-mbpp-selected-20260816T000000Z/run --skip-endpoints`,
     `scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --suite gsm8k --run-id prepare-gsm8k-selected-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/prepare-gsm8k-selected-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-gsm8k-selected-20260816T000000Z/run --skip-endpoints`,
     and
     `scripts/run env HF_HOME=.scratch/glm52-local-serving/tmp/hf-home python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --suite aime --run-id prepare-aime-selected-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/prepare-aime-selected-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-aime-selected-20260816T000000Z/run --skip-endpoints`
     each exited zero with `status=prepared`. Their artifacts each contain only
     the selected suite, available Hugging Face dataset caches, available Git
     harness caches, and empty `image_preflight` lists. Direct inspection
     showed `mbpp` dataset revision
     `4bb6404fdc6cacfda99d4ac4205087b89d32030c`, `gsm8k` dataset revision
     `740312add88f781978c0658806c59bc2815b9866`, `aime` dataset revision
     `8d88b2876a82a080e2f172cc9b25d0d9d2cb4792`, EvalPlus harness HEAD
     `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e`, and
     `lm-evaluation-harness` HEAD
     `8a07e1110d060de48cfc7a9a7987b7659060b60b`, matching the checked-in
     manifest pins.
   - Prepare gold-path preflight now runs deterministic trusted local fixture
     checks for suites whose gold path does not require live model calls or
     external containers: AIME and GSM8K answer extraction each run two
     fixtures, and needle-smoke runs the three-position local-answer fixture.
     Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_runs_local_fixture_checks`
     first failed because the records only said `status=available`, then
     passed after the preflight began executing the local checks.
   - Trusted local gold-path fixtures are no longer blocked by the host bwrap
     prerequisite when they run inside verifier code, while generated-code
     suites such as HumanEval still report missing `bwrap` when the launcher is
     unavailable. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_does_not_require_bwrap_for_trusted_fixtures`
     first failed because GSM8K was reported as `missing_prerequisite`, then
     passed.
   - Fresh command-level prepare evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/tmp/gold-path-prepare-20260816T053200Z/benchmark-manifest.yaml --run-id gold-path-prepare-20260816T053200Z --results-root .scratch/glm52-local-serving/tmp/gold-path-prepare-20260816T053200Z/results --run-root .scratch/glm52-local-serving/tmp/gold-path-prepare-20260816T053200Z/run --skip-endpoints`
     exited zero with `status=prepared`. Its `prepare.json`
     `gold_path_preflight` records AIME and GSM8K
     `answer-extraction-fixture` as `status=passed` with `fixtures_passed=2`
     of `fixtures_total=2`, and needle-smoke `local-answer-fixture` as
     `status=passed` with `fixtures_passed=3` of `fixtures_total=3`.
     The same artifact still records HumanEval `known-good-bad-fixtures` as
     `missing_prerequisite` for `bwrap`, and Terminal-Bench 2 `harbor-oracle`
     as `missing_prerequisite` for `docker` and `harbor`.
   - Command-level prepare state proof:
     `glm52-benchmark-results/prepare-state-20260816T000000Z/prepare.json`,
     `.scratch/glm52-local-serving/run/benchmark-prepare-state-20260816T000000Z.json`,
     and
     `.scratch/glm52-local-serving/run/cleanup-prepare-state-20260816T000000Z.json`.
   - Prepare artifacts now also include result-local `run.json` and
     `environment.json`, and the copied `benchmark-manifest.json`;
     `archive-manifest.json` hashes all three plus `prepare.json`. Red-green
     evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_write_prepare_artifact_records_manifest_and_rootfs`
     first failed with missing `run.json`, later failed with missing
     `benchmark-manifest.json`, then passed. Command-level fixture evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/tmp/conformance-layout-20260816T044200Z/benchmark-manifest.yaml --run-id prepare-layout-20260816T045000Z --results-root .scratch/glm52-local-serving/tmp/prepare-layout-20260816T045000Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-layout-20260816T045000Z/run --skip-endpoints`
     exited zero and its archive listed `environment.json`, `prepare.json`,
     and `run.json`. Fresh post-manifest-copy fixture evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/tmp/conformance-layout-20260816T044200Z/benchmark-manifest.yaml --run-id prepare-layout-20260816T051500Z --results-root .scratch/glm52-local-serving/tmp/prepare-layout-20260816T051500Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-layout-20260816T051500Z/run --skip-endpoints`
     exited zero with `status=prepared`. The result directory contains
     `archive-manifest.json`, `benchmark-manifest.json`, `environment.json`,
     `prepare.json`, and `run.json`; `archive-manifest.json` lists and hashes
     `benchmark-manifest.json`, `environment.json`, `prepare.json`, and
     `run.json` as contract artifacts.
   - The conformance command defaults to all manifest suites when `--suite` is
     omitted, matching the execution prompt's dry-run shape.
   - The smoke command now defaults to the checked-in benchmark manifest when
     `--manifest` is omitted. If `--suite` is omitted, it selects the manifest's
     bwrap fixture/static suites for the default smoke path while leaving
     HumanEval/MBPP codegen and Terminal-Bench 2 Harbor smoke to their explicit
     commands.
   - The smoke command supports the `scripts_run` backend declaration for
     manifest-selected trusted fixture/static suites. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_supports_scripts_run_fixture_backend`
     passed. Command-level evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py smoke --suite ruler --manifest .scratch/glm52-local-serving/tmp/scripts-run-smoke-20260816T055000Z/benchmark-manifest.yaml --execution-backend scripts_run --run-id scripts-run-smoke-20260816T055000Z --results-root .scratch/glm52-local-serving/tmp/scripts-run-smoke-20260816T055000Z/results --run-root .scratch/glm52-local-serving/tmp/scripts-run-smoke-20260816T055000Z/run`
     exited zero with `status=pass`; `summary.json` records
     `execution_backend=scripts_run`, run state records `status=completed`,
     the suite state is `completed`, `ruler/samples.jsonl` exists, and
     `archive-manifest.json` includes `summary.json` as a contract artifact.
   - Fixture/static smoke and calibration samples now record the selected
     `execution_backend` in `samples.jsonl`, matching the run-level backend
     condition recorded in `summary.json` and `environment.json`. Red-green
     evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_records_execution_backend_in_fixture_samples`
     first failed with missing `execution_backend` in the sample artifact, then
     passed after the shared fixture sample writer annotated samples with the
     run backend. Full-file evidence now reports 90 benchmark verifier tests.
   - Fixture/static smoke and calibration samples now also record
     `prompt_template` and `metric`, so each sample artifact preserves every
     manifest condition needed to interpret score comparability alongside
     `profile`, `dataset_revision`, `harness_revision`, `decoding_profile`, and
     `execution_backend`. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_prompt_template_and_metric_in_samples`
     first failed with missing `prompt_template`, then passed after the shared
     fixture sample writer added both manifest fields. Full-file evidence now
     reports 91 benchmark verifier tests.
   - Fixture/static and bwrap-codegen `metrics.json` artifacts now record the
     manifest condition fields used to interpret scores: `profile`,
     `dataset_revision`, `harness_revision`, `prompt_template`,
     `execution_backend`, `decoding_profile`, and `metric`. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_write_fixture_benchmark_run_records_manifest_conditions_in_metrics`
     first failed with missing `profile`, then passed after metrics generation
     reused the suite condition metadata helper.
   - Fixture/static resume now rejects stale completed suite artifacts whose
     `metrics.json` predates the required condition metadata. Red-green
     evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_fixture_benchmark_run_does_not_resume_stale_metrics_schema`
     first failed because a stale `samples.jsonl` sentinel remained after
     rerun, then passed after `_fixture_suite_complete()` required the metrics
     condition fields before marking a suite resumable. Full-file evidence now
     reports 93 benchmark verifier tests.
   - The smoke command supports the `local_docker` backend declaration for
     manifest-selected trusted fixture/static suites without launching an
     unofficial container harness. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_smoke_command_supports_local_docker_fixture_backend`
     first failed because `environment.json` did not record the fixture smoke
     execution backend, then passed after fixture run environments gained
     `mode` and `execution_backend` fields. Command-level evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py smoke --suite ruler --manifest .scratch/glm52-local-serving/tmp/local-docker-smoke-20260816T062000Z/benchmark-manifest.yaml --execution-backend local_docker --run-id local-docker-smoke-20260816T062000Z --results-root .scratch/glm52-local-serving/tmp/local-docker-smoke-20260816T062000Z/results --run-root .scratch/glm52-local-serving/tmp/local-docker-smoke-20260816T062000Z/run`
     exited zero with `status=pass`; `summary.json` and `environment.json`
     both record `execution_backend=local_docker`, run state records
     `status=completed`, the suite state is `completed`, `ruler/samples.jsonl`
     exists, and `archive-manifest.json` includes `summary.json`,
     `environment.json`, and `run.json` as contract artifacts.
   - The calibration command now defaults to the checked-in benchmark manifest
     when `--manifest` is omitted, matching the benchmark spec's documented
     calibration command shape.
   - The conformance command now accepts `--results-root` and `--run-root` and,
     for complete comparable inputs, writes `conformance.json`, copied
     benchmark and published-score manifests, an archive manifest, and run and
     cleanup ledgers.
   - The conformance command rejects backend overrides through the public CLI
     path before writing result artifacts or run ledgers. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_backend_override_before_artifacts`
     passed. Command-level evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py conformance --manifest .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/benchmark-manifest.yaml --published-scores .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/published-scores.yaml --suite humaneval --execution-backend host_subprocess --run-id conformance-override-20260816T054200Z --results-root .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/results --run-root .scratch/glm52-local-serving/tmp/conformance-override-20260816T054200Z/run`
     exited `2` with `error: backend override is not allowed in conformance
     mode`; no result directory, `benchmark-<run-id>.json`, or
     `cleanup-<run-id>.json` was written.
   - Conformance validation now rejects selected suites whose
     `dataset_revision` or `harness_revision` still contains placeholder
     revision markers, including `@pinned-placeholder`, before writing a
     `status: validated` conformance artifact or run state.
   - Conformance validation now rejects selected `local_docker` and
     `harbor_local_docker` suites that lack a concrete `container_image`, before
     writing a `status: validated` artifact or run state.
   - Conformance validation now rejects selected Docker-backed suites whose
     `container_image` is only tag-pinned. The reference must include a
     `sha256` digest before conformance can write a `status: validated`
     artifact or run state.
   - Conformance validation now requires selected suites to declare
     `dataset_source` and `harness_source` metadata whose revisions match the
     suite-level revisions before writing a `status: validated` artifact or run
     state. Earlier conformance input errors, such as missing published-score
     fields or non-comparable scores, still report first.
   - Conformance validation now also rejects declared `dataset_source` and
     `harness_source` objects that omit `revision`, before writing a
     `status: validated` artifact or run state. Regression coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_source_metadata_revisions`
     first failed because conformance wrote a validated artifact with source
     objects that had no revisions, then passed. Command-level evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py conformance --manifest .scratch/glm52-local-serving/tmp/conformance-source-revision-missing-20260816T064500Z/benchmark-manifest.yaml --published-scores .scratch/glm52-local-serving/tmp/conformance-source-revision-missing-20260816T064500Z/published-scores.yaml --suite humaneval --run-id conformance-source-revision-missing-20260816T064500Z --results-root .scratch/glm52-local-serving/tmp/conformance-source-revision-missing-20260816T064500Z/results --run-root .scratch/glm52-local-serving/tmp/conformance-source-revision-missing-20260816T064500Z/run`
     exited `2` with `error: suite humaneval dataset_source.revision must be
     declared`; no result directory, `benchmark-<run-id>.json`, or
     `cleanup-<run-id>.json` was written.
   - The fixture smoke/calibration path rejects `host_subprocess` as a benchmark
     task backend, preserving it for trusted preparation and scoring helpers
     only.
   - The Harbor smoke pass path writes `run.json`,
     `benchmark-<run-id>.json`, and `cleanup-<run-id>.json` before invoking
     `harbor terminal-bench`, then finalizes run state after ingesting Harbor
     trial artifacts.
   - The Harbor smoke pass path now writes `environment.json` with the
     `harbor_local_docker` backend, Responses base URL, local host route, local
     container runtime, Python version, and PID, and includes it in
     `archive-manifest.json`.
   - Harbor smoke `run.json`, `environment.json`, environment-failure
     summaries, and success summaries now record both host-facing
     `responses_base_url` and container-facing
     `harbor_agent_responses_base_url`. Normalized Harbor trial fallback
     endpoints use the job-config agent URL, or a derived container-facing URL,
     before adding `/responses`; raw `harbor-raw/trials.jsonl` remains copied
     source output. Fresh coverage:
     `python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_harbor_and_archives_trials`,
     `python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_ingests_harbor_021_native_result_layout`,
     `python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config`,
     and
     `python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config`
     passed together (`4 passed`).
   - The Harbor smoke pass path now copies the supplied benchmark manifest to
     `benchmark-manifest.json` after validating the selected
     `terminal-bench-2` suite, and includes that artifact in
     `archive-manifest.json`.
   - The classified Harbor environment-failure path applies the same manifest
     validation and archive behavior when a manifest is supplied.
   - The prelaunch classified Harbor environment-failure path now also writes
     result-local `run.json` and `environment.json` and includes both files in
     `archive-manifest.json`.
   - The prelaunch classified Harbor environment-failure path now also writes
     run-root state when invoked by the benchmark verifier. Fresh evidence:
     `GLM52_RESPONSES_BASE_URL=http://localhost:8080/v1 scripts/run_glm52_benchmark_verifier.sh smoke --suite terminal-bench-2 --pool harbor_terminal --local-container-runtime docker --run-id tbench2-lock-failure-20260816T043500Z`
     exited `2` with `status=environment_setup_failed`. The run wrote
     `.scratch/glm52-local-serving/run/benchmark-tbench2-lock-failure-20260816T043500Z.json`,
     `.scratch/glm52-local-serving/run/cleanup-tbench2-lock-failure-20260816T043500Z.json`,
     and
     `.scratch/glm52-local-serving/run/benchmark-tbench2-lock-failure-20260816T043500Z.lock`;
     the lock records `status=environment_setup_failed`, `completed_at`, and
     pointers to the benchmark state, cleanup state, and result directory.
   - The Harbor pass path validates copied `trials.jsonl` records for required
     trial metadata before computing pass/fail summaries.
   - `archive-manifest.json` now records `contract_artifact_sha256`, a
     file-byte SHA-256 map keyed by the same relative paths listed in
     `contract_artifacts`.
   - Post-launch Harbor subprocess failures now finalize both result-local
     `run.json` and `.scratch/glm52-local-serving/run/benchmark-<run-id>.json`
     as `environment_setup_failed` instead of leaving stale `running` state.
   - The Harbor smoke pass path now records its `harbor-raw` output directory in
     `.scratch/glm52-local-serving/run/cleanup-<run-id>.json` before launch, and
     host-side deployment cleanup can dry-run and remove recorded `temp_dirs`.
   - `python/tests/test_glm52_benchmark_verifier.py` passed (`69 passed`).

8. Harbor Terminal-Bench 2 smoke completes or fails with classified environment
   setup failure.

   Status: partial.

   Evidence:
   - Existing smoke commands fail with classified `environment_setup_failed`
     because `harbor` is not installed on the default host PATH.
   - `glm52-benchmark-results/tbench2-config-20260815T000000Z/` and
     `glm52-benchmark-results/harbor-relative-artifacts-20260815T010500Z/`
     preserve Harbor failure artifacts.
   - A scratch host-side Python 3.12 virtualenv at
     `.scratch/glm52-local-serving/tmp/harbor-venv` can install
     `harbor==0.21.0`. The installed Harbor CLI exposes `harbor run --config`,
     not the earlier fake-tested `harbor terminal-bench` command.
   - The verifier now has a pass-path branch that writes a run-scoped Harbor
     JobConfig to `harbor-raw/job-config.yaml`, invokes
     `harbor run --config <job-config> --yes`, ingests Harbor `trials.jsonl`,
     copies Harbor artifacts into the run-scoped result directory, and writes a
     passing summary when all Harbor trials pass. This is covered with fake
     Harbor executables by
     `test_terminal_bench_smoke_invokes_harbor_and_archives_trials` and
     `test_terminal_bench_smoke_invokes_real_harbor_run_config`.
   - The fake-Harbor pass-path test also verifies that run state and cleanup
     ledgers exist before the external Harbor command is invoked.
   - Real host-side smoke with the scratch Harbor venv and Docker present now
     reaches `harbor run --config`. It first failed because Harbor 0.21.0
     resolved `supabase==3.0.0a1`, whose package lacks the
     `acreate_client` symbol imported by Harbor. Pinning `supabase==2.18.1`
     inside the scratch venv restored that symbol.
   - After the scratch Supabase repair, real host-side smoke progressed to
     Harbor registry resolution and failed with
     `Dataset terminal-bench-2@d28711d0da2675d0bb1d56de45ae5df6082438a3 not found`.
     `harbor download terminal-bench-2` also reports the dataset is not found,
     while `harbor download terminal-bench` succeeds and downloads 89 legacy
     Terminal-Bench tasks. The workstream still requires Terminal-Bench 2, so
     this remains an upstream registry/configuration blocker rather than a
     completed smoke.
   - The same fake-Harbor pass-path test verifies the run-scoped
     `environment.json` artifact and its archive-manifest entry.
   - The same fake-Harbor pass-path test verifies the copied
     `benchmark-manifest.json` artifact and its archive-manifest entry.
   - Harbor pass-path validation now rejects copied trials missing `task_id`,
     `trial_id`, `model_id`, `endpoint`, `agent_version`,
     `environment_provider`, or `local_host_route`.
   - If Harbor is present and launches but exits before producing usable trial
     artifacts, the verifier writes a classified failure summary and finalizes
     run state as `environment_setup_failed` for crash-recovery cleanup.
   - The Harbor pass-path cleanup ledger now records the run-scoped
     `harbor-raw` directory as a temporary directory, and
     `scripts/run_glm52_deployment.sh cleanup --state` can remove recorded
     benchmark temp dirs.
   - The direct classified-failure regression verifies the copied
     `benchmark-manifest.json` artifact and archive entry for missing-Harbor
     runs.
   - The direct classified-failure regression now also verifies result-local
     `run.json`, `environment.json`, and their archive-manifest entries for
     missing-Harbor runs.
   - The checked-in Terminal-Bench 2 Harbor smoke config and dataset lock now
     pin the Harbor source to
     `9dd349f28b969268aef419e910e1998149b612a5` and the Terminal-Bench source
     to `d28711d0da2675d0bb1d56de45ae5df6082438a3`. The loader rejects
     placeholder-style source revisions before Harbor execution.
   - The repository default Terminal-Bench 2 smoke config is now preflighted
     before Harbor launch. When it points to
     `terminal-bench-2@d28711d0da2675d0bb1d56de45ae5df6082438a3`, the verifier
     exits `2` with `status=environment_setup_failed` and the unresolved
     registry reason instead of invoking Harbor.
   - Temporary Harbor configs still exercise the real CLI shape,
     `harbor run --config <job-config> --yes`, so the new registry preflight
     does not remove coverage for the launch path.
   - Fresh host-side wrapper evidence with the scratch Harbor venv on `PATH`
     used run id `tbench2-registry-preflight-20260816T000001Z` and exited `2`
     with the unresolved Terminal-Bench 2 registry reason before Harbor launch.
   - Harbor-native execution now progresses past registry resolution, import
     discovery, and artifact-layout parsing. The repaired smoke config uses
     `terminal-bench@2.0` with task `adaptive-rejection-sampler`, and the
     verifier normalizes Harbor 0.21's nested `result.json` layout into the
     run-scoped contract artifact `harbor/trials.jsonl`.
   - Host run `tbench2-harbor-native-infra-20260816T000000Z` produced real
     native Harbor result artifacts and exited with a fail summary:
     `tasks_total=1`, `tasks_passed=0`, `infrastructure_failures=1`,
     `model_failures=0`. Its normalized trial records
     `state=environment_crashed` and exception
     `AttributeError: 'GLM52HarborAgent' object has no attribute 'setup'`.
     This is the next real Harbor agent API boundary, not a registry,
     import, or artifact-layout failure.
   - The context hook compatibility slice added
     `populate_context_post_run(context)` as the minimal no-op Harbor hook.
     Focused verification
     `scripts/run uv run pytest python/tests/test_glm52_harbor_agent.py -q`
     reported `7 passed` from the worker.
   - Real host smoke run
     `tbench2-harbor-context-hook-20260816T000000Z` advanced past the missing
     context hook and exposed the next boundary:
     `AttributeError: 'GLM52HarborAgent' object has no attribute 'run'`. Its
     summary records `status=fail`, `model_failures=1`, and
     `infrastructure_failures=0`.
   - The run-loop compatibility slice added `run(...)` with fake Responses plus
     fake environment TDD. Parent verification
     `scripts/run uv run pytest python/tests/test_glm52_harbor_agent.py -q &&
     scripts/run python -m py_compile scripts/glm52_harbor_agent.py
     python/tests/test_glm52_harbor_agent.py` passed with `8 passed`, and
     `py_compile` exited zero.
   - Real host smoke run `tbench2-harbor-run-loop-20260816T000000Z` advanced
     past the missing `run(...)` boundary and failed when the host Harbor agent
     process called `http://host.docker.internal:8080/v1/responses`. Its summary
     records `status=fail`, `model_failures=1`, and `infrastructure_failures=0`;
     the trial records `URLError: <urlopen error [Errno -2] Name or service not
     known>`.
   - The verifier now has a Harbor-smoke-only strict Responses `/models`
     preflight before `harbor run`. The preflight requires JSON with a non-empty
     `data` list and classifies DNS, connection, HTTP, non-JSON, and empty-model
     responses as `environment_setup_failed` before Harbor launch.
   - Focused bad-endpoint regression evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_bad_responses_models_endpoint_before_harbor`
     passed after proving SearXNG HTML from `/models` is rejected before Harbor
     can run. The Harbor-related subset including
     `test_terminal_bench_smoke_invokes_real_harbor_run_config` also passed, and
     the benchmark verifier module reported `107 passed`.
   - Parent host evidence:
     `PATH="$PWD/.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH"
     scripts/run_glm52_benchmark_verifier.sh smoke --suite terminal-bench-2
     --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml
     --harbor-smoke-config
     .scratch/glm52-local-serving/harbor/configs/terminal-bench-2-smoke.yaml
     --responses-base-url http://host.docker.internal:8080/v1
     --local-container-runtime docker --run-id
     tbench2-responses-preflight-20260816T000000Z --results-root
     .scratch/glm52-local-serving/tmp/results --run-root
     .scratch/glm52-local-serving/tmp/run` exited `2` before Harbor launch. The
     run-scoped `summary.json`, `run.json`, and `harbor/trials.jsonl` record
     `status=environment_setup_failed` with reason
     `Responses /models preflight failed for
     http://host.docker.internal:8080/v1/models: <urlopen error [Errno -2] Name
     or service not known>`.
   - The current real blocker is that no GLM Responses adapter/upstream is
     running at a valid host URL. Host probing showed `localhost:8080` and
     `127.0.0.1:8080` serve SearXNG HTML, and
     `localhost:8000/v1/models` returns HTML 404. A real pass requires starting
     the GLM chat backend and adapter on free ports, then using a
     host-resolvable `--responses-base-url` while leaving
     `--local-host-route host.docker.internal` for Docker.

9. HumanEval, MBPP, GSM8K, AIME, and needle-smoke calibration runs complete.

   Status: partial.

   Evidence:
   - Fresh local calibration command evidence:
     `scripts/run_glm52_benchmark_verifier.sh calibration --suite humaneval --suite mbpp --suite gsm8k --suite aime --suite needle-smoke --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --execution-backend bwrap_rootfs --run-id calibration-core-20260816T034300Z`
     exited zero with `status=pass`.
   - `glm52-benchmark-results/calibration-core-20260816T034300Z/summary.json`
     records `mode=calibration`, `execution_backend=bwrap_rootfs`,
     `status=pass`, and `model_failures=0` plus `infrastructure_failures=0`
     for HumanEval, MBPP, GSM8K, AIME, and needle-smoke.
   - The run directory contains `run.json`, `environment.json`,
     `benchmark-manifest.json`, `summary.json`, `archive-manifest.json`, and
     per-suite `samples.jsonl`, `metrics.json`, and `failures.jsonl` for all
     five named suites.
   - `archive-manifest.json` records `contract_artifact_sha256` for every
     run-scoped contract artifact in the calibration result.
   - The inspected HumanEval, MBPP, GSM8K, AIME, and needle-smoke samples carry
     manifest-derived `profile`, `dataset_revision`, `harness_revision`,
     `decoding_profile`, `prompt_sha256`, `latency_seconds`, `usage`, and
     `state=passed`.
   - The same inspected samples show the current limitation: HumanEval, MBPP,
     GSM8K, and AIME still use fixture responses and `endpoint=fixture`, so
     this is not real benchmark calibration or live model inference.
   - HumanEval/MBPP-style bwrap code-generation smoke is covered by tests and
     fixture artifacts.
   - GSM8K/AIME static fixture extraction and artifact validation are present.
   - GSM8K/AIME static fixture extraction and needle-smoke local-answer
     fixture validation now also run during prepare gold-path preflight and are
     recorded in `prepare.json` before scoring.
   - Needle-smoke fixture calibration artifacts exist.
   - Fixture and bwrap code-generation sample artifacts now include explicit
     manifest-derived `profile` and `decoding_profile` fields, in addition to
     endpoint, latency, usage, dataset revision, and harness revision.
   - Real benchmark adapters and live model inference for these suites are not
     complete.

10. Published conformance runs only after manifests are primary-source pinned.

   Status: verified guardrail, blocked conformance.

   Evidence:
   - `.scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml`
   - `.scratch/glm52-local-serving/benchmarks/published-scores.yaml`
   - `.scratch/glm52-local-serving/published-score-source-check.md`
   - Primary-source GLM-5.2 scores found on the Hugging Face model card are not
     comparable to the current local profiles.
   - The published-score manifest now has placeholder coverage for every
     default conformance suite, including `needle-smoke`.
   - The checked-in benchmark manifest now has concrete non-placeholder
     prepare revisions and source metadata for all default suites. Red-green
     evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_checked_in_benchmark_manifest_has_pinned_prepare_revisions`
     first failed with
     `suite humaneval dataset_revision must be pinned`, then passed after the
     checked-in manifest replaced `@pinned-placeholder` revisions with
     concrete upstream refs and verifier-supported `dataset_source` /
     `harness_source` objects. The published-score placeholder manifest's
     condition fields were updated to match those benchmark revisions while
     keeping `score`, `source_url`, `tolerance`, and `tolerance_basis` invalid.
   - The checked-in Terminal-Bench 2 Harbor smoke config and dataset lock now
     use the same Harbor and Terminal-Bench source pins as the benchmark
     manifest, and placeholder-style Harbor smoke revisions fail validation.
   - Default conformance dry-run exits before inference while placeholders
     remain:
     `error: published score for needle-smoke missing fields: score, source_type, source_url, tolerance, tolerance_basis`.
   - Fresh Phase 6 command evidence:
     `GLM52_CHAT_BASE_URL=http://localhost:8000/v1 scripts/run_glm52_benchmark_verifier.sh conformance --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml --run-id conformance-dry-run-20260816T034900Z`
     exited `2` with
     `error: published score for needle-smoke missing fields: score, source_url, tolerance`.
   - Fresh pinned-revision dry-run evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py conformance --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml --run-id conformance-pinned-revisions-dry-run-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/conformance-pinned-revisions-dry-run-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/conformance-pinned-revisions-dry-run-20260816T000000Z/run`
     exited `2` with
     `error: published score for needle-smoke missing fields: score, source_type, source_url, tolerance, tolerance_basis`.
   - That dry-run wrote no `glm52-benchmark-results/conformance-dry-run-20260816T034900Z/`
     result directory and no matching `.scratch/glm52-local-serving/run/`
     run-state files, confirming validation stops before inference or run
     artifact creation for incomplete conformance inputs.
   - Benchmark suite manifests now require an explicit `profile` field before
     verifier or conformance paths accept them; the regression test first
     failed with `AssertionError: suite profile should be required`, then
     passed, and the full benchmark verifier file now passes with 69 tests.
     The full focused GLM test bundle now passes with 112 tests, and
     `py_compile`, wrapper `bash -n`, and `git diff --check` all exit zero.
   - Complete published-score metadata is still rejected when the score entry
     is explicitly marked `comparable: false`, preventing non-comparable local
     profiles from becoming conformance claims by filling in score fields.
   - Complete published-score metadata is now also rejected when `source_url`
     is not an absolute `http` or `https` URL. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_url_published_score_source`
     first failed because `not-a-url` was accepted, then passed after the
     conformance validator required an HTTP(S) primary-source URL shape.
   - Comparable published-score metadata now also requires
     `source_type: primary`. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_primary_published_score_source`
     first failed because a score with `source_type: secondary` was accepted,
     then passed after `source_type` became a required published-score field
     and conformance validation began rejecting non-primary values.
   - Published-score model identity is now checked against the manifest-level
     model before conformance can proceed. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_published_score_model_mismatch`
     first failed because `other-org/OtherModel` was accepted for a
     `zai-org/GLM-5.2` manifest, then passed after conformance validation
     required the published-score model to match the manifest model.
   - Published-score tolerance is now required to be a finite non-negative
     numeric value before conformance can proceed. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_numeric_tolerance`
     first failed because string tolerance `"0.02"` was accepted, then passed
     after the validator rejected non-numeric tolerance values.
   - Published-score tolerance now also requires a declared
     `tolerance_basis` object before conformance can proceed. Red-green
     evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_tolerance_basis`
     first failed because a complete score with only a numeric tolerance was
     accepted, then passed after `tolerance_basis` became required
     published-score metadata. This enforces the benchmark spec's requirement
     that tolerance claims state a basis such as sample size and variance.
   - Published-score tolerance basis now must declare the benchmark spec's
     concrete basis fields, `sample_size` and `variance`, before conformance
     can proceed. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_sample_size_and_variance_tolerance_basis`
     first failed because objects containing only one of those fields were
     accepted, then passed after the validator required both fields while
     preserving placeholder-string rejection.
   - Published-score `score` is now required to be a finite numeric value
     before conformance can proceed. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_non_numeric_score`
     first failed because string score `"0.9"` was accepted, then passed after
     the validator rejected non-numeric score values.
   - Complete conformance-input fixtures now produce a run-scoped
     `conformance.json` reproducibility artifact with selected suites, matched
     score metadata, manifest hash, and published-score manifest hash.
   - Complete conformance-input fixtures now also write result-local
     `run.json` and `environment.json`, and include both in
     `archive-manifest.json`, matching the Phase 4 run-scoped artifact
     contract. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_writes_reproducibility_artifact`
     first failed because `run.json` was missing, then passed. Command-level
     fixture evidence:
     `scripts/run python scripts/glm52_benchmark_verifier.py conformance --manifest .scratch/glm52-local-serving/tmp/conformance-layout-20260816T044200Z/benchmark-manifest.yaml --published-scores .scratch/glm52-local-serving/tmp/conformance-layout-20260816T044200Z/published-scores.yaml --suite humaneval --run-id conformance-layout-20260816T044200Z --results-root .scratch/glm52-local-serving/tmp/conformance-layout-20260816T044200Z/results --run-root .scratch/glm52-local-serving/tmp/conformance-layout-20260816T044200Z/run`
     exited zero and its archive listed `benchmark-manifest.json`,
     `conformance.json`, `environment.json`, `published-scores.json`, and
     `run.json`.
   - Docker-backed conformance suites now require digest-pinned
     `container_image` references. Mutable tags are rejected before the
     verifier writes run state or a conformance artifact.
   - The exact Phase 6 prompt verification target
     `test_published_score_manifest_validation` now exists. It loads the
     checked-in benchmark and published-score manifests, verifies published
     score coverage for default conformance suites, and asserts that placeholder
     `needle-smoke` score fields still fail before inference.
   - The checked-in benchmark and published-score manifests now include an
     explicit `swe-bench-verified` entry, and
     `validate_manifest_suite_coverage()` requires it with the other default
     suites. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_manifest_coverage_requires_all_named_suites`
     first failed because a manifest without SWE-bench Verified was accepted,
     then passed after the required-suite contract was extended. The SWE-bench
     manifest and score records remain placeholders and non-comparable; they do
     not claim official SWE-bench execution or conformance.
   - Checked-in published-score condition fields now have an explicit drift
     guard against the benchmark manifest. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_checked_in_published_score_conditions_match_benchmark_manifest`
     first failed on `swe-bench-verified.dataset_revision` because the
     published-score placeholder entry still carried the SWE-bench harness
     commit in the dataset revision slot, then passed after that field was
     corrected to the Hugging Face dataset revision
     `SWE-bench/SWE-bench_Verified@78f471bf655a3137b2e8a75af1501690ec009ec3`.
     Score, source URL, tolerance, and comparability placeholders remain
     blocking, so this does not create a conformance claim.
   - Fresh checked-in conformance dry-run after that metadata fix still exits
     before inference and before artifact creation:
     `scripts/run python scripts/glm52_benchmark_verifier.py conformance --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --published-scores .scratch/glm52-local-serving/benchmarks/published-scores.yaml --run-id conformance-condition-guard-20260816T000000Z --results-root .scratch/glm52-local-serving/tmp/conformance-condition-guard-20260816T000000Z/results --run-root .scratch/glm52-local-serving/tmp/conformance-condition-guard-20260816T000000Z/run`
     exited `2` with missing `needle-smoke` score/source/tolerance fields.
     Follow-up `find` checks found no files under the requested result/run
     roots and no matching `.scratch/glm52-local-serving/run` ledger, so the
     guard still blocks incomplete conformance inputs before writing success
     artifacts.
   - SWE-bench Verified prepare gold-path preflight now reports a
     suite-specific `swe-bench-official-harness` check instead of the generic
     `benchmark-native-oracle` fallback. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_build_gold_path_preflight_classifies_missing_harbor`
     first failed because SWE-bench used the generic check name, then passed
     after the verifier named the official-harness check and kept missing
     Harbor classified as `missing_prerequisite`.
   - SWE-bench Verified conformance now rejects otherwise valid inputs that
     lack an `instance_images` declaration before writing run state or a
     conformance artifact. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_requires_swebench_instance_images`
     first failed because conformance wrote `status=validated` with only a
     suite-level container image, then passed after the verifier required
     per-instance image metadata for SWE-bench Verified.
   - SWE-bench Verified conformance now also rejects mutable per-instance
     Docker image tags before writing run state or a conformance artifact.
     Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_command_rejects_mutable_swebench_instance_images`
     first failed because `ghcr.io/swe-bench/swe-0:latest` was accepted, then
     passed after the verifier required each declared instance image to be
     digest-pinned.
   - SWE-bench Verified Harbor smoke files now exist at
     `.scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml`
     and
     `.scratch/glm52-local-serving/harbor/datasets/swe-bench-verified.lock.yaml`.
     They record `status: ready`, `runnable: true`, one smoke instance
     (`astropy__astropy-12907`), the official row image, the exact Docker
     digest, and `conformance.claim: none`, while preserving the checked-in
     benchmark manifest's SWE-bench dataset and harness pins. This is
     metadata/preflight evidence only, not live Harbor execution, benchmark
     success, or published SWE-bench conformance.
   - Red-green evidence:
     `scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_verified_harbor_placeholders_preserve_guardrails -q`
     first failed because the smoke config file was missing, then passed after
     the placeholder config and lock were added.
   - Parent verification:
     `scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider python/tests/test_glm52_benchmark_verifier.py -q`
     reported `108 passed`.
   - Current SWE-bench prepare evidence:
     `scripts/run env PYTHONDONTWRITEBYTECODE=1 HF_HOME=.scratch/glm52-local-serving/tmp/prepare-swebench-current-20260816T153700Z/hf-home python scripts/glm52_benchmark_verifier.py prepare --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml --suite swe-bench-verified --skip-endpoints --run-id prepare-swebench-current-20260816T153700Z --results-root .scratch/glm52-local-serving/tmp/prepare-swebench-current-20260816T153700Z/results --run-root .scratch/glm52-local-serving/tmp/prepare-swebench-current-20260816T153700Z/run`
     exited zero with `status=prepared`. Its artifact
     `.scratch/glm52-local-serving/tmp/prepare-swebench-current-20260816T153700Z/results/prepare-swebench-current-20260816T153700Z/prepare.json`
     records `cache_preflight` status `available` and
     `swe_bench_smoke_image_preflight` status `pass` for
     `astropy__astropy-12907` with digest
     `docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907@sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88`.
     The same prepare artifact still records missing local `docker` and
     `harbor` prerequisites, so this does not prove live SWE-bench execution.
   - Benchmark manifest suite IDs are now required to be unique before suite
     selection or coverage validation can proceed. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_manifest_selection_rejects_duplicate_suite_ids`
     first failed because duplicate IDs were silently collapsed by the suite
     lookup map, then passed after manifest suite loading began rejecting
     duplicate IDs.
   - Published-score suite IDs are now required to be unique before
     conformance validation or conformance artifact writing can proceed.
     Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_duplicate_published_score_suites`
     first failed because duplicate published-score entries for `humaneval`
     were silently collapsed by the score lookup map, then passed after
     published-score loading began rejecting duplicate suite records.
   - Conformance manifests now require a declared manifest-level model identity
     before any published-score comparison can proceed. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_requires_manifest_model_identity`
     first failed because an otherwise complete conformance manifest with no
     `model` was accepted, then passed after conformance validation required a
     non-placeholder manifest model before matching score metadata.
   - Published-score manifests with a top-level `model` now must match the
     benchmark manifest model before conformance validation can proceed.
     Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_published_manifest_model_mismatch`
     first failed because a published-score manifest with top-level
     `model: other-org/OtherModel` was accepted when each score entry matched
     `zai-org/GLM-5.2`, then passed after conformance validation required the
     top-level manifest models to match.
   - Published-score entries now must be objects with a string `suite` field
     before conformance validation or artifact writing can use them.
     Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_conformance_validation_rejects_malformed_published_score_entries`
     first failed because a score entry with `suite: 123` was skipped and later
     surfaced as a missing selected score, then passed after published-score
     loading began rejecting malformed score entries directly.
   - Benchmark manifest suite `execution_backend` values are now restricted to
     the verifier's known local backends:
     `bwrap_rootfs`, `scripts_run`, `local_docker`,
     `harbor_local_docker`, and `host_subprocess`. Red-green evidence:
     `python/tests/test_glm52_benchmark_verifier.py::test_manifest_suite_validation_rejects_unknown_execution_backend`
     first failed because `execution_backend: mystery_backend` was accepted,
     then passed after suite-field validation began rejecting unknown backend
     names before prepare, smoke, calibration, or conformance work can use the
     suite.
   - Terminal-Bench 2 Harbor smoke config now uses the registry-resolved
     binding `terminal-bench@2.0` from
     `harbor-framework/harbor@9dd349f28b969268aef419e910e1998149b612a5`,
     with smoke task `adaptive-rejection-sampler`. The benchmark source
     revision `d28711d0da2675d0bb1d56de45ae5df6082438a3` remains recorded as
     source provenance, not as the Harbor dataset version. The verifier now
     rejects the old unresolved `terminal-bench-2` binding during smoke-config
     validation and generates Harbor JobConfig dataset fields from the config.
     Registry probe evidence:
     `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor download
     terminal-bench@2.0 --repo
     harbor-framework/harbor@9dd349f28b969268aef419e910e1998149b612a5`
     exited zero and downloaded 89 tasks.
   - Fresh full-file evidence:
     `scripts/run python -m pytest python/tests/test_glm52_benchmark_verifier.py -q`
     now reports 107 passed. The Harbor agent tests report 5 passed; the
     focused GLM bundle remains recorded as 153 passed.
  - Real host-side Harbor-native runs now produce native Harbor result
    artifacts for `terminal-bench@2.0` task `adaptive-rejection-sampler`.
    The verifier normalizes Harbor 0.21's nested `result.json` layout into
    run-scoped `harbor/trials.jsonl`. Earlier runs exposed the `setup`,
    `populate_context_post_run`, and `run` Harbor agent API boundaries; those
    compatibility slices are now implemented and covered by Harbor agent tests.
    The latest recorded real Harbor path progressed to calling the configured
    Responses adapter URL and is blocked by endpoint readiness, not registry,
    import, artifact-layout, or missing-agent-method failures.

## Fresh Deployment Lifecycle Evidence

Host-side lifecycle checks were rerun on 2026-08-16 against
`.scratch/glm52-local-serving/run/deployment.json`:

```sh
scripts/run_glm52_deployment.sh status \
  --state .scratch/glm52-local-serving/run/deployment.json
# responses-adapter: status=absent, detail="pidfile is absent", pid=null
# dynamo-sglang: status=absent, detail="pidfile is absent", pid=null

scripts/run_glm52_deployment.sh cleanup \
  --state .scratch/glm52-local-serving/run/deployment.json \
  --dry-run
# status=clean, dry_run=true
# dynamo-sglang: cleanup=already-clean, status=absent, detail="pidfile is absent"
# responses-adapter: cleanup=already-clean, status=absent, detail="pidfile is absent"
```

Interpretation: no managed local GLM Responses adapter or Dynamo/SGLang backend
process is currently running under this deployment state, and cleanup is safe
and idempotent. This is lifecycle cleanup evidence only; it is not live provider
readiness evidence.

Fresh host port probes on 2026-08-16 found no usable default local GLM endpoint:

```sh
curl -i http://127.0.0.1:8000/v1/models
# HTTP/1.0 404 File not found
# Server: SimpleHTTP/0.6 Python/3.11.2

curl -i http://127.0.0.1:8080/v1/models
# HTTP/1.1 404 Not Found
# content-type: text/html; charset=utf-8
# server: granian

curl -i http://127.0.0.1:18080/v1/models
# HTTP/1.1 401 Unauthorized
# {"error":"Unauthorized"}
```

Interpretation: `:8000` is a SimpleHTTP server, `:8080` is an unrelated HTML
service, and `:18080` is not an unauthenticated Responses endpoint for this
workstream. Live verifier and Harbor promotion still require an operator-provided
GLM-5.2 Chat endpoint plus a host-resolvable Responses adapter URL.

## Fresh Host-Control Domain Verification

Main-thread verification on 2026-08-16 confirms that `harbor_local_docker` is a
host-control execution domain and refuses in-rootfs invocation before Harbor
launch. The refusal is an environment classification, not a model failure and
not benchmark success.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_records_rootfs_host_bootstrap_diagnostics \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_refuses_harbor_launch_inside_rootfs \
  -q
# 2 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python scripts/glm52_benchmark_verifier.py smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-container-runtime docker \
  --run-id swebench-rootfs-domain-20260816T125513Z \
  --results-root .scratch/glm52-local-serving/tmp/swebench-rootfs-domain-20260816T125513Z/results \
  --run-root .scratch/glm52-local-serving/tmp/swebench-rootfs-domain-20260816T125513Z/run
# exit 2: status=environment_setup_failed
# reason="host-control domain required for harbor_local_docker: running inside scripts/run rootfs"
```

Artifact inspection:

- `summary.json` records `environment_diagnostics.execution_domain` as
  `scripts_run_rootfs`.
- `summary.json` records `required_execution_domain=host` and
  `host_bootstrap_required=true`.
- `missing_tools` records both `harbor` and `docker`.
- The Harbor tool diagnostic records the repo-mounted candidate
  `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor` and its
  host-absolute shebang.

Regression and hygiene checks:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 121 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

## Fresh Host-Route Guidance Verification

Main-thread verification on 2026-08-16 also exercised the host-control Harbor
path outside `scripts/run` with the scratch Harbor venv on `PATH`. Host
bootstrap tools were present: `environment_diagnostics` records
`execution_domain=host`, `required_execution_domain=host`,
`host_bootstrap_required=false`, no missing tools, Harbor status `ok`, Docker
status `ok`, and Docker socket visibility. The run still refused before Harbor
launch because the host process could not resolve `host.docker.internal`.

The verifier now makes that failure actionable: the reason tells the operator
to use a host-resolvable `--responses-base-url` for the adapter and keep
`--local-host-route host.docker.internal` for Docker containers. This is still
environment evidence only; it is not a model failure, benchmark pass, or
published conformance claim.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_explains_host_docker_route_dns_failure \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_classifies_bad_responses_models_endpoint_before_harbor \
  -q
# red: host-route DNS failure lacked operator guidance
# green: 2 passed

PATH=".scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH" \
  scripts/run_glm52_benchmark_verifier.sh smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --harbor-smoke-config .scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml \
  --responses-base-url http://host.docker.internal:8080/v1 \
  --local-host-route host.docker.internal \
  --local-container-runtime docker \
  --run-id swebench-host-route-guidance-20260816T130234Z \
  --results-root .scratch/glm52-local-serving/tmp/swebench-host-route-guidance-20260816T130234Z/results \
  --run-root .scratch/glm52-local-serving/tmp/swebench-host-route-guidance-20260816T130234Z/run
# exit 2: status=environment_setup_failed
# reason includes the host-resolvable --responses-base-url guidance

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

## Fresh Harbor Agent URL Split Verification

Clean-context review and main-thread TDD found a host/container URL split gap:
`--responses-base-url` was used both for the host `/models` preflight and as
the Harbor agent's in-container Responses URL. A host-resolvable loopback URL
can pass preflight but fail inside Docker. The verifier now keeps the original
host URL for preflight and rewrites only loopback agent URLs to
`--local-host-route` when writing the Harbor job config.

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  -q
# red: Harbor job config passed http://127.0.0.1:18081/v1 to the Dockerized
# GLM52HarborAgent
# green: 1 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_terminal_bench_smoke_invokes_real_harbor_run_config \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config \
  -q
# 2 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
# 122 passed

scripts/run python -m py_compile \
  scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_benchmark_verifier.py

git diff --check
```

## Ticket Closeout Checklist

This checklist maps the execution prompt's ticket closeout rules to the current
tracker state. It is not a completion claim for the overall workstream.

- Closeout rule 1, run focused tests named by the ticket: satisfied for
  resolved Issue 02 and for completed local slices recorded in Issues 01, 03,
  04, 05, and 06. Remaining `ready-for-human` tickets still need fresh focused
  verification when live GLM, Harbor, or comparable conformance evidence exists.
- Closeout rule 2, run `git diff --check`: satisfied for the recorded local
  slices in each issue. This audit's current docs-only updates also run scoped
  `git diff --check` before being reported.
- Closeout rule 3, inspect the diff for unrelated changes: current tracker
  updates are scratch-only and preserve unrelated dirty files. Before any
  commit or ticket resolution, re-inspect the full dirty tree because this
  checkout still contains unrelated tracked changes outside the GLM scratch
  tracker.
- Closeout rule 4, update the ticket with an `## Answer` section and exact
  verification evidence: satisfied for resolved Issue 02 and for the major
  partial slices in Issues 03, 04, and 05. Some suite-specific Issue 06 children
  use `Current Status` or dated evidence sections instead of final `## Answer`
  sections because they are intentionally not resolved.
- Closeout rule 5, leave remaining work as a new numbered ticket instead of
  burying it in chat: satisfied for the fixture-adapter debt by parent Issue 06
  and child tickets 06a through 06f. Remaining live serving, Harbor, and
  conformance blockers are tracked by Issues 01, 03, 04, and 05 and the issue
  status map below.
- Prompt-update rule, update this prompt when ticket behavior changes documented
  in the prompt: current behavior changes are reflected in the audit, issue
  files, and `.scratch/glm52-local-serving/spec.md`. The execution prompt
  remains the work-order source; do not rewrite it to claim completion until the
  final prompt-to-artifact audit passes.

## Remaining Required Work

Issue status map, 2026-08-16:

- Issue 01 (`issues/01-serving-verifier.md`): `ready-for-human`. Local
  verifier, adapter, parser, and deployment-helper coverage exists, but live
  raw Chat and live Responses readiness remain blocked on a real Dynamo/SGLang
  GLM-5.2 endpoint and adapter.
- Issue 02 (`issues/02-bwrap-task-backend.md`): `resolved`. The bwrap task
  backend is complete for the current prompt-to-artifact contract; do not
  reopen it for live benchmark or Harbor work.
- Issue 03 (`issues/03-benchmark-verifier.md`): `ready-for-human`. The verifier
  is partial but not agent-ready because remaining proof requires live GLM
  Responses output, host-control Harbor/local Docker execution, or official
  provider evidence.
- Issue 04 (`issues/04-harbor-agent.md`): `ready-for-human`. Helper and
  artifact plumbing exist, but real Harbor trial artifacts still require a
  valid host-resolvable Responses adapter backed by GLM-5.2 plus host
  Docker/Harbor.
- Issue 05 (`issues/05-published-conformance-manifests.md`):
  `ready-for-human`. Manifest guardrails exist; conformance must remain blocked
  until comparable primary-source score metadata is populated.

- [Issue 01](issues/01-serving-verifier.md): Bring up a live Dynamo/SGLang
  GLM-5.2 endpoint and run the raw Chat serving verifier.
- [Issue 01](issues/01-serving-verifier.md): Run the Responses adapter against
  that endpoint and pass the live Responses verifier, including streaming
  function calls and continuation.
- [Issue 03](issues/03-benchmark-verifier.md) and
  [Issue 04](issues/04-harbor-agent.md): Invoke local Docker Terminal-Bench 2
  and SWE-bench Verified smoke, and copy real Harbor trial artifacts into the
  benchmark result directory. A scratch
  Harbor 0.21.0 install now exists, the verifier uses the real
  `harbor run --config` CLI, and the Terminal-Bench 2 smoke config now resolves
  to `terminal-bench@2.0` in the pinned Harbor repo. The Terminal-Bench 2
  native Harbor path now produces real Harbor artifacts, and the Harbor agent
  has progressed past the `setup` and `run` API boundaries. The current blocker
  is a valid host-resolvable Responses adapter URL backed by a running GLM chat
  endpoint; SWE-bench Verified now routes through the Harbor smoke path but
  still needs a real Harbor executable, local Docker runtime, and live
  Responses endpoint before a benchmark can run. Under `scripts/run`, the
  current Harbor smoke blocker is host-bootstrap/rootfs integration:
  `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor` is visible as a
  repo-mounted file but has a host-absolute shebang, while `/usr/bin/docker`
  and Docker sockets are not visible inside the rootfs. The verifier now
  classifies this as `environment_setup_failed` with `environment_diagnostics`
  rather than launching Harbor or reporting a model/benchmark failure. The
  contract is now explicit: `harbor_local_docker` executes in the host-control
  domain through `scripts/run_glm52_benchmark_verifier.sh`; if invoked from
  inside `scripts/run`, the verifier refuses to launch Harbor and records
  `execution_domain=scripts_run_rootfs` plus `required_execution_domain=host`.
- [Issue 03](issues/03-benchmark-verifier.md): Identify and declare pinned
  official Docker/Harbor image references for Docker-backed suites, including
  SWE-bench Verified per-instance image metadata, before immutable image
  digests can be recorded for the checked-in benchmark manifest. The
  SWE-bench Verified Harbor config and lock now pin the
  first smoke instance (`astropy__astropy-12907`), official row image, and exact
  image digest, and prepare records that metadata preflight as pass. This must
  not be treated as live benchmark success or published conformance evidence.
  The verifier has a pure local
  `resolve_swe_bench_smoke_image_metadata(config, lock)` preflight seam that can
  validate those future declarations once the selected rows and digests exist.
- [Issue 03](issues/03-benchmark-verifier.md): Materialize and verify the
  checked-in benchmark manifest's concrete source pins on this host. Current
  prepare artifacts can materialize explicit local source caches, pinned Git
  sources, pinned HTTP tar archives, and pinned Hugging Face/SWE-bench sources,
  and the checked-in manifest now declares concrete non-placeholder source
  metadata. Selected prepare has materialized the checked-in `needle-smoke`
  local source pins, the checked-in `ruler` Git source pins, and the checked-in
  `humaneval`, `mbpp`, `gsm8k`, and `aime` Hugging Face dataset plus Git harness
  pins. Remaining source materialization gaps are the Docker/Harbor-backed
  `terminal-bench-2` and
  `swe-bench-verified` suites, which still need official image/provider
  metadata and Harbor/local Docker execution evidence before conformance.
- [Issue 03](issues/03-benchmark-verifier.md) and
  [Issue 06](issues/06-real-benchmark-adapters.md): Replace fixture-only
  benchmark paths with live-validated benchmark adapters. HumanEval, MBPP,
  GSM8K, AIME, RULER, and needle-smoke now have bounded fake-Responses
  adapter-path coverage, but none of those slices is live GLM, official harness
  scoring, or published-conformance evidence. This debt is split into
  `.scratch/glm52-local-serving/issues/06-real-benchmark-adapters.md` and
  suite-specific child tickets `06a` through `06f`, which keep fixture paths
  explicitly out of model-inference and published conformance evidence until
  real adapters land.
- [Issue 05](issues/05-published-conformance-manifests.md): Populate
  published-score manifests only for primary-source conditions that match local
  profile, prompt template, decoding profile, benchmark revision, execution
  backend, metric, and tolerance.
- Run a final prompt-to-artifact audit after live endpoint and Harbor evidence
  exists.

## Current Host-Control Terminal-Bench 2 Smoke Probe

Status: not complete.

Command:

```sh
timeout 240s env PATH="$PWD/.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH" \
  GLM52_RESPONSES_BASE_URL=http://127.0.0.1:8080/v1 \
  scripts/run_glm52_benchmark_verifier.sh smoke \
    --suite terminal-bench-2 \
    --execution-backend harbor_local_docker \
    --local-container-runtime docker \
    --responses-base-url http://127.0.0.1:8080/v1 \
    --local-host-route host.docker.internal \
    --run-id tbench2-smoke-20260816T155253Z \
    --results-root glm52-benchmark-results \
    --run-root .scratch/glm52-local-serving/run
```

Exit code: 2.

Result directory:
`glm52-benchmark-results/tbench2-smoke-20260816T155253Z/`.

Run ledger:
`.scratch/glm52-local-serving/run/benchmark-tbench2-smoke-20260816T155253Z.json`.

Contract artifact findings:

- `summary.json`: `status=environment_setup_failed`; suite
  `terminal-bench-2` has `state=environment_setup_failed`,
  `infrastructure_failures=1`, and `model_failures=0`.
- Failure reason:
  `Responses /models preflight failed for http://127.0.0.1:8080/v1/models: HTTP Error 404: Not Found`.
- `environment.json`: host-control execution domain was used, Docker was found
  at `/usr/bin/docker` with a Docker socket present, and Harbor was found at
  `.scratch/glm52-local-serving/tmp/harbor-venv/bin/harbor`.
- `run.json`: `execution_backend=harbor_local_docker`,
  `responses_base_url=http://127.0.0.1:8080/v1`, and
  `harbor_agent_responses_base_url=http://host.docker.internal:8080/v1`.
- `harbor/trials.jsonl`: contains only the synthetic
  `terminal-bench-2/environment-preflight` trial with
  `state=environment_setup_failed`.

Harbor did not actually launch benchmark execution. No `harbor-raw/` output
directory was created for this run; only the preflight trial and empty
`harbor/artifacts/` directory were emitted. This is current setup-failure
evidence for the likely non-adapter URL at `http://127.0.0.1:8080/v1`, not
Terminal-Bench success, conformance, or model-quality evidence.

## Current Handoff Guide Blocker Snapshot

Status: not complete.

Updated `docs/agentic-ai/glm52-local-serving.md` with a current local blocker
snapshot that points operators at the fresh serving-verifier Contract Artifacts:

- `glm52-serving-results/20260816T181200Z-chat/`: Chat-only verifier exited 1;
  `environment.json` passed, `chat-models.json` warned, and
  `chat-health.json` failed because `http://127.0.0.1:8000/v1` refused
  connections.
- `glm52-serving-results/20260816T181200Z-responses/`: Responses-only verifier
  exited 1; `environment.json` passed, and `responses-models.json` failed
  because `http://127.0.0.1:8080/v1/models` returned HTTP 404 SearXNG HTML.

This is handoff hygiene and blocker traceability only. It does not make the
live serving, Harbor-backed benchmark, or published-conformance gates pass.

Fresh verification:

```sh
git diff --check -- docs/agentic-ai/glm52-local-serving.md
rg -n "[ \t]+$|Current Local Blocker Snapshot|20260816T181200Z" \
  docs/agentic-ai/glm52-local-serving.md
```

The diff check passed, and the `rg` command found the new heading plus both
fresh result directories and no trailing-whitespace matches.

## Current Harbor/Docker Versus Adapter Blocker

Status: not complete.

The latest host-control Harbor-backed smoke artifacts narrow the remaining
runner blocker. Docker and Harbor are available in the recorded Terminal-Bench 2
and SWE-bench Verified attempts; both runs stop at the GLM Responses adapter
preflight:

- `glm52-benchmark-results/tbench2-smoke-20260816T155253Z/summary.json`:
  `status=environment_setup_failed`,
  `environment_diagnostics.tools.docker.status=ok`,
  `environment_diagnostics.tools.harbor.status=ok`, and suite reason
  `Responses /models preflight failed for http://127.0.0.1:8080/v1/models:
  HTTP Error 404: Not Found`.
- `glm52-benchmark-results/swebench-smoke-default-config-20260816T172813Z/summary.json`:
  `status=environment_setup_failed`,
  `environment_diagnostics.tools.docker.status=ok`,
  `environment_diagnostics.tools.harbor.status=ok`, and the same Responses
  `/models` HTTP 404 reason.

Updated `issues/03-benchmark-verifier.md` and `issues/04-harbor-agent.md` to
reflect that the next non-repeated live gate is a valid GLM-backed Responses
adapter URL. Repeating the Harbor smoke against `http://127.0.0.1:8080/v1`
would only reproduce known SearXNG/404 blocker evidence.

Fresh verification:

```sh
python3 - <<'PY'
import json
from pathlib import Path

for p in [
    Path("glm52-benchmark-results/tbench2-smoke-20260816T155253Z/summary.json"),
    Path("glm52-benchmark-results/swebench-smoke-default-config-20260816T172813Z/summary.json"),
]:
    data = json.loads(p.read_text())
    print(p)
    print("status=", data["status"])
    print("docker=", data["environment_diagnostics"]["tools"]["docker"]["status"])
    print("harbor=", data["environment_diagnostics"]["tools"]["harbor"]["status"])
    print("reason=", data["suites"][0]["reason"])
PY
```

Both artifact summaries printed `status=environment_setup_failed`,
`docker=ok`, `harbor=ok`, and the Responses `/models` HTTP 404 reason.

## Current Published Conformance Handoff Boundary

Status: not complete.

Updated `docs/agentic-ai/glm52-local-serving.md` with an explicit published
conformance boundary. The checked-in
`.scratch/glm52-local-serving/benchmarks/published-scores.yaml` manifest still
uses `TODO-primary-source`, `TODO` score, and `TODO` tolerance placeholders for
every suite, and those placeholders must not be replaced with secondary
articles, incompatible model-card rows, or fixture smoke outputs. The guide now
points operators back to the exact condition match required by the prompt:
profile, prompt template, decoding profile, benchmark revision, execution
backend, metric, and tolerance must all match before a primary-source score can
support conformance.

This is handoff hygiene and guardrail reinforcement only. It does not populate
comparable primary-source scores and does not make conformance pass.

## Current EvalPlus Samples Artifact Coverage

Status: not complete.

The importable-`evalplus` fake-runner tests for HumanEval and MBPP now verify
that the generated EvalPlus samples JSONL file is part of the run-scoped
Contract Artifact trail:

- HumanEval: the test asserts
  `humaneval/artifacts/humaneval-001-codegen-artifact-evalplus-samples.jsonl`
  exists, contains `task_id=HumanEval/0` and the generated solution, and is
  listed in `archive-manifest.json`.
- MBPP: the test asserts
  `mbpp/artifacts/mbpp-001-codegen-artifact-evalplus-samples.jsonl` exists,
  contains `task_id=MBPP/0` and the generated solution, and is listed in
  `archive-manifest.json`.

This closes an artifact-quality gap in the official-harness attempt path. It is
still fake-runner coverage only; the rootfs does not currently import real
`evalplus`, and no official pass@1 or published conformance claim is made.

## SGLang Schema Runtime Live Gate Attempt

Status: not complete.

The schema-driven local SGLang runtime path is now code-ready through fake
repeat-loop coverage, but the live Task 10 gate is blocked before SGLang launch
because the governed rootfs does not import SGLang:

- Schema materialization and validation passed with
  `.scratch/glm52-local-serving/config/sglang-local.yaml` and
  `.scratch/glm52-local-serving/tmp/local-environment.yaml`.
- Live repeat artifact:
  `glm52-serving-results/glm52-sglang-local-repeat-20260816T222859Z-23ca9e4a/loop-summary.json`.
- First run ID:
  `glm52-sglang-local-20260816T222859Z-1-51d60225`.
- Selected port: `19000`.
- Launch status: `failed`.
- Error:
  `sglang help preflight failed: /usr/bin/python: Error while finding module specification for 'sglang.launch_server' (ModuleNotFoundError: No module named 'sglang')`.
- Teardown status: `failed` with `cannot teardown without process record`,
  because launch stopped before `Popen` and no owned process group existed.

Run-scoped blocker artifacts now include:

- `glm52-serving-results/glm52-sglang-local-repeat-20260816T222859Z-23ca9e4a/loop-summary.json`
- `glm52-serving-results/glm52-sglang-local-20260816T222859Z-1-51d60225/materialized-sglang-runtime.yaml`
- `glm52-serving-results/glm52-sglang-local-20260816T222859Z-1-51d60225/resolved-local-paths.yaml`
- `glm52-serving-results/glm52-sglang-local-20260816T222859Z-1-51d60225/launch-summary.json`
- `glm52-serving-results/glm52-sglang-local-20260816T222859Z-1-51d60225/logs/telemetry.jsonl`
- `glm52-serving-results/glm52-sglang-local-20260816T222859Z-1-51d60225/sandbox/resolved-bwrap-plan.yaml`

Rootfs import checks:

```sh
scripts/rootfs/enter_rootfs.sh --repo-readonly \
  --rootfs /data02/home/philip.yang/workspace/monarch/scripts/rootfs/rootfs \
  -- python - <<'PY'
import importlib.util
import sys
print(sys.executable)
print(importlib.util.find_spec("sglang"))
PY

scripts/rootfs/enter_rootfs.sh --repo-readonly \
  --rootfs /data02/home/philip.yang/workspace/monarch/scripts/rootfs/rootfs \
  -- /workspace/monarch/.venv-rootfs/bin/python - <<'PY'
import importlib.util
import sys
print(sys.executable)
print(importlib.util.find_spec("sglang"))
PY
```

Both checks printed `None` for `importlib.util.find_spec("sglang")`, using
`/usr/bin/python` and `/workspace/monarch/.venv-rootfs/bin/python`
respectively. The next live-serving step is to provision SGLang into the
governed rootfs/venv or update the rootfs build contract to include it, then
rerun the same repeat gate. This attempt does not prove live SGLang launch,
model identity, chat completions, Dynamo, Responses, Harbor, EvalPlus, or
published conformance readiness.

## SGLang Native Generation Diagnostics

Status: not complete.

The governed rootfs now has a rootfs-projected SGLang venv and model cache
path, and live SGLang reaches HTTP readiness. The blocker has moved from
missing SGLang installation to native engine generation:

- Active local environment:
  `.scratch/glm52-local-serving/config/local-environment.vartmp-rootfs.yaml`.
- Active declared SGLang config:
  `.scratch/glm52-local-serving/config/sglang-local.yaml`.
- Rootfs:
  `/data01/builder/opt_draccus/monarch-glm52-local-serving/rootfs/rootfs-ca484a4d579b45c0`.
- Cache root:
  `/var/tmp/monarch-glm52-local-serving-cache/glm52-sglang-local`.

Live artifacts:

- `glm52-serving-results/glm52-sglang-local-20260817T125005Z-1-9b9671ab/`:
  SGLang launched on port `19000`, `/v1/models` passed, native `POST
  /generate` accepted the request, and the generate probe timed out after
  `300s`. Teardown returned GPUs to zero memory.
- `glm52-serving-results/glm52-sglang-local-20260817T130527Z-1-0e77aae2/`:
  same profile with schema-owned diagnostic prompt `Say OK.` and
  `max_new_tokens: 1`; `/v1/models` passed, native `/generate` accepted the
  one-token request, and the generate probe timed out after `300s`. Teardown
  returned GPUs to zero memory.
- `glm52-serving-results/glm52-sglang-local-20260817T131416Z-1-3695c49e/`:
  temporary no-`--skip-server-warmup` diagnostic; `/v1/models` still passed and
  native `/generate` still timed out after `300s`. Teardown returned GPUs to
  zero memory.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T132304Z-42f9f9c0/`
  and
  `glm52-serving-results/glm52-sglang-local-repeat-20260817T132604Z-0094b773/`:
  attempts to run the temporary `--dsa-decode-backend trtllm` diagnostic failed
  before process start because GPU 7 was occupied by another user's process.
  The launcher wrote `teardown.status: not_started` and did not kill or reuse
  non-owned processes.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T133808Z-8b03fa09/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T133808Z-1-a16e9ec9/`:
  the `trtllm` diagnostic ran after the repeat runner observed all eight
  visible GPUs free through `--wait-for-gpu-free-seconds 300`. The materialized
  launch command used `--dsa-decode-backend trtllm`, `/v1/models` returned
  `zai-org/GLM-5.2`, and native `/generate` accepted the one-token request, but
  the generate probe still timed out after `300s`. Teardown stopped the owned
  process group; current post-run GPU occupancy was a non-owned GPU 7 process.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T135226Z-39aba0e1/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T135226Z-1-8e0f8784/`:
  the active `flashmla_kv` profile reproduced the same native `/generate`
  timeout. The launcher sent owned `SIGQUIT` to process group `1893257` before
  teardown, and `stderr.log` recorded `SIGQUIT received` plus SGLang's message
  that it would sleep five seconds before crash diagnostics. Teardown began
  before those delayed diagnostics flushed, so the launcher now waits six
  seconds after a successful diagnostic signal before teardown.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T140313Z-5d340f2b/`:
  a retry with the diagnostic flush wait did not start SGLang. The repeat
  wait observed all visible GPUs free, but the final strict launch preflight
  failed because non-owned VLLM workers occupied GPU 1 before `Popen`.
- 2026-08-17 diagnostic hardening: the declared SGLang profile now owns
  `observability.crash_dump_folder: /run/glm52/crash-dumps`, and the
  materialized SGLang launch command must include the matching
  `--crash-dump-folder` flag. This is based on SGLang's `--crash-dump-folder`
  handling, which sets CUDA coredump environment and creates the destination
  directory. Verification:
  `MONARCH_ROOTFS_CACHE_ROOT=/data01/builder/opt_draccus/monarch-rootfs-cache scripts/rootfs/enter_rootfs.sh --rootfs /data01/builder/opt_draccus/monarch-glm52-local-serving/rootfs/rootfs-ca484a4d579b45c0 -- uv run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`
  passed with `118 passed`. A default `scripts/run` attempt failed before
  pytest because exporting the repo-local default rootfs hit `No space left on
  device`; use the `/data01` rootfs path for this workstream.
- A live retry was not attempted after this hardening because all eight GPUs
  were occupied by non-owned `VLLM::Worker_TP*` processes using about
  `103282` to `103310` MiB each. This remains a valid strict-preflight blocker,
  not SGLang completion evidence.
- 2026-08-17 follow-up: the owned `SIGQUIT` diagnostic summary now records the
  sandbox crash dump folder, the resolved host crash dump path, and a relative
  file inventory from that directory after the six-second flush wait. This makes
  the next live `/generate` timeout audit self-contained even when the crash
  dump directory is empty. Verification used the same `/data01` rootfs command
  above and passed with `118 passed`. A live retry remained blocked because all
  eight GPUs were occupied by non-owned `VLLM::Worker_TP*` processes using
  about `154470` MiB each.

Current diagnosis:

- The blocker is no longer SGLang import, rootfs entry, port allocation, model
  identity, or OpenAI route selection.
- The failing layer is native SGLang generation/decode: the server accepts
  `/generate` but does not produce text before timeout.
- Probe size, `--skip-server-warmup`, `--dsa-decode-backend trtllm`,
  `--disable-overlap-schedule`, and `--moe-runner-backend triton` have been
  ruled out as sufficient fixes.
- The `--disable-overlap-schedule` one-variable diagnostic used
  `.scratch/glm52-local-serving/tmp/sglang-local-disable-overlap-schedule.yaml`.
  It differs from the active profile only by appending
  `--disable-overlap-schedule`. Source grounding: SGLang defines this flag as
  disabling the scheduler that overlaps CPU scheduling with GPU model workers,
  and the failure was localized to native generation/decode after readiness.
  Materialization check showed the generated launch command had
  `extra= ['--disable-overlap-schedule']`, `missing= []`, and exactly one
  occurrence of the flag.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T142318Z-b2665a74/`:
  attempted to run the `--disable-overlap-schedule` diagnostic through the
  repeat runner with `--wait-for-gpu-free-seconds 300` and
  `--gpu-free-stable-seconds 60`. It did not reach SGLang launch. The only
  artifact is `loop-summary.json`, which reports `status: failed` because the
  GPU-free wait timed out: visible GPU 0 was occupied by pid `2026492`
  (`VLLM::Worker_TP0_EP0`, `96520` MiB). A follow-up `nvidia-smi` check showed
  all eight GPUs occupied by non-owned `VLLM::Worker_TP*` processes using about
  `96520` MiB each. This is blocker evidence, not generation evidence, and it
  does not test whether disabling overlap fixes the `/generate` timeout.
- 2026-08-17 blocker artifact hardening: GPU occupancy failures now carry a
  structured `blocked_gpus` list through `GpuOccupancyError`, and repeat
  `gpu_wait` failure summaries include every occupied visible GPU instead of
  only the first one named in the error string. Verification:
  `MONARCH_ROOTFS_CACHE_ROOT=/data01/builder/opt_draccus/monarch-rootfs-cache scripts/rootfs/enter_rootfs.sh --rootfs /data01/builder/opt_draccus/monarch-glm52-local-serving/rootfs/rootfs-ca484a4d579b45c0 -- uv run python -m pytest python/tests/test_glm52_sglang_runtime.py -q`
  passed with `118 passed`. This improves future blocker evidence but does not
  prove SGLang generation.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T143755Z-0bff4e54/`:
  reran the `--disable-overlap-schedule` diagnostic with
  `--wait-for-gpu-free-seconds 0` after the launch-preflight propagation fix.
  It failed before `Popen`; `cycles[0].launch.status` is `failed`,
  `cycles[0].teardown.status` is `not_started`, and the child run directory
  stops at materialization, rootfs plan, help preflight, and a
  `launch-summary.json` with `status: launch_failed`. There is no
  `process.yaml`, no server log, and no generation result. The
  `loop-summary.json` now carries
  `cycles[0].launch.blocked_gpus` for all eight visible GPUs:
  indices `0..7`, pids `2026492`, `2026765`, `2026886`, `2027210`, `2027527`,
  `2027805`, `2028126`, and `2028422`, all named `VLLM::Worker_TP*` and using
  about `154470` MiB each. This confirms the strict no-kill/no-fallback GPU
  blocker is now fully captured for launch-preflight failures, but it is still
  not SGLang generation evidence.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T145416Z-8abdaf61/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T145416Z-1-2abac4b8/`:
  the `--disable-overlap-schedule` diagnostic ran after the repeat runner
  observed all eight visible GPUs free for the configured 60-second stable
  window. The materialized launch command used the `/data01` rootfs, port
  `19000`, `--crash-dump-folder /run/glm52/crash-dumps`, and exactly one
  `--disable-overlap-schedule` flag. `/v1/models` returned
  `zai-org/GLM-5.2`, native `/generate` accepted the one-token request, and the
  generate probe still timed out after `300s`. The owned diagnostic path sent
  `SIGQUIT`, waited six seconds, and recorded crash dump inventory containing
  `n116-077-207/crash_dump_2026-08-17_15-02-58.pkl`. Teardown stopped the
  owned process group; `process.yaml` ended with `status: stopped` and
  `stop_reason: terminated`, `teardown-summary.json` reports
  `status: already_stopped`, port `19000` was no longer listening afterward,
  and `nvidia-smi --query-compute-apps` reported no active compute processes.
  This is live SGLang blocker evidence: launch and model identity are real, but
  generation is still not proven.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T150751Z-1d162a9c/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T150751Z-1-4c87f083/`:
  tested the one-variable `--moe-runner-backend triton` diagnostic after a
  60-second all-GPU stable-free window. The materialized command used the same
  `/data01` rootfs and port `19000`, retained
  `--crash-dump-folder /run/glm52/crash-dumps`, and added exactly
  `--moe-runner-backend triton`. `/v1/models` returned `zai-org/GLM-5.2`, and
  native `/generate` accepted the one-token request, but SGLang closed the HTTP
  connection without a response after the scheduler crashed. `stderr.log`
  records a scheduler traceback through
  `sglang/srt/utils/offloader.py:145` into
  `torch.nn.utils.stateless.functional_call`, ending with
  `ValueError: functional_call got multiple values for keys
  ['self_attn.attn_mha.kv_b_proj.weight', 'self_attn.kv_b_proj.weight'], which
  are tied. Consider using tie_weights=False`. The diagnostic path sent
  `SIGQUIT`, recorded crash dump
  `n116-077-207/crash_dump_2026-08-17_15-13-47.pkl`, and teardown left no
  run-owned process or compute app. This rules out Triton MoE as a direct fix
  under the current `cpu_offload_gb: 16` profile and points the next diagnostic
  at the CPU-offload/tied-weight interaction.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T151603Z-ad63b324/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T151603Z-1-3075c47d/`:
  tested the one-variable no-CPU-offload diagnostic
  `.scratch/glm52-local-serving/tmp/sglang-local-no-cpu-offload.yaml`, whose
  materialized argv changed only `--cpu-offload-gb 16` to
  `--cpu-offload-gb 0`. The repeat runner again observed all eight GPUs free
  for the 60-second stable window, but SGLang exited before `/v1/models`
  readiness with `returncode=137`. `stderr.log` records
  `torch.OutOfMemoryError: CUDA out of memory` while allocating MoE weights on
  GPU 2; that GPU had only `64.75 MiB` free after the process had already used
  about `178.27 GiB`. No models or generate probe artifacts were written.
  `process.yaml` ended with `status: stopped` and
  `stop_reason: process_group_absent`, teardown reported
  `status: already_stopped`, and no active compute apps remained. This rules
  out simply disabling CPU offload for the current memory profile.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T152148Z-8afefe11/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T152148Z-1-a2b9d576/`:
  reran the `--moe-runner-backend triton` diagnostic after a local SGLang venv
  patch changed `sglang/srt/utils/offloader.py` to call
  `functional_call(..., tie_weights=False)`. The original offloader file hash
  was
  `1d89240584d56990174e22f31f1dd89d8585075607e14f6491a943dbd44aabed`; the
  patched hash was
  `0c6f79db8bc8cffcdf4152e10864b04963cb6844ff50a2435107d4e0ee127c3d`. The
  repeat runner again observed all eight GPUs free for the 60-second stable
  window, launched on the run-owned port `19000`, and `/v1/models` returned
  `zai-org/GLM-5.2`. Native `/generate` still did not complete: SGLang closed
  the HTTP connection after scheduler crashes on all TP ranks. The tied-weight
  `functional_call` error disappeared, but `stderr.log` now records
  `RuntimeError: Expected all tensors to be on the same device, but got mat2 is
  on cpu, different from other tensors on cuda:<rank>` at
  `sglang/srt/models/deepseek_common/attention_forward_methods/forward_mla.py:710`,
  `q_nope_out = torch.bmm(q_nope.transpose(0, 1), self.w_kc)`. Source
  inspection shows `w_kc` and `w_vc` are plain tensor attributes initialized as
  `None` in `deepseek_v2.py` and assigned by the DeepSeek weight loader, not
  registered parameters or buffers. That makes the remaining blocker consistent
  with `OffloaderV1` moving only `module.state_dict()` entries to CUDA during
  `functional_call` while absorbed MLA side tensors stay on CPU. The diagnostic
  path sent `SIGQUIT`, recorded crash dump
  `n116-077-207/crash_dump_2026-08-17_15-28-11.pkl`, and teardown left the
  run-owned process stopped with no generation artifact. This is blocker
  evidence, not completion evidence.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T153422Z-2270bbbc/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T153422Z-1-e2856b57/`:
  reran the same `--moe-runner-backend triton` diagnostic after extending the
  local SGLang venv patch so `OffloaderV1` temporarily moves absorbed-MLA plain
  tensor attributes (`w_kc`, `w_vc`, and related scales) to the target device
  around the wrapped forward and restores them afterward. The patched
  `offloader.py` hash for this run was
  `7d9b58db50c64a06561c3e2ef00ccc06c61e4e8172f0178b23e630db2166550a`.
  A CUDA micro-check inside the rootfs-projected SGLang venv verified that a
  CPU `w_kc` plain tensor moves to CUDA and restores to the original object
  after the helper runs. The live repeat runner observed all eight GPUs free
  for the 60-second stable window, launched on run-owned port `19000`, and
  `/v1/models` returned `zai-org/GLM-5.2`. Native SGLang generation completed
  for the first time in this workstream: `probes/generate.json` records one
  output token with content `"You"` (`payload.text` was `" You"`,
  `completion_tokens: 1`, `finish_reason.type: length`, `e2e_latency:
  158.43309165816754`). The run also wrote `probes/completions.json` and
  `probes/chat-completions.json`. The repeat wrapper still exited nonzero
  because successful-cycle teardown compared `process.yaml` against the
  pre-launch materialized config instead of reloading the post-model-cache
  `materialized-sglang-runtime.yaml`; the error was `process record outer_argv
  must match materialized config`. No listener remained on port `19000`; a
  transient GPU process from the run disappeared during ownership inspection.
  This artifact proves direct live SGLang generation, but it is not yet a clean
  repeatability pass because teardown acceptance failed.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T154435Z-42e6204f/`
  and child run
  `glm52-serving-results/glm52-sglang-local-20260817T154435Z-1-76692ead/`:
  reran the same diagnostic after patching the repeat runner so successful
  teardown reloads the post-launch materialized config. This retry did not test
  the fixed successful-teardown path because SGLang failed before `/v1/models`.
  The repeat runner observed a 60-second all-GPU stable-free window, but SGLang
  then exited with `returncode=137` during startup. `stderr.log` records
  SGLang's memory-balance guard:
  `RuntimeError: The memory capacity is unbalanced. Some GPUs may be occupied by
  other processes`, with `pre_model_load_memory=147.90692138671875` and
  `local_gpu_memory * 0.9` around `158.57` to `158.85`. Teardown reported
  `status: already_stopped`, `process.yaml` ended with `status: stopped` and
  `stop_reason: process_group_absent`, and port `19000` was not listening
  afterward. A later `nvidia-smi` sample showed a non-owned process,
  `python3 xperf_plugin/unit_test/tf/test_mfalcon.py`, using about `28.5 GiB`
  on GPU 5; it was not an SGLang command or process group and was left alone.
  This artifact is external-occupancy/startup blocker evidence, not a
  generation regression and not a clean repeatability pass.
- `glm52-serving-results/prepare-venv/sglang-venv.json` was refreshed through
  the governed `prepare-venv` path after extending
  `scripts/glm52_sglang_offloader_patch.py` to patch both multi-line and
  single-line upstream `functional_call` wrappers. The record now includes
  `checks.offloader_patch.patch_id:
  glm52-offloader-v1-plain-tensor-attrs-v1`, `changed: true`, and
  `sha256_after:
  9ac28bc702ae84608f3ebbe80987e4f382d4e8e9dc8a8f1920a1947091b41097` for
  `/cache/glm52/venvs/sglang/lib/python3.12/site-packages/sglang/srt/utils/offloader.py`.
  This makes the offloader fix reproducible under the bwrap-rootfs-owned
  SGLang venv instead of depending on a manual site-packages edit.
- `glm52-serving-results/glm52-sglang-local-repeat-20260817T155846Z-1cfe6ce1/`
  is the first clean governed SGLang-only repeatability pass. Its
  `loop-summary.json` reports `status: passed`; cycles `1..3` launched and
  tore down cleanly on run-owned ports `19000`, `19001`, and `19002`. Child run
  artifacts are
  `glm52-serving-results/glm52-sglang-local-20260817T155846Z-1-df427599/`,
  `glm52-serving-results/glm52-sglang-local-20260817T160433Z-2-e49b1e4a/`,
  and
  `glm52-serving-results/glm52-sglang-local-20260817T161010Z-3-e827a64c/`.
  Each child wrote `/v1/models`, `/generate`, `/v1/completions`, and
  `/v1/chat/completions` probe artifacts. `/v1/models` advertised
  `zai-org/GLM-5.2`; `/generate` produced one token with content `"You"` and
  `finish_reason.type: length`; `/v1/completions` produced `"You"`; and
  `/v1/chat/completions` produced `"OK"`. Every child `process.yaml` ended with
  `status: stopped`, and a post-run `nvidia-smi` sample showed zero GPU memory
  used on GPUs `0..7` with no compute apps listed.
- This is real local SGLang GLM-5.2 inference and clean SGLang
  launch/probe/teardown evidence for the current patched-offloader
  `--moe-runner-backend triton` profile. It is not Dynamo evidence, not
  Responses adapter evidence, not Harbor or benchmark evidence, not EvalPlus
  evidence, and not published conformance evidence. Those gates remain open.
- The parent end-to-end inference runner fails before live SGLang launch when
  the Dynamo prerequisite is not satisfied. Earlier blocker run
  `glm52-serving-results/glm52-inference-dynamo-preflight-20260817T162622Z/`
  exited `2` and wrote `reason: placeholder_argv` for the old proxy-style
  placeholder command. That remains valid historical fail-fast evidence only;
  it is not a live Dynamo `/v1/models` or chat-completions proof.
- Dynamo package inspection found `ai-dynamo==1.4.0` and
  `ai-dynamo-runtime==1.4.0` wheels. The `ai-dynamo` wheel contains
  `dynamo.frontend.__main__` and `dynamo.sglang.__main__`, so the module name is
  real when the package is installed. However, the current parent-materialized
  `dynamo.frontend` argv uses proxy-style flags (`--host`, `--port`,
  `--upstream-url`, and `--model`) rather than the frontend parser's actual
  flags (`--http-host`, `--http-port`, `--model-name`,
  `--discovery-backend`, `--request-plane`, and related Dynamo options). The
  parent runner now rejects unsupported `dynamo.frontend` flags before `Popen`
  with `reason: unsupported_argv_flag`; this prevents a package install from
  being misread as a complete topology.
- The current declared config now uses a schema-backed Dynamo topology instead
  of proxy-style argv: `mode: local_frontend_worker`, `package: ai-dynamo`,
  `discovery_backend: file`, `request_plane: tcp`, `namespace: glm52`,
  frontend module `dynamo.frontend`, and worker module `dynamo.sglang`.
  Materialization derives the frontend command with `--http-host`,
  `--http-port`, `--model-name`, `--discovery-backend`, `--request-plane`,
  `--namespace`, and `--dyn-chat-processor sglang`; it also records the worker
  command for `python -m dynamo.sglang` with endpoint
  `dyn://glm52.backend.generate` and endpoint types `chat,completions`.
- Fresh current-config blocker run
  `glm52-serving-results/glm52-inference-dynamo-topology-20260817T164445Z/`
  exited `2` and wrote `components/dynamo/environment.json` with
  `status: missing_prerequisite`, `reason: missing_module`,
  `module: dynamo.frontend`, `popen_attempted: false`, endpoint
  `http://127.0.0.1:19001/v1`, and upstream
  `http://127.0.0.1:19000/v1`. This is fail-fast blocker evidence only. It
  proves the parent runner reaches the real topology contract and stops before
  `Popen` when `ai-dynamo` is not installed in the host-control Python
  environment; it is historical blocker evidence, not live Dynamo inference
  evidence.
- Follow-up current-state update:
  `glm52-serving-results/prepare-dynamo-venv-20260817T165525Z/components/dynamo/dynamo-venv.json`
  records a prepared host-control Dynamo venv with `ai-dynamo==1.4.0`,
  `ai-dynamo-runtime==1.4.0`, and successful import probes for
  `dynamo.frontend` and `dynamo.sglang`. Parent run
  `glm52-serving-results/glm52-inference-dynamo-venv-20260817T165732Z/`
  records `components/dynamo/environment.json` with `status: ok`,
  `reason: python_module_importable`, and `popen_attempted: false`, so the
  missing-module prerequisite is no longer the active blocker. That same parent
  run still did not reach Dynamo launch because its owned SGLang child
  advertised `/v1/models` on port `19000` but timed out on the real generation
  probe after `300s` with a detokenizer health failure. This is parent-run
  SGLang blocker evidence before Dynamo frontend/worker launch, not a Dynamo
  or Responses live pass.
- The repeat runner now has opt-in GPU-free wait gates:

```sh
MONARCH_ROOTFS_CACHE_ROOT=/data01/builder/opt_draccus/monarch-rootfs-cache \
scripts/run_glm52_sglang_runtime.sh repeat \
  --declared-spec .scratch/glm52-local-serving/tmp/sglang-local-disable-overlap-schedule.yaml \
  --local-environment .scratch/glm52-local-serving/config/local-environment.vartmp-rootfs.yaml \
  --cycles 1 \
  --wait-for-gpu-free-seconds 300 \
  --gpu-free-stable-seconds 60
```

Those gates reduce the race between manual GPU polling and launcher preflight,
but they do not reserve GPUs and are not completion evidence. The strict launch
preflight still runs immediately before process start and fails loudly on any
non-owned occupancy. Native SGLang generation now has clean repeatability
evidence, but the end-to-end Dynamo, Responses, Harbor, EvalPlus, and
published-conformance gates remain blocked until they have their own live
artifacts.
