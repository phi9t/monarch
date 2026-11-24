# Inventory Monarch release work

Type: task
Status: ready-for-human
Blocked by:
Parent: ../spec.md

## Requirements

- Establish the trusted upstream boundary; inventory branches, worktrees,
  gitlinks, generated evidence, and publication objects.
- Assign every local item a durable disposition and verify gitlink provenance,
  license, and public availability.

## Verification

- Independent review confirms exhaustive coverage without changing existing
  work or refs.

## Comments

### 2026-09-07 — local inventory completed and repair pending review

Gated-path classification: release provenance, publication history, a gitlink,
generated evidence, and five worktrees exceed the short path. `ask-matt` is not
available in this runtime; the gated criteria were applied directly. Authority
was limited to tracker-file edits and read-only verification: no Git/ref/remote
mutation, deletion, publication, or ledger edit occurred.

[Local estate and provenance inventory](../research/local-estate-and-provenance-2026-09-07.md)
records a dated live-remote verification receipt, every local branch, all
ref/worktree/dirty/generated/publication classes, exact gitlink public/MIT
proof, ledger drift, and the recovery-manifest admission gate. The report
verified local counts with `git for-each-ref`,
`git worktree list --porcelain`, per-worktree `git status --porcelain=v1 -uall`,
`git ls-files -s`, `git fsck`, reflog counting, and `jq` ledger queries;
the dated receipt separately records live remote checks and the exact-SHA
temporary-bare gitlink fetch.

Rulings: the JSON ledger is stale/non-authoritative for current candidate
decisions and must be canonically regenerated, not hand-edited; publication
exclusion does not authorize deletion. Remaining human decisions are candidate
reconstruction against public upstream, integration/cleanup of the named local
branches, canonical-ledger regeneration plus independent comparison, and
sensitive-metadata/receipt/publication approval. The configured upstream has a
usable push destination, violating the fetch-only remote contract; its removal
is a human-owned, separately authorized blocker. The ticket remains
`ready-for-human`: independent Standards and Spec reviews are green, and the
ticket awaits human acceptance. A later `scripts/run` verifier was
non-observational for the host estate: bubblewrap bind mounts projected a
different generated/cache namespace without establishing or mutating host state.
No deletion or Git/ref/remote mutation occurred. The durable report and manifest
therefore use a host-side read-only Python refresh: `Path.rglob('*')` plus
`is_file()`, class-relative POSIX paths in Python string order, NUL-final
content records `<file SHA-256><two spaces><relative path>` or metadata records
`f<tab><decimal size><tab><relative path>`; `.scratch` excludes only the
manifest. Generated-class fingerprints are point-in-time recovery identities,
not a claim that mutable classes remain current.
