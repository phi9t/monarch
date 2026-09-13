# SWE-bench Harbor Dataset Resolution

Type: task
Status: ready-for-review
Blocked by:

## Objective

Make the SWE-bench Verified smoke use a Harbor-resolvable dataset source, or
replace the Harbor path with a clearly documented local SWE-bench evaluator path
for the pinned smoke instance.

## Context

The latest run `benchmark-e2e-swe-bench-verified-streaming-20260822T031816Z`
failed before trial execution:

```text
ValueError: Dataset swe-bench-verified not found
```

The smoke config currently pins instance `astropy__astropy-12907` and its
official digest-pinned image metadata. The result is explicitly non-comparable
to published SWE-bench Verified scores.

## Requirements

- Inspect Harbor 0.21.0 dataset registry, package dataset, and local dataset
  modes.
- Determine the correct representation for the pinned SWE-bench Verified smoke:
  Harbor registry dataset, Harbor local dataset, Harbor package dataset, or
  direct SWE-bench evaluator.
- Add a preflight that fails before Harbor launch with a precise message if the
  configured dataset cannot be resolved.
- Preserve the pinned smoke instance and digest-pinned image unless a
  primary-source review selects a better smoke instance.
- Capture generated local dataset files and provenance as contract artifacts if
  local/package mode is used.
- Keep the result labelled as smoke evidence and non-comparable to published
  SWE-bench Verified.

## Files

- Modify if needed: `.scratch/glm52-local-serving/harbor/configs/swe-bench-verified-smoke.yaml`
- Modify if needed: `.scratch/glm52-local-serving/harbor/datasets/swe-bench-verified.lock.yaml`
- Modify if needed: `scripts/glm52_benchmark_verifier.py`
- Test: `python/tests/test_glm52_benchmark_verifier.py`
- Update: `.scratch/glm52-local-serving/issues/09-harbor-host-bootstrap.md`

## Exclusions

- Do not run a full SWE-bench Verified campaign.
- Do not claim leaderboard or published-score comparability.
- Do not remove digest pinning from official row images.
- Do not mount the host Docker socket into a model-controlled container.

## Verification

Run focused tests after code changes:

```sh
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py \
  -q
```

Then rerun the one-instance smoke to the first model call or to a task-specific
harness failure:

```sh
PATH=.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH \
  python scripts/glm52_benchmark_verifier.py smoke \
    --suite swe-bench-verified \
    --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
    --execution-backend harbor_local_docker \
    --responses-base-url http://127.0.0.1:18081/v1 \
    --run-id benchmark-e2e-swe-bench-verified-dataset-<timestamp>
```

## Done When

- The SWE-bench smoke no longer fails with `Dataset swe-bench-verified not
  found`.
- Dataset provenance is recorded in the run artifacts.
- Any unresolved blocker is a task-specific harness or model-path issue, not a
  Harbor dataset-name ambiguity.

## Resolution

### 2026-08-23 local Harbor task materialization

Harbor 0.21.0 treats a bare dataset `name: swe-bench-verified` as a default
registry lookup, and that registry does not contain this dataset. The verifier
now represents the pinned SWE-bench Verified smoke as explicit local Harbor
tasks instead of an opaque dataset entry:

- `datasets: []`
- `tasks: [{path: <harbor-raw>/swe-bench-verified-tasks/astropy__astropy-12907}]`
- generated task files include `instruction.md`, `environment/`,
  `tests/test.sh`, and `task.toml`
- `task.toml` records the pinned dataset revision, pinned harness revision,
  row image, digest-pinned image, adapter, and non-comparable smoke status

Verification:

```text
scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_harbor_job_config_uses_local_task_not_registry_dataset \
  python/tests/test_glm52_benchmark_verifier.py::test_swe_bench_smoke_invokes_real_harbor_run_config -q
# 2 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_benchmark_verifier.py -k harbor -q
# 21 passed, 152 deselected

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider \
  python/tests/test_glm52_harbor_agent.py python/tests/test_glm52_benchmark_verifier.py -q
# 185 passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m py_compile \
  scripts/glm52_harbor_agent.py scripts/glm52_benchmark_verifier.py \
  python/tests/test_glm52_harbor_agent.py python/tests/test_glm52_benchmark_verifier.py
# passed

scripts/run env PYTHONDONTWRITEBYTECODE=1 python -m pyright \
  scripts/glm52_harbor_agent.py scripts/glm52_benchmark_verifier.py
# 0 errors

git diff --check
# passed

PATH=.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH PYTHONPATH=$PWD \
  .scratch/glm52-local-serving/tmp/harbor-venv/bin/python - <<'PY'
  ...
  JobConfig.model_validate(...)
  Task.is_valid_dir(...)
  PY
# job_tasks 1
# valid_with_verifier True
# valid_without_verifier True
```

Host-control smoke rerun:

```text
PATH=.scratch/glm52-local-serving/tmp/harbor-venv/bin:$PATH PYTHONPATH=$PWD \
  python3 scripts/glm52_benchmark_verifier.py smoke \
  --suite swe-bench-verified \
  --manifest .scratch/glm52-local-serving/benchmarks/benchmark-manifest.yaml \
  --execution-backend harbor_local_docker \
  --responses-base-url http://127.0.0.1:18081/v1 \
  --run-id benchmark-e2e-swe-bench-verified-dataset-20260823T175003Z
```

Result: `environment_setup_failed` at the explicit Responses `/models`
preflight because `http://127.0.0.1:18081/v1` was not listening. This is no
longer the Harbor `Dataset swe-bench-verified not found` failure.
