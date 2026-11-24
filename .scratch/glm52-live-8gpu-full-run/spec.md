# GLM-5.2 Live 8-GPU Full Run Spec

Status: ready-for-agent

Route: gated

Owner fallback: `$ask-matt` was requested for this effort, but it is not
available as a callable model skill in this session. Per
`docs/agents/skill-orchestration.md`, this tracker applies the Matt route and
combined completion criteria directly with the available Superpowers planning
supporting skill. Do not later claim that `ask-matt`, `to-spec`, or
`to-tickets` was invoked unless a harness actually invoked it.

## Goal

Execute the live local GLM-5.2 parent workload on exactly eight local GPUs and
produce benchmark-ready Contract Artifacts for this chain:

```text
Ginkgo parent run -> Insula bwrap rootfs -> SGLang GLM-5.2 GPU backend -> Dynamo -> Responses adapter -> verifiers/benchmarks
```

This effort is live operations and evidence collection, not a new
implementation project. The implementation contract is
`ginkgo/docs/glm52-gpu-workload.md`; the portable parent config is
`ginkgo/configs/inference-glm52.yaml`.

## Source Material

- `CONSTITUTION.md`
- `AGENTS.md`
- `CONTEXT.md`
- `docs/adr/0001-bwrap-rootfs-for-local-runs.md`
- `docs/adr/0002-python-isolation-reruns-for-local-run-classification.md`
- `docs/agents/agentic-engineering.md`
- `docs/agents/skill-orchestration.md`
- `docs/agents/issue-tracker.md`
- `ginkgo/docs/glm52-gpu-workload.md`
- `ginkgo/docs/evidence-boundary.md`
- `ginkgo/docs/verification-ladder.md`
- `.scratch/glm52-end-to-end-inference/spec.md`
- `.scratch/glm52-end-to-end-inference/issues/05-repeatability-runner.md`
- `.scratch/glm52-local-serving/spec.md`
- `.scratch/glm52-local-serving/completion-audit-2026-08-16.md`

## Route Classification

This is a gated path because it touches production-like local inference,
distributed GPU scheduling, rootfs and bwrap boundaries, strict port ownership,
process supervision, teardown, and benchmark evidence. It is not short-path
work, even if no code changes are required.

Durable authority is limited to this tracker and the existing Ginkgo workload
docs. Operators may run the declared commands and append evidence to the
tickets. Any change to schema, topology, process ownership, ports, fallback
policy, or benchmark evidence semantics requires a separate implementation
ticket and review before the live run resumes.

## Live Acceptance Criteria

A run is complete only when all criteria below are met from the same parent run
or from its three recorded parent cycles:

- The materialized parent config resolves host rootfs, cache, temp, results,
  shared-memory, and GPU refs through `ginkgo/local-env/*`, not through
  portable absolute host paths.
- All component ports are concrete before launch, are allocated from
  `19000-19200`, and are not `8000`, `8080`, or `18080`.
- The SGLang backend launches through Insula-owned rootfs execution on
  `CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7`, tensor parallel size `8`, bf16, model
  id `zai-org/GLM-5.2`, and the exact prepared model snapshot recorded in
  `glm52-serving-results/prepare-model/model-cache.json`.
- SGLang `/v1/models` reports `zai-org/GLM-5.2` and a real chat or generation
  probe returns generated text. `/v1/models` alone is not completion evidence.
- Dynamo launches in the declared `local_frontend_worker` topology with both
  `dynamo.frontend` and `dynamo.sglang` import/help contracts proven by the
  dependency record, then returns real GLM-backed chat output.
- The Responses adapter launches only after the upstream GLM-backed path is
  proven, binds to a run-owned port, and returns model listing, non-streaming
  Responses output, streaming Responses output, and tool-call behavior.
- Three parent cycles complete by default, each with a unique run id and fresh
  concrete ports.
- Teardown runs in reverse order, proves every owned port is closed, proves no
  owned process group remains, and records a GPU process audit for devices
  `0,1,2,3,4,5,6,7`.
- `parent-manifest.json` passes
  `scripts/glm52_inference_runtime.py audit-parent-manifest` and classifies
  the result as benchmark-ready.
- Benchmark smoke, calibration, or conformance commands are run only with the
  completed parent manifest and completed Responses base URL from the same
  parent run.

## Non-Goals

- Do not kill, reuse, or mask non-owned GPU processes.
- Do not fall back to CPU, fewer GPUs, a fixture backend, a fake Responses
  route, default ports, or any endpoint outside the materialized parent config.
- Do not classify Qwen smoke, `/v1/models` alone, unit tests, fake endpoints,
  or stale run directories as GLM completion evidence.
- Do not alter Dynamo into an HTTP proxy contract unless a separate reviewed
  implementation ticket intentionally changes the executable contract.
- Do not run Harbor, Terminal-Bench, SWE-bench, HumanEval, MBPP, EvalPlus, or
  published conformance as GLM-backed evidence without the benchmark-ready
  parent manifest gate.

## Known Blocker Signatures

Prior blocker artifacts are useful for triage, but they do not complete this
spec.

- `generate probe timed out after 300s`
- `Health check failed. Server couldn't get a response from detokenizer for last 20 seconds`
- SGLang scheduler exceptions during `/generate`
- Non-owned GPU occupancy, including prior GPU 4 occupancy by pid `2672717`
  (`/opt/tiger/b200/bin/python`, about `12898` MiB) and later
  `VLLM::Worker_TP*` workers
