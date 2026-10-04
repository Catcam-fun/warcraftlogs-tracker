---
id: doc-remediation
title: Documentation Remediation
status: documented
summary:
  - "Per-file verdict on the existing docs now that the Atlas documents the same ground — code-grounded and self-syncing."
  - "2 safe to remove, 1 to consolidate (save unique bits first), 1 to keep."
  - "Removing a file is destructive — atlas-remediate is interview-first and never deletes without your confirmation."
tagline: Which existing docs the Atlas now supersedes — remove, consolidate, or keep.
invariants:
  - "MUST fold frontend/public/art/README.md's unique content into the Atlas before removing it (DOC-003)."
  - "NEVER remove a doc file without explicit human confirmation, even when marked remove."
links: [frontend, deployment, testing, frontend-pages-and-routing, frontend-landing-and-art, overview]
content_hash: sha256:0cea54fc087ae6af07101d44b1fc88ad400d21f833afca2201846a1c48052ca7
---
## Summary

Pass 3 also judges each existing doc as a **whole file**: now that the Atlas documents the same material (code-grounded, `file:line`, self-syncing), is the file still earning its place? Each row is a verdict — **remove** (the Atlas supersedes it; safe to delete), **consolidate** (mostly superseded, but holds unique content to fold into the Atlas first), or **keep** (serves a purpose the Atlas does not). Filter by verdict; start with **remove**.

**2 remove · 1 consolidate · 1 keep.** Removing a file is destructive: hand each to `atlas-remediate DOC-001` — it interviews you first and **never deletes without your explicit OK** (and for *consolidate*, it folds the unique content into the Atlas and proves it's captured before proposing removal).

## Reference

Every existing doc, with its supersession verdict. `remove` = the Atlas covers it fully; `consolidate` = save the unique bits first; `keep` = distinct purpose. Handled files carry the **resolved** chip.

| ID {remove} | Verdict | File | Superseded by | Save first (unique) | Recommendation |
|---|---|---|---|---|---|
| DOC-001 {remove} | remove | `frontend/README.md` | `frontend`, `deployment`, `testing` | — | Stock Create React App boilerplate with no project content; the npm scripts are covered b… |
| DOC-002 {remove} | remove | `frontend/.project-snapshot.md` | `frontend`, `frontend-pages-and-routing`, `frontend-landing-and-art`, `overview` | — | A stale machine-generated dump from 2026-05-16 with mojibake, wrong line counts, a delete… |
| DOC-003 {consolidate} | consolidate | `frontend/public/art/README.md` | `frontend-landing-and-art` | Rationale for self-hosting art (no hotlinking, survives source removal); Web processing s… | Useful in place for contributors, but its add-a-background steps are wrong (ignore CURREN… |
| DOC-004 {keep} | keep | `frontend/public/art/bosses/README.md` | `frontend-landing-and-art` | Step-by-step fetch-boss-renders.py pipeline (wago.tools DB2 lookups, render CDN URL, cuto… | Mostly accurate and the natural place a contributor looks when adding tiles, so keep it b… |

## Gotchas

Before removing anything, save what only the old doc has (resolved files omitted):

- **frontend/public/art/README.md** (DOC-003, consolidate): unique content to preserve — Rationale for self-hosting art (no hotlinking, survives source removal); Web processing spec for backgrounds (~2200px, JPEG q72); Fan-content/attribution note:….
- **frontend/public/art/bosses/README.md** (DOC-004, keep): unique content to preserve — Step-by-step fetch-boss-renders.py pipeline (wago.tools DB2 lookups, render CDN URL, cutout, 300px webp); Command line usage with boss-name args and Pillow req….

## Related

Each file is superseded by one or more code-truth Atlas domains — the trustworthy version of the same material: [[frontend]] · [[deployment]] · [[testing]] · [[frontend-pages-and-routing]] · [[frontend-landing-and-art]] · [[overview]].
