# Issue 02: Prepare SGLang Venv and Model Cache

Status: ready-for-agent

Type: task

Blocked by: 01

Spec: `.scratch/glm52-rootfs-sglang-hardening/spec.md`

Plan: `.scratch/glm52-rootfs-sglang-hardening/implementation-plan.md`

## Outcome

Add explicit preparation commands for the rootfs-managed SGLang venv and
rootfs-managed GLM-5.2 model cache. Launch must later refuse to start unless
these preparation records are present and valid.

## Requirements

- SGLang venv must live at `/cache/glm52/venvs/sglang`.
- SGLang package installation must run inside the governed bwrap rootfs.
- The preparation record must prove the Python executable, package set,
  `--served-model-name` help support, rootfs recipe digest, and bwrap plan.
- Model preparation must run with `HF_HOME=/cache/glm52/hf-home`.
- Model preparation must validate `model.safetensors.index.json` and required
  shard files.
- Launch must fail before server startup if preparation evidence is absent or
  stale.

## Exclusions

- Do not launch SGLang.
- Do not implement repeatability cycles.
- Do not use host Python package checks as success evidence.

## Verification

Run:

```sh
scripts/run python -m pytest python/tests/test_glm52_sglang_runtime.py -q
bash -n scripts/run_glm52_sglang_runtime.sh
```

When live prerequisites exist, also run:

```sh
scripts/run_glm52_sglang_runtime.sh prepare-venv \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml

scripts/run_glm52_sglang_runtime.sh prepare-model \
  --declared .scratch/glm52-local-serving/config/sglang-local.yaml \
  --local-env .scratch/glm52-local-serving/config/local-environment.example.yaml
```

## Comments
