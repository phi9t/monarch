# SWE-bench Image Source Check

Checked: 2026-08-16

## Purpose

Record the source of SWE-bench Verified evaluation images before wiring the
GLM-5.2 benchmark verifier to any SWE-bench smoke or conformance run. This note
records the first minimal smoke instance selected from the materialized dataset
cache and the registry digest resolved for that row image.

## Primary Sources

- SWE-bench README, raw `main`, lines 67-72: default evaluation images are
  pulled from DockerHub namespace `swebench`; passing `--namespace ''` uses
  locally built images instead.
- SWE-bench harness `swebench/harness/utils.py`, lines 235-247: `TestSpec` is
  built from the dataset row and carries that row's `image` field.
- SWE-bench harness `swebench/harness/run_evaluation.py`, lines 79-95 and
  117: the evaluator pulls or creates containers from `test_spec.image`.
- HuggingFace dataset API for `SWE-bench/SWE-bench_Verified`: live dataset SHA
  is `78f471bf655a3137b2e8a75af1501690ec009ec3`.
- Materialized dataset parquet from
  `.scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-main-20260816T115900Z/benchmarks/datasets/swe-bench-verified/data/test-00000-of-00001.parquet`.
- Docker registry metadata for
  `swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest`.

## Findings

- DockerHub namespace `swebench` is the upstream default for official
  evaluation images.
- The concrete image used for an instance is not a verifier-level constant. It
  comes from the materialized SWE-bench dataset row via `TestSpec.image`.
- `run_evaluation.py` consumes `test_spec.image` when pulling or creating the
  test container, so any digest pin must be derived after choosing the dataset
  revision and smoke instance rows.
- The checked-in value `4e6126978a16bdfebc6538db8f28cacc2c8b77dc` is suitable
  as a SWE-bench harness git commit pin. It is not proven to be a HuggingFace
  dataset revision pin, and it differs from the current live HF dataset SHA
  `78f471bf655a3137b2e8a75af1501690ec009ec3`.
- The pinned dataset revision materializes 500 rows. The first row is
  `astropy__astropy-12907`, with `repo=astropy/astropy`,
  `version=4.3`, `problem_statement` length 1246, `test_patch` length 1415,
  and row image
  `swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest`.
- Docker `buildx imagetools inspect` resolved the row image tag to OCI index
  digest `sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88`.
  The linux/amd64 manifest under that index is
  `sha256:a39a5c3244a9be4af79d7bb669cae25259452b4f9945561ed433efd0840b85b7`.

## Decision

Use `astropy__astropy-12907` as the first minimal SWE-bench Verified smoke
instance and pin its dataset row image to
`docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907@sha256:483f26c8c89a879560ed3f2e47e470343a5a0b8bf5e08d8fe3ec7eac9201df88`.
This is smoke metadata only. It does not assert SWE-bench Verified published
conformance, and `conformance.claim` remains `none`.

## Verification Commands

```sh
curl -fsSL https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/README.md \
  | sed -n '67,72p'

curl -fsSL https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/swebench/harness/utils.py \
  | sed -n '235,247p'

curl -fsSL https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/swebench/harness/run_evaluation.py \
  | sed -n '79,95p;117p'

python - <<'PY'
from huggingface_hub import HfApi
print(HfApi().dataset_info("SWE-bench/SWE-bench_Verified").sha)
PY

scripts/run python - <<'PY'
from pathlib import Path
import pyarrow.parquet as pq

parquet = Path(".scratch/glm52-local-serving/tmp/prepare-swebench-hf-revision-main-20260816T115900Z/benchmarks/datasets/swe-bench-verified/data/test-00000-of-00001.parquet")
table = pq.read_table(parquet)
row = table.slice(0, 1).to_pylist()[0]
print(table.num_rows)
print(row["instance_id"])
print(row["repo"])
print(row["version"])
print(row["image"])
print(len(row["problem_statement"]))
print(len(row["test_patch"]))
PY

docker manifest inspect \
  swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest

docker buildx imagetools inspect \
  swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest
```

## Next Required Slice

Wire the selected smoke instance into a real Harbor/SWE-bench execution path
that can create the official container, run the instance through the Responses
adapter, and emit Contract Artifacts. Keep published conformance claims blocked
until primary-source score conditions are pinned and matched.
