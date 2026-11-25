# Add GLM-5.3-Flash Multimodal Smoke Fixture

Type: task
Status: ready-for-agent
Blocked by: 01
Parent: `.scratch/glm53-flash-local-serving/spec.md`

## Requirements

- Add a small, license-clear image fixture for the GLM-5.3-Flash multimodal
  smoke profile.
- Record fixture provenance, license, path, byte size, and SHA256 digest in a
  tracked metadata file.
- Define the Chat Completions content-block request shape for one image and a
  short text instruction.
- Ensure the fixture can be loaded inside the verifier execution domain without
  network access.
- Add validation that the backend exposes a multimodal processor before sending
  the request.
- Add verifier checks that prove the image request path was used, not only that
  a text-only prompt returned content.
- Keep the multimodal smoke profile separate from the first text and tool
  compatibility tracer bullet.
- Mark video and file inputs as deferred profiles unless their prerequisites,
  fixtures, and processor evidence are declared.

## Exclusions

- Do not add video or file-input smoke coverage in this ticket.
- Do not download fixture assets at verifier runtime.
- Do not use an image whose license/provenance is unclear.
- Do not require `torchcodec` until a video profile is introduced.

## Acceptance Criteria

- The fixture metadata is tracked and includes a stable digest.
- Tests cover request serialization for image content blocks.
- The multimodal smoke fails loudly when the fixture is missing, the digest does
  not match, the backend lacks a processor, or the response cannot be tied to
  the image prompt.
- The tracked metadata records that video/file profiles are unsupported in the
  first acceptance path, not silently untested.

## Verification Plan

```sh
scripts/run python -m pytest python/tests/test_glm53_flash_serving_verifier.py -q
scripts/run python -m pytest python/tests/test_glm52_serving_verifier.py -q
```

Add GLM-5.3-Flash multimodal fixture and verifier tests before implementation.
Keep the GLM-5.2 verifier command as regression coverage when shared verifier
code changes.
