# Teaching notes — preferences & working notes

## Learner preferences (observed)
- **Source-faithful above all.** Every lesson claim must cite an exact file:line
  in this checkout. No generic bwrap/docker lore presented as fact. If a fact is
  from memory, say so.
- **Repo-local.** This workspace lives at `.agents/teach/` and is git-ignored (a
  one-line rule was added to `.gitignore`). Monarch-specific artifacts stay in
  the repo, not in `~/.agents` or outside.
- **Clean-tree discipline.** Do not dirty the tracked tree. `yarn.lock` under
  `python/monarch/monarch_dashboard/frontend/` is Buck-owned — never edit/commit
  it; `git restore` if it drifts.
- **Text-based lessons.** Lessons and reference are Emacs org-mode (`.org`) with
  headings and bullets, no tables — the learner's recorded preference. (The teach
  skill defaults to HTML; we deliberately override it here at the learner's
  request.) Quizzes are inline "answer before reading" questions, not JS widgets.
- **Mission: extend/maintain confidently** — lessons target the invariants you
  must not break when changing the rootfs, not abstract appreciation.

## Workspace facts
- Mission: `.agents/teach/MISSION.md`.
- Reference: `reference/rootfs-glossary.org`.
- No `assets/` — text-based lessons need no shared CSS/JS.

## Lesson plan (zone of proximal development)
1. [done] 0001 — the recipe digest is identity (staleness/rebuild).
2. [done] 0002 — the guard & execution domains — why `scripts/run` is the only door,
   how domains decide what must run inside, the `monarch_contract_error` redirect.
3. [done] 0003 — hermeticity mechanics — read-only root, `--clearenv` + allowlist, why bare
   `cargo` fails (PyO3/libpython), the venv activation.
4. [done] 0004 — GPU & CUDA — synthetic `CUDA_HOME`, host driver bind, driver/runtime match.
5. [done] 0005 — writing a capacity verifier — the Local Run Ladder, Contract Artifacts,
   Failure Classification (Suite-Ordering Fragility), grounded in
   `run_local_8gpu_capacity.sh`.

## Open item to confirm with learner
- I added `.agents/teach/` to `.gitignore` (a tracked-file edit). If the learner
  prefers zero tracked edits, revert it and instead keep the workspace outside
  the repo — but that trades away repo-local discoverability.