- Default port probes on `8000` or `8080` reaching no Chat endpoint or a SearXNG
  service

When a known signature recurs, write fresh blocker evidence and stop further
cycles. Do not silently switch flags, devices, ports, or topology inside the
same ticket.

## Operator Preflight

Run preflight from the isolated GLM worktree unless an operator intentionally
uses a newer reviewed branch:

```sh
pwd
git status --short
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py python/tests/test_rootfs_verifier.py scripts/rootfs/tests/test_execution_contract.py scripts/rootfs/tests/test_entrypoint_inventory.py -q
scripts/run python scripts/glm52_inference_runtime.py prepare-dynamo-venv --declared ginkgo/configs/inference-glm52.yaml --local-env <local-env.yaml> --run-id prepare-dynamo-venv-<UTC>
scripts/run python scripts/glm52_inference_runtime.py materialize --declared ginkgo/configs/inference-glm52.yaml --local-env <local-env.yaml> --run-id glm52-live-preflight-<UTC> --output glm52-serving-results/glm52-live-preflight-<UTC>/materialized.yaml
scripts/run python scripts/glm52_inference_runtime.py validate --materialized-config glm52-serving-results/glm52-live-preflight-<UTC>/materialized.yaml
```

`<local-env.yaml>` must be a real local-environment file derived from
`ginkgo/local-env/template.yaml`. It must resolve repo, cache, temp, run,
results, rootfs, shared-memory, and GPU devices without changing
`ginkgo/configs/inference-glm52.yaml`.

Host-resource checks that are explicitly outside the Linux-local rootfs command
domain may use host tools directly:

```sh
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader
ss -H -ltn 'sport >= :19000 and sport <= :19200'
```

The launch ticket owns the final strict preflight immediately before process
spawn. A clean earlier sample is not a reservation.

## Execution Sequence

1. Refresh SGLang venv and model-cache records only through the governed
   preparation commands if the existing records are missing, stale, or refer to
   the wrong rootfs/cache path.
2. Prepare and verify the Dynamo venv dependency record.
3. Materialize the parent config and inspect concrete ports, component URLs,
   launch argv, dependency records, and Insula plan refs.
4. Run the three-cycle parent repeatability command:

   ```sh
   scripts/run python scripts/glm52_inference_runtime.py repeatability --declared ginkgo/configs/inference-glm52.yaml --local-env <local-env.yaml> --run-id glm52-live-8gpu-<UTC> --cycles 3
   ```

5. If the run fails, stop the campaign, preserve the failed result directory,
   audit teardown artifacts, and update the relevant ticket with the exact
   blocker signature.
6. If the run succeeds, audit the parent manifest:

   ```sh
   scripts/run python scripts/glm52_inference_runtime.py audit-parent-manifest --manifest glm52-serving-results/glm52-live-8gpu-<UTC>/parent-manifest.json
   ```

7. Run benchmark smoke only through the benchmark verifier with
   `--parent-manifest` pointing at the audited manifest. Calibration or
   conformance remains blocked until smoke evidence is green and the benchmark
   ticket is updated.

## Evidence Artifact Contract

The final evidence bundle must include, at minimum:

- materialized parent config;
- local-env digest or copied local-env summary with secret-free host paths;
- SGLang venv record and model-cache record;
- Dynamo venv dependency record;
- Insula bwrap, mount, env, cwd, GPU, and argv plan records;
- SGLang process record, logs, `/v1/models`, and generated output payload;
- Dynamo frontend and worker process records, logs, model listing, and chat
  output payload;
- Responses adapter process record, logs, model listing, non-stream output,
  streaming output, and tool-call output;
- parent `summary.json`;
- parent `parent-manifest.json`;
- teardown summaries, port closure proof, orphan scan, and GPU process audit;
- benchmark gate output, if any benchmark command was run.

Each artifact must be classified as blocker, readiness, completion, or
benchmark-ready. A blocker directory may be kept and cited, but it must not be
renamed or summarized as successful evidence.

## Ticket Graph

- `issues/01-clean-8gpu-preflight.md`: prove the host and declared config are
  ready for one live attempt.
- `issues/02-parent-repeatability-live-run.md`: run the three-cycle parent
  workload and collect same-run completion artifacts.
- `issues/03-blocker-triage-and-one-variable-retry.md`: handle a failed live
  attempt without uncontrolled flag churn.
- `issues/04-parent-manifest-audit.md`: audit and classify the successful parent
  manifest.
- `issues/05-benchmark-gate-smoke.md`: run only benchmark smoke against the
  audited GLM-backed Responses URL.

Tickets are intentionally sequential. Parallel work is allowed only for
read-only artifact review or independent blocker diagnosis in separate
contexts; no two agents may share a mutable live-run checkout or live GPU
process ownership.

## Comments

2026-08-18:

- This spec was created after implementation commit `c72df8e9c Add GLM52 parent
  manifest gate` in the isolated worktree
  `.worktrees/glm52-gpu-workload`.
- The root checkout remains dirty and is not the live-run authority for this
  tracker unless a human explicitly switches the execution branch.
- Current blocker history still points at SGLang generation health and
  opportunistic GPU occupancy as the first live risks.
