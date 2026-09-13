# Decide the de-GLM runtime seam for serving

Type: grilling
Status: open
Blocked by: 01, 12
Parent: ../map.md

## Question

Should the serving plane neutralize its GLM-5.2-specific runtime into a
model-agnostic seam before GLM-5.3-Flash, or stay model-scoped as the current
spec proposes?

Evidence of the coupling:

- The entire serving runtime is GLM-prefixed: `scripts/glm52_sglang_runtime.py`
  (~4170 lines), `glm52_inference_runtime.py`, `glm52_responses_adapter.py`,
  `glm52_serving_verifier.py`, `glm52_deployment.py`.
- Qwen3 already reuses the GLM file: `ginkgo/local_run.py:594` loads
  `scripts/glm52_sglang_runtime.py` as its runtime — the "shared" runtime is a
  GLM filename.
- `ginkgo/insula/compatibility.py` carries a `GLM52_*` host-env allowlist and a
  hard-coded `REPO_MOUNT="/workspace/monarch"`.
- `GinkgoHostControlAdapter` hard-binds `kind=="sglang"` and rejects other kinds.
- `.scratch/glm53-flash-local-serving/spec.md` explicitly prefers a model-scoped
  `glm53_flash_` prefix and defers a shared-runtime extraction until both model
  paths are green.

Decide:

- Whether to (a) extract a model-agnostic SGLang runtime + model registry
  (model → config + backend kind) now, unblocking GLM-5.3 as config not code, or
  (b) proceed model-scoped per the GLM-5.3 spec and extract later.
- Whether a backend-kind abstraction (sglang / vLLM / dynamo / future) is part
  of the same seam or a separate ticket.
- Record the tradeoff (fork cost now vs shared-runtime risk) and flag any
  conflict with the GLM-5.3-Flash spec's stated preference.

This is a serving-plane shape decision; it hangs on the plane seam (ticket 01).
