# Mission: Extend and maintain Monarch's hermetic bwrap rootfs confidently

## Why
You own the Linux-local execution path for Monarch on this host: the bwrap rootfs,
the `scripts/run` gateway, and the 8-GPU capacity verifier. You will keep changing
it — adding tools, bumping pins, writing new verifiers — and every change risks
breaking hermeticity or reproducibility in ways that only surface later (a drifted
loader, an unstamped rootfs, a leaked host env var). The goal is to make those
changes without fear, because you understand which invariants must hold and where
they are enforced.

## Success looks like
- You can add or bump a tool in the rootfs (e.g. a new pinned binary) knowing
  exactly which files to touch (`contract.env`, `build_rootfs.sh`) and why the
  recipe digest must change with them.
- You can explain, from memory, why a bare-host `cargo` fails but `scripts/run
  cargo` works, and trace it to the PyO3/libpython link and the cleared env.
- You can predict whether a given edit forces a rootfs rebuild, and verify it via
  the stamped `/etc/monarch-rootfs-contract` and `monarch_rootfs_contract_current`.
- You can write a new capacity verifier that follows the Local Run Ladder and
  emits machine-readable Contract Artifacts, without weakening hermeticity.
- You can classify a verifier failure as real vs. Suite-Ordering Fragility using
  the isolation-rerun evidence, not guesswork.

## Constraints
- Source-faithful only: every claim traces to a file:line in this checkout, never
  to generic bwrap/docker lore.
- Repo-local: this workspace lives under `.agents/teach/` and is git-ignored.
- Respect the clean-tree discipline; teaching artifacts must not dirty the repo.
- Lessons are text-based Emacs org-mode (`.org`), headings and bullets, no
  tables — matching your recorded preference for lesson artifacts.

## Out of scope
- Meta-internal Buck/fbcode tooling (`arc`, `buck2`) — not runnable in OSS locally.
- Remote/MAST orchestration and multi-host distribution.
- Rewriting the rootfs to a non-docker/non-bwrap mechanism (nspawn, podman, etc.).
- macOS and installed-wheel execution domains.
