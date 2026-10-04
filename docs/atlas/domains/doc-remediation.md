---
id: doc-remediation
title: Documentation Remediation
status: documented
summary:
  - "Per-file verdict on the existing docs now that the Atlas documents the same ground — code-grounded and self-syncing."
  - "0 safe to remove, 0 to consolidate (save unique bits first), 0 to keep, 4 resolved."
  - "Removing a file is destructive — atlas-remediate is interview-first and never deletes without your confirmation."
tagline: Which existing docs the Atlas now supersedes — remove, consolidate, or keep.
invariants:
  - "NEVER remove a doc file without explicit human confirmation, even when marked remove."
links: [frontend, deployment, testing, frontend-pages-and-routing, frontend-landing-and-art, overview]
content_hash: sha256:a26580c062b15b9f8f8505737a19ac04f3ff0d34cdc8b67a6c95d1b589c033eb
---
## Summary

Pass 3 also judges each existing doc as a **whole file**: now that the Atlas documents the same material (code-grounded, `file:line`, self-syncing), is the file still earning its place? Each row is a verdict — **remove** (the Atlas supersedes it; safe to delete), **consolidate** (mostly superseded, but holds unique content to fold into the Atlas first), or **keep** (serves a purpose the Atlas does not). Filter by verdict; start with **remove**.

**0 remove · 0 consolidate · 0 keep · 4 resolved.** Removing a file is destructive: hand each to `atlas-remediate DOC-001` — it interviews you first and **never deletes without your explicit OK** (and for *consolidate*, it folds the unique content into the Atlas and proves it's captured before proposing removal).

**4 files already handled.** Resolved entries keep their id, render in the **resolved** filter with the closing commit, and are tracked in `.resolved.json`.

## Reference

Every existing doc, with its supersession verdict. `remove` = the Atlas covers it fully; `consolidate` = save the unique bits first; `keep` = distinct purpose. Handled files carry the **resolved** chip.

| ID {remove} | Verdict | File | Superseded by | Save first (unique) | Recommendation |
|---|---|---|---|---|---|
| DOC-001 {resolved} | resolved (was remove) | `frontend/README.md` | `frontend`, `deployment`, `testing` | — | resolved in `6955139` — Replaced the stock CRA README with a short Floor Pov README: commands, backend … |
| DOC-002 {resolved} | resolved (was remove) | `frontend/.project-snapshot.md` | `frontend`, `frontend-pages-and-routing`, `frontend-landing-and-art`, `overview` | — | resolved in `e0863ef` — Removed the stale frontend/.project-snapshot.md; the code and atlas supersede i… |
| DOC-003 {resolved} | resolved (was consolidate) | `frontend/public/art/README.md` | `frontend-landing-and-art` | — | resolved in `cc62a73` — Unique content folded into frontend-landing-and-art; art README rewritten as a … |
| DOC-004 {resolved} | resolved (was keep) | `frontend/public/art/bosses/README.md` | `frontend-landing-and-art` | — | resolved in `7bae88d` — Kept; corrected against fetch-boss-renders.py (AnalyzeConfig.js, ENC_OVERRIDE, … |

## Gotchas

Before removing anything, save what only the old doc has (resolved files omitted):

- No outstanding file carries unique content that the Atlas does not already cover.

## Related

Each file is superseded by one or more code-truth Atlas domains — the trustworthy version of the same material: [[frontend]] · [[deployment]] · [[testing]] · [[frontend-pages-and-routing]] · [[frontend-landing-and-art]] · [[overview]].
