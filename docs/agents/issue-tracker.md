# Legacy tracker history

Kata is authoritative for active engineering intent. Follow
`docs/agents/active-work.md` for selection, creation, claiming, relationships,
handoff, and closure.

Existing Markdown files under `.scratch/` are read-only cutover history. Do not
create, claim, resolve, update, or dual-write active work in these files. The
legacy importer may read unresolved specs and tickets using their historical
`Status:`, `Blocked by:`, `Parent:`, and `## Comments` fields, but it never
modifies or deletes them.

Historical wayfinder maps and ticket files remain useful as provenance. New
single-repository work belongs in that repository's Kata project; new
cross-repository work uses an Ultron Kata parent with linked project children.
