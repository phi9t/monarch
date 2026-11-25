# Local estate and provenance inventory

Observed 2026-09-07 UTC. This is a local inventory supplemented by a dated
live-remote and temporary-bare verification receipt. It does not change a ref,
remote, worktree, submodule, or generated artifact.

## Scope and authority

This ticket follows the gated path: it crosses release provenance, publication
history, a gitlink, generated evidence, and five worktrees. `ask-matt` is not
available in this runtime, so the gated-path criteria in
[`docs/agents/agentic-engineering.md`](../../../docs/agents/agentic-engineering.md)
were applied directly. Authority was limited to the two tracker artifacts named
in ticket 01 and read-only Git inspection. In particular, this report does not
authorize a commit, push, merge, ref or remote change, deletion, pruning,
publication, or canonical-ledger edit.

## Durable verification capture

This report is the retained release-readiness inventory capture. On 2026-09-07
UTC, a one-time **live-remote verification receipt** was made by a verifier
outside this checkout. The verifier performed remote reads and, for the gitlink,
wrote only to a temporary bare repository; it did not alter this checkout. The
temporary repository was discarded after inspection. The observations below are
the durable record of that receipt; a later release decision must make a fresh
receipt rather than treat cached remote-tracking refs as live evidence.

| Source | Read-only capture command and result | Captured identity |
| --- | --- | --- |
| Public upstream `https://github.com/meta-pytorch/monarch.git` | `git ls-remote <public-upstream> refs/heads/main` returned `e1a3ebbd7c106418e3398ae2babf155a2fee8e72` for `refs/heads/main` | public `main` `e1a3ebbd7c106418e3398ae2babf155a2fee8e72` |
| Configured fork remote (raw URI intentionally not persisted) | `git ls-remote <configured-fork> refs/heads/main` returned `6db28cfb78e983b40da411b5c1e171c50d8a124d`; the feature-ref query returned `4046eb9e750b7711007f7b776de22039192ea27a`; `refs/heads/ultron/mainline` returned no record | fork default and feature identities; no live federated-trunk ref |
| Declared gitlink URL `https://github.com/ROCm/hipify_torch.git` | In a temporary bare repository: `git fetch --no-tags <declared-url> ee928d80eb49a74be5d556465e04c6a40de7e3bc`; `git rev-parse ee928d80eb49a74be5d556465e04c6a40de7e3bc^{tree}` returned `e067baef28b4ed87470aa4726bf8c218229b2a7a` | exact gitlink commit and tree |
| Pinned gitlink content | `git show ee928d80eb49a74be5d556465e04c6a40de7e3bc:LICENSE.txt | sha256sum` returned `ecf819d55b17c2f091b3ba0934d044368aa0680d8a81374860306aa2b91aa1eb`; `git merge-base --is-ancestor <pin> 1ea3231415a41c07f9e1f1d41906df08a9af390d` succeeded | MIT license content and public-master ancestry |

