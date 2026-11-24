# Parent Repeatability Live Run

Type: task
Status: ready-for-agent
Blocked by: 01

## Goal

Run the declared GLM-5.2 parent workload for three live cycles and collect
same-run completion artifacts for SGLang, Dynamo, Responses, and teardown.

## Requirements

- Read `../spec.md` and `01-clean-8gpu-preflight.md` before launching.
- Start only after ticket 01 has fresh clean preflight evidence.
- Use the exact portable declared config:
  `ginkgo/configs/inference-glm52.yaml`.
- Use the exact local-environment file validated in ticket 01.
- Use the default three cycles unless a human explicitly narrows the attempt
  because of a blocker investigation.
- Launch order inside every cycle is SGLang, Dynamo, Responses.
- Teardown order inside every cycle is Responses, Dynamo, SGLang.
- Stop further cycles on the first failed cycle.
- Preserve every run directory under `glm52-serving-results/`.
- Record the parent run id in this ticket before launch.
- If the command exits nonzero, immediately inspect and cite the failed
  `summary.json`, component launch summary, process records, teardown proof,
  port closure proof, orphan scan, and GPU process audit.

## Command

Use a run id with a UTC timestamp:

```sh
scripts/run python scripts/glm52_inference_runtime.py repeatability --declared ginkgo/configs/inference-glm52.yaml --local-env <local-env.yaml> --run-id glm52-live-8gpu-<UTC> --cycles 3
```

## Exclusions

- Do not run benchmark commands from this ticket.
- Do not continue to Dynamo or Responses completion claims if SGLang produces
  only `/v1/models` or times out on generation.
- Do not rerun with new SGLang flags in the same ticket after a failure.
- Do not leave `debug_mode` or keepalive behavior that skips teardown proof.

## Verification Evidence

- Parent repeatability command exits zero.
- `summary.json` reports `ok: true`.
- SGLang evidence includes `/v1/models` reporting `zai-org/GLM-5.2` and a real
  generated text response.
- Dynamo evidence includes real GLM-backed chat output through the declared
  frontend/worker topology.
- Responses evidence includes model listing, non-streaming output, streaming
  output, and tool-call output.
- Three cycles have unique run ids and fresh concrete ports.
- Every cycle has reverse-order teardown evidence, closed owned ports, no owned
  process group residue, and GPU process audit.

## Comments
