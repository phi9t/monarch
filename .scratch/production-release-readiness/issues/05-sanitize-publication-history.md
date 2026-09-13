# Sanitize Monarch publication history

Type: task
Status: ready-for-agent
Blocked by: 01
Parent: ../spec.md

## Requirements

- Reconstruct unsafe local commits while preserving public upstream authors.
- Resolve path, network, company metadata, identity, gitlink, generated
  artifact, binary, license, and proprietary findings.

## Verification

- Pinned scanners and independent human review find no unresolved blocker.
- The path/network/machine-identity scan is `scripts/release_desensitizer.py`
  (gateway wrapper `scripts/run_release_desensitizer.sh`). It redacts absolute
  home/workspace paths, login names, routable and private IPv4, hardware MAC
  addresses, GPU serial UUIDs, and non-allowlisted emails to deterministic
  placeholders. `--check` (default) is fail-loud and gates a release; `--apply`
  rewrites in place and is idempotent. Unit coverage lives in
  `python/tests/test_release_desensitizer.py`.

## Comments