The local commands in [Verification record and remaining decisions](#verification-record-and-remaining-decisions)
rechecked the checkout state at the same observation date. They are separate
from the live receipt and do not establish remote liveness.

## Trusted boundary and provenance

| Boundary | Observation | Review state | Disposition |
| --- | --- | --- | --- |
| Public upstream | `https://github.com/meta-pytorch/monarch.git`; live `main` was `e1a3ebbd7c106418e3398ae2babf155a2fee8e72` | verified by dated live-remote receipt | integrate |
| Configured fork | Live default `main` was `6db28cfb78e983b40da411b5c1e171c50d8a124d`; live feature head was `4046eb9e750b7711007f7b776de22039192ea27a`; no live `ultron/mainline` | verified by dated live-remote receipt; not a release boundary | retain-local |
| Local `main` | `ed393f251dadbcaa1a67504d6875d674b9e729e7`, 48 ahead and 190 behind live upstream `main`; merge base `c1205cc46d4582d252471c22ed6f3a57633110c0` | compared with dated live-remote receipt | integrate |
| Local feature head | `4046eb9e750b7711007f7b776de22039192ea27a`, 49 ahead and 190 behind live upstream `main` | compared with dated live-remote receipt | integrate |
| Local `upstream/main` snapshot | `f160d319c9f84593213ebca36738a309d4d7773f`, older than the live observation | snapshot only | retain-local |
| Configured upstream push URL | Present, contrary to the release remote contract | recorded; changing it is outside authority | retain-local |

The trusted public comparison point is the dated live-remote receipt, not
`refs/remotes/upstream/*`. The local `main`/`ultron/mainline`
series requires reconstruction or synchronization before release. This
inventory does not select a candidate commit.

### Gitlink proof

The sole superproject gitlink is `deps/hipify_torch`, mode `160000`, pinned to
`ee928d80eb49a74be5d556465e04c6a40de7e3bc`; `.gitmodules` declares
`https://github.com/ROCm/hipify_torch`. Local `git ls-files -s` and every local
head agree on that one path and pin.

The dated live-remote receipt fetched that exact SHA into a temporary bare
repository from the declared public URL. The commit's tree is
`e067baef28b4ed87470aa4726bf8c218229b2a7a`; its subject is `refresh from
upstream v2 mappings (#79)`, authored by Jeff Daily on 2025-10-14. At the pin,
`LICENSE.txt` is MIT with SHA-256
`ecf819d55b17c2f091b3ba0934d044368aa0680d8a81374860306aa2b91aa1eb`.
The pin is an ancestor of public `master`
`1ea3231415a41c07f9e1f1d41906df08a9af390d`, which had two later commits at
observation time. This proves public availability, content identity, and the
MIT license for the pinned content. The gitlink is therefore **integrate**,
with review state **verified provenance; candidate inclusion still requires
normal dependency review**.

## Ref estate

`git for-each-ref` found 3,227 names: 8 local heads, 3,207 cached
remote-tracking refs, 10 tags, and 2 tool refs. There are 2,966 distinct direct
ref objects. These counts are names, not a basis for collapsing aliases.

| Local branch | Head | Basis | Review state | Disposition |
| --- | --- | --- | --- | --- |
| `main` | `ed393f251dadbcaa1a67504d6875d674b9e729e7` | native intended patch series | human reconstruction/synchronization required | integrate |
| `ultron/mainline` | `ed393f251dadbcaa1a67504d6875d674b9e729e7` | federated trunk target; equals local `main`, local-only | not a qualified candidate | integrate |
| `feature/unified-control-plane-substrate` | `4046eb9e750b7711007f7b776de22039192ea27a` | pushed provisional control-plane milestone | focused tests previously passed; release gates remain open | integrate |
| `backup/unified-control-plane-substrate-prerebase` | `4046eb9e750b7711007f7b776de22039192ea27a` | exact alias of feature head | preserve pending human cleanup | superseded |
| `codex/active-work-tracker` | `2d9a3e102853f3bb2e465e46bd6b0aff1f9d33cf` | no patch-unique commits against local `main` | dirty worktree is separately retained | superseded |
| `codex/bwrap-contract-closeout` | `8f719d6c3ae68e0decd66daf5611ea8c98b6f92a` | 18 patch-unique Hermetic Rootfs/Local Run commits | replay and review separately | integrate |
| `codex/ultron-mainline-policy` | `ce427102c12d282d03169a83fde8361a1d467600` | one patch-unique workflow-policy commit | reconcile in its policy worktree | integrate |
| `glm52-gpu-workload` | `46acdaf44333db54541cb6be6244628cfff0fd4a` | 10 patch-unique workload commits and separate evidence/configuration | out of ticket scope | retain-local |

| Other ref class | Count | Review state | Disposition |
| --- | ---: | --- | --- |
| Cached remote-tracking refs | 3,207 | observation only; never trusted without a live check | retain-local |
| Existing tags | 10: 5 annotated and unsigned, 5 lightweight; none federation-candidate or release tag | human tag/candidate review required | retain-local |
| Tool-owned turn-diff refs | 2 | preserve until separately authorized tool cleanup; names deliberately omitted | reject |

`reject` above means reject from publication only. It does not authorize ref
deletion or tool cleanup.

## Worktrees and dirty material

The pre-report snapshot had five attached, non-detached worktrees and 50 dirty
paths; no worktree had an active merge, rebase, cherry-pick, revert, or bisect.
The completed report made the root class 10 paths. The recovery manifest below
is deliberately created last and excludes itself, yielding 11 root paths and
52 final dirty paths, assuming no concurrent owner change.

| Worktree | Branch | Pre-report dirt | Review state | Disposition |
| --- | --- | ---: | --- | --- |
| repository root | `feature/unified-control-plane-substrate` | 11 final untracked production-readiness tracker files | tracker intent only, not release evidence | integrate |
| `.worktrees/active-work-tracker` | `codex/active-work-tracker` | 4 modified workflow-guidance files and 5 untracked tracker/tool files | separate effort | superseded |
| `.worktrees/glm52-gpu-workload` | `glm52-gpu-workload` | 32 untracked paths | separate workload effort | retain-local |
| `.worktrees/ultron-mainline` | `ultron/mainline` | clean | candidate reconstruction required | integrate |
| `.worktrees/ultron-mainline-policy` | `codex/ultron-mainline-policy` | clean | policy reconciliation required | integrate |

| Dirty/generated class | Count or observation | Review state | Disposition |
| --- | --- | --- | --- |
| Root production-readiness tracker, including this report and recovery manifest | 11 final paths | process intent; canonical ledger remains non-authoritative | integrate |
| Active-work-tracker modified/untracked material | 9 | separate effort | retain-local |
| GLM52 specs and local configuration | 7 | separate effort | retain-local |
| GLM52 `*.pyc` files | 25 | generated; removal needs separate authority | reject |
| `control-plane-results/` | 2 files, 101,113 bytes | replace only with fresh sanitized contract-bound receipt | reject |
| `substrate-results/` | 4 files, 4,583 bytes | privacy/security review required before evidence publication | reject |
| `glm52-serving-results/` | 64,697 files, 5,508,623,030 bytes | sensitive-metadata review required | retain-local |
| `glm52-benchmark-results/` | 771 files, 1,620,253 bytes | sensitive-metadata review required | retain-local |
| Remaining `.scratch/` | exact self-excluded count and size are in the timestamped recovery manifest | quarantine pending human review | retain-local |
| `scripts/rootfs/rootfs/` | 60,666 files, 10,561,875,714 bytes | rebuild from reviewed inputs | reject |
| `.venv/`, `.venv-rootfs/`, `target/`, future `build/`/`dist/`, wheels, archives, and images | 20,121 / 23,934 / 3 current files, respectively; local environments or generated binaries | rebuild or produce under a reviewed publication contract | reject |
| Git LFS | no pointers or tracked LFS files | empty inventory | reject |

The tracked workflows `wheels.yml` and `publish_release.yml` are inherited PyPI
and container-publication machinery. They are **integrate**, review state
**execution and publication outside this milestone**. Any resulting wheel,
container, attestation, SBOM, log, or receipt is **reject** until it has a
separate reviewed publication entry.

### Recovery manifest

Before any local work is reconstructed, the local-only
[recovery manifest](../estate-fingerprints-2026-09-07.json) preserves a
redacted recovery reference and SHA-256 content fingerprint for each of the 51
final Git-dirty paths that existed before the manifest. It also records
deterministic redacted tree-metadata fingerprints for the large ignored
generated/evidence classes, and content fingerprints for the small receipt
directories. The report and ticket were finalized before that manifest was
generated; neither is edited afterward.

The manifest explicitly excludes itself. Including its content hash would
require rewriting it after every hash update, so it cannot be a stable
pre-reconstruction fingerprint. The final live count is therefore 52: 51
manifest-covered dirty paths plus the self-excluded manifest.

### Post-observation volatility

A later `scripts/run` canonical-gateway verifier was non-observational for the
host estate: its bubblewrap bind mounts projected a different generated/cache
namespace, rather than establishing or mutating host generated state. No
deletion, revert, Git, ref, remote, or host generated-state mutation was
performed for this inventory. The generated-class observations above and the
replacement manifest were refreshed with a host-side read-only Python walker,
not `scripts/run`.

For each class, the host walker enumerates `Path.rglob('*')` entries satisfying
`is_file()`, converts them to class-relative POSIX paths, and sorts by Python
string order. Content records are `<file SHA-256><two spaces><relative path>`;
metadata records are `f<tab><decimal size><tab><relative path>`. It NUL-joins
the records and adds exactly one final NUL for a non-empty stream before
SHA-256. `.scratch` excludes only the manifest itself.

Generated-class fingerprints are therefore point-in-time recovery identities,
not a durable assertion that mutable caches or evidence directories remain
current after their recorded observation. The manifest's content SHA-256
entries remain the recovery identity for its 51 covered Git-dirty files.

## Object residue

| Class | Observation | Review state | Disposition |
| --- | --- | --- | --- |
| Unreachable objects | 260: 54 commits, 157 trees, 49 blobs | quarantine; inspect before history cleanup | retain-local |
| Reflog entries | 3,388 | preserve for recovery and review | retain-local |
| Stash, notes, replace refs | 0 each | empty inventory | retain-local |
| Object-store health | `git fsck --full --no-reflogs --unreachable --dangling` reported no corruption; non-shallow, four packs | verified local health | retain-local |

The empty classes are retained as a record, not an instruction to create or
delete anything. No prune operation is authorized.

## Ledger validation and drift

`estate-ledger.json` parses as JSON and reports schema `1.1` and tool `1.1.0`.
It is a 2026-09-04 canonical-tool snapshot whose generator is absent here;
the ledger itself must not be hand-edited. It has 3,268 items: 3,213 `ref`, 49
`dirty`, 5 `worktree`, and 1 `gitlink`, all `retain-local` and
`pending-human-review`.

It is stale and non-authoritative for current release decisions:

- It identifies refs by object, not refname, collapsing aliases. The current
  estate has 3,227 refnames and 2,966 direct objects, so name-level dispositions
  cannot be represented.
- Fifteen current objects are missing and four recorded objects are no longer
  referenced. The missing set includes the two tool refs, the feature object,
  and 13 cached-upstream objects.
- It has no worktree paths or dirty paths. Its 49 dirty entries do not cover the
  live root change; the pre-report live count was 50 and this report makes it
  51.
- `policy_refs.ultron/mainline` is
  `2d9a3e102853f3bb2e465e46bd6b0aff1f9d33cf`, while live local
  `refs/heads/ultron/mainline` is
  `ed393f251dadbcaa1a67504d6875d674b9e729e7`.
- It lacks remote trust state, upstream relationships, tag type/signature and
  release status, reflog and unreachable-object classes, tool refs, gitlink
  provenance, generated-evidence paths, and publication machinery.

Canonical regeneration is therefore required before candidate assembly, followed
by an independent comparison with this name- and path-level report. A future
generator may select different stable identifiers or class boundaries; that is
why the comparison, rather than a hand edit, is required.

## Publication boundary

A publication exclusion is not deletion authority. `reject` means the item must
not enter the candidate or a publication output under this ticket. It does not
permit deleting generated files, pruning objects/reflogs, removing gitlinks,
or changing refs. `retain-local` preserves a local item outside the candidate;
`superseded` preserves it until human-approved cleanup; `integrate` identifies
process or source material that requires a later reviewed integration action.

## Verification record and remaining decisions

Read-only commands run from the repository root included:

```sh
git remote -v
git rev-parse main ultron/mainline feature/unified-control-plane-substrate upstream/main origin/main
git merge-base main upstream/main
git rev-list --left-right --count upstream/main...main
git for-each-ref --format='%(refname) %(objectname)'
git worktree list --porcelain
git -C <worktree> status --porcelain=v1 -uall
git ls-files -s | awk '$1==160000'
git fsck --full --no-reflogs --unreachable --dangling
git reflog --all --format='%H' | wc -l
jq '...' .scratch/production-release-readiness/estate-ledger.json
```

The dated live-remote receipt additionally records the remote reads and
exact-SHA temporary-bare fetch that prove the gitlink above. Human decisions
and blockers remain:

1. Select and reconstruct/synchronize the release candidate against the trusted
   public upstream boundary.
2. Approve integration or cleanup plans for the `integrate` and `superseded`
   branches, without treating this report as Git authority.
3. Regenerate the canonical ledger and independently compare it with this
   report before candidate assembly.
4. Approve the sensitive-metadata review and any receipt/publication contract;
   do not publish the rejected classes.
5. Authorize and perform the remote-contract repair that removes the usable
   configured upstream push destination. The contract requires upstream to be
   fetch-only with no usable push destination; this inventory records the
   violation but does not authorize changing it.
