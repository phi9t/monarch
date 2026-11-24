# Harden GLM-5.3-Flash Checkpoint Storage Preflight

Type: task
Status: ready-for-agent
Blocked by: 01
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add a checkpoint storage preflight for large local model pulls that rejects
  sandbox-private destinations unless the run explicitly records a persistent
  host path and bind mount.
- Require the GLM-5.3-Flash checkpoint path to survive the process that created
  it. A one-shot `scripts/run` private `/tmp` path is invalid unless it is
  backed by a host bind mount.
- Record filesystem capacity before download, expected checkpoint size, actual
  top-level file count, safetensor shard count, index digest, and Hugging Face
  repo metadata in a structured artifact.
- Mark Hugging Face transport retries as resumable only when the destination
  path is persistent and the local metadata can be rechecked after retry.
- Add stable failure classes for `checkpoint_storage_not_persistent`,
  `checkpoint_capacity_insufficient`, `checkpoint_manifest_mismatch`, and
  `checkpoint_resume_failed`.

## Exclusions

- Do not move large checkpoint files into the git checkout.
- Do not store checkpoint artifacts under the bwrap rootfs unless the path is
  explicitly host-backed and capacity-checked.
- Do not treat a successful download inside a one-shot sandbox as durable
  evidence unless a second process verifies the same path.

## Acceptance Criteria

- A preflight run against a private rootfs `/tmp` path fails before launch with
  `checkpoint_storage_not_persistent`.
- A preflight run against a host path such as
  `/tmp/glm53-flash-store/checkpoint` records the bind-mount source and passes
  persistence verification from a second process.
- The verification artifact records the expected 72 top-level repo files, 62
  safetensor shards, safetensor byte total, and
  `model.safetensors.index.json` SHA256 digest.
- Partial Hugging Face download state is classified as resumable only when the
  destination path persists across a fresh process.
- The preflight refuses to proceed when available capacity is below the
  configured model-size budget plus working-space margin.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_checkpoint_preflight.py -q
scripts/run python -m pytest python/tests/test_glm52_inference_runtime.py -q
```

Add tests before implementation. Use temporary directories and fake manifests
for unit coverage; live checkpoint verification remains a final acceptance
artifact and must not redownload the model during the unit suite.
