# Monarch Production Release Readiness

Status: approved
Path: gated
Parent: ultron:.scratch/production-release-readiness/issues/03-qualify-monarch.md

## Outcome

Produce a sanitized `ultron/mainline` candidate that retains Monarch's strong
Insula and `scripts/run` boundary, independently implements Vaso v1, and proves
native control-plane and B200 behavior from a clean checkout.

The Ultron parent effort keeps rootfs implementation in `needs-info` until
Vaso's linked `02-freeze-rootfs-spec-v1` ticket resolves and its digest is
recorded here.

## Current state

Monarch is closest to the target: image/tool inputs are digest-pinned, launch
plans are schema-backed, environment and CUDA projection are explicit, and
rootfs tests are broad. Remaining work is conformance proof, clean-checkout
reproducibility, gitlink verification, local-history disposition, and complete
publication sanitization.

## Rootfs adaptation

Keep `scripts/run` as the sole public execution gateway and Insula as the native
planner. Prove complete recipe/content identity, read-only selection,
repo-local writable state, environment filtering, explicit network behavior,
B200 projection, and sanitized receipts. The implementation remains owned by
Monarch and imports nothing from Vaso or Ultron.

## Approved test seam

Use Insula plans, rootfs manifests, `scripts/run` results, native Python/Rust
suite reports, and B200 control-plane receipts. Clean checkout and negative
behavior are part of the public contract.

Before GPU execution, a human approves the exact command, immutable fixtures,
GPU count/topology, steps or duration, correctness/tolerance thresholds, any
performance claim, negative cases, timeout/resource budget, receipt schema,
and signing verification. The child receipt is signed and binds the approved
contract to the exact commit and rootfs identity.

## Acceptance criteria

- Monarch independently passes the pinned Vaso v1 behavior contract.
- The relevant Python, Rust, build, and control-plane suites pass in bwrap.
- The human-approved exact B200 control-plane contract produces an
  independently verified sanitized signed receipt.
- Gitlinks, licenses, local work, history, and metadata are fully dispositioned.
- The exact candidate passes independent review and desensitization.

## Out of scope

- Replacing Insula, publishing packages/containers, qualifying other hardware,
  or depending on Vaso or Ultron.

## Authority

Approved tickets may change local files and test in repo-local worktrees. Git
and GitHub mutations, deletion, and merges require separate authorization.
