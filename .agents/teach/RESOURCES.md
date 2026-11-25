# Hermetic bwrap rootfs — Resources

## Knowledge

### Primary (in-repo — highest trust, they *are* the behavior)
- `scripts/rootfs/execution_contract.sh` — the guard library: recipe digest,
  rootfs validity, domain classification, the canonical error. Use for: any
  question about "is this a valid rootfs / does it need rebuild / why did the
  guard fire."
- `scripts/rootfs/enter_rootfs.sh` — the bwrap invocation. Use for: what is
  writable, what env crosses the boundary, GPU + host-driver binds, LD paths.
- `scripts/rootfs/build_rootfs.sh` — the image recipe + atomic export. Use for:
  what tools are in the rootfs, how CUDA_HOME is synthesized, how pins are
  verified at build time.
- `scripts/rootfs/contract.env` — the reviewed pins. Use for: bumping a tool.
- `scripts/rootfs/execution-domains.toml` + `audit_entrypoints.py` — the domain
  inventory and its audit. Use for: deciding whether a new script must run under
  `scripts/run`.
- `AGENTS.md` (Build & Commands, Testing) — repo-level policy on the gateway,
  the Local Run Ladder, and Contract Artifacts.
- `.agents/skills/run-monarch-single-machine/SKILL.md` — the canonical agent
  procedure for running Monarch on one host through the rootfs.

### External (only for background mechanics; never override the repo)
- bubblewrap `bwrap(1)` man page — semantics of `--ro-bind`, `--unshare-all`,
  `--clearenv`, `--dev-bind`, tmpfs-over-readonly-root. Use for: understanding
  what a bwrap flag guarantees. Read in a terminal: `man bwrap`.
- `docker export` docs — how a flattened rootfs differs from a layered image
  (empty `/etc/resolv.conf`, no init). Use for: why DNS is bound in.
- PyO3 "Building and distribution" — why the extension links libpython and needs
  an interpreter present at link time. Use for: the `cargo` must-run-in-venv rule.
- `uv` docs (`uv venv`, `--system-site-packages`, `UV_PROJECT_ENVIRONMENT`).

## Wisdom (Communities)
- Not applicable for now: this is a repo-internal system on a single host. The
  authoritative "community" is the reviewed contract + PR review described in
  `CONTRIBUTING.md`. Revisit if you ever upstream rootfs changes.

## Gaps
- No external doc will ever describe *this* rootfs; the repo files are the only
  source. Treat any parametric bwrap/docker recollection as unverified until
  checked against the scripts.
