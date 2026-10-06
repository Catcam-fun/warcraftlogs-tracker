#!/usr/bin/env node
/* ============================================================================
 * render-doc-remediation.mjs — the per-FILE sibling of the reconciliation page.
 * Pass 3 also judges each EXISTING doc as a whole file: now that the Atlas
 * documents the same ground (code-grounded, self-syncing), is the file still
 * earning its place? Verdict per file:
 *   remove      — the Atlas supersedes it fully → safe to delete
 *   consolidate — mostly superseded, but holds unique content → fold into the
 *                 Atlas first, THEN remove
 *   keep        — serves a purpose the Atlas does not (README, ADRs, user docs)
 *
 * Renders docs/atlas/domains/doc-remediation.md with a verdict-filterable table.
 *
 * LEDGER-AWARE + RE-RENDERABLE (mirrors render-reconciliation.mjs). On first run
 * with an input file it persists a snapshot to <ATLAS_ROOT>/.doc-remediation.json
 * so the page can be re-rendered later without the original input (and without
 * renumbering the stable DOC-### ids). On every run it reads
 * <ATLAS_ROOT>/.resolved.json and marks any DOC-### in the ledger as RESOLVED —
 * it keeps its id, moves to the `resolved` filter, cites the commit, and drops
 * out of the open tallies. So after `atlas-remediate` removes/consolidates a doc
 * and records it, re-running this (no arg) + rebuilding reflects the closure.
 *
 * Zero-dependency (Node >= 16). Companion to render-reconciliation.mjs.
 *
 * Usage:
 *   ATLAS_ROOT=docs/atlas node render-doc-remediation.mjs <files.json>   # first render (persists snapshot)
 *   ATLAS_ROOT=docs/atlas node render-doc-remediation.mjs                # re-render from snapshot + ledger
 * then add a domain to atlas.config.json:
 *   { "id": "doc-remediation", "title": "Documentation Remediation",
 *     "axis": "layer", "color": "amber", "kicker": "Meta · Remove / consolidate / keep" }
 * and rebuild.
 *
 * Input JSON shape:
 *   { "files": [ { "file", "verdict", "supersededBy":[atlas page ids],
 *                  "unique":[strings], "recommendation", "confidence"? } ] }
 *   verdict ∈ remove | consolidate | keep
 * ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';

const ATLAS_ROOT = process.env.ATLAS_ROOT
  ? path.resolve(process.env.ATLAS_ROOT)
  : path.resolve(process.cwd(), 'docs/atlas');

const SNAPSHOT = path.join(ATLAS_ROOT, '.doc-remediation.json');
const LEDGER = path.join(ATLAS_ROOT, '.resolved.json');

const inPath = process.argv[2];
let input;
if (inPath && fs.existsSync(inPath)) {
  input = JSON.parse(fs.readFileSync(inPath, 'utf8'));
  fs.mkdirSync(path.dirname(SNAPSHOT), { recursive: true });
  fs.writeFileSync(SNAPSHOT, JSON.stringify(input, null, 2) + '\n');
} else if (fs.existsSync(SNAPSHOT)) {
  input = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8'));
  console.error(`[doc-remediation] no input file given — re-rendering from snapshot ${path.relative(ATLAS_ROOT, SNAPSHOT)}`);
} else {
  console.error('usage: ATLAS_ROOT=docs/atlas node render-doc-remediation.mjs <files.json>');
  console.error('   or: ATLAS_ROOT=docs/atlas node render-doc-remediation.mjs   (re-render from .doc-remediation.json once it exists)');
  process.exit(2);
}

let ledger = {};
try { ledger = JSON.parse(fs.readFileSync(LEDGER, 'utf8')); } catch { ledger = {}; }

const VORD = { remove: 0, consolidate: 1, keep: 2 };
const files = (input.files || []).slice().sort((a, b) => (VORD[a.verdict] ?? 9) - (VORD[b.verdict] ?? 9));
files.forEach((f, i) => { if (!f.id) f.id = 'DOC-' + String(i + 1).padStart(3, '0'); });
files.forEach((f) => { f._res = ledger[f.id] || null; });

const open = files.filter((f) => !f._res);
const nResolved = files.length - open.length;

const tally = open.reduce((m, f) => ((m[f.verdict] = (m[f.verdict] || 0) + 1), m), {});
const t = (k) => tally[k] || 0;
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').replace(/\|/g, '/').trim();
const trunc = (s, n) => { s = clean(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
const arr = (v) => (Array.isArray(v) ? v : (v ? [v] : []));
const code = (v) => arr(v).map((x) => '`' + clean(x) + '`').join(', ');

const allPages = [...new Set(files.flatMap((f) => arr(f.supersededBy).map((x) => String(x).trim())).filter(Boolean))];

let md = '';
md += '---\n';
md += 'id: doc-remediation\n';
md += 'title: Documentation Remediation\n';
md += 'status: documented\n';
md += 'summary:\n';
md += '  - "Per-file verdict on the existing docs now that the Atlas documents the same ground — code-grounded and self-syncing."\n';
md += `  - "${t('remove')} safe to remove, ${t('consolidate')} to consolidate (save unique bits first), ${t('keep')} to keep${nResolved ? `, ${nResolved} resolved` : ''}."\n`;
md += '  - "Removing a file is destructive — atlas-remediate is interview-first and never deletes without your confirmation."\n';
md += 'tagline: Which existing docs the Atlas now supersedes — remove, consolidate, or keep.\n';
md += 'invariants:\n';
open.filter((f) => f.verdict === 'consolidate').slice(0, 5).forEach((f) => {
  md += `  - "MUST fold ${clean(f.file)}'s unique content into the Atlas before removing it (${f.id})."\n`;
});
md += '  - "NEVER remove a doc file without explicit human confirmation, even when marked remove."\n';
md += `links: [${allPages.join(', ')}]\n`;
md += '---\n\n';
md += '## Summary\n\n';
md += 'Pass 3 also judges each existing doc as a **whole file**: now that the Atlas documents the same material (code-grounded, `file:line`, self-syncing), is the file still earning its place? Each row is a verdict — **remove** (the Atlas supersedes it; safe to delete), **consolidate** (mostly superseded, but holds unique content to fold into the Atlas first), or **keep** (serves a purpose the Atlas does not). Filter by verdict; start with **remove**.\n\n';
md += `**${t('remove')} remove · ${t('consolidate')} consolidate · ${t('keep')} keep${nResolved ? ` · ${nResolved} resolved` : ''}.** Removing a file is destructive: hand each to \`atlas-remediate DOC-001\` — it interviews you first and **never deletes without your explicit OK** (and for *consolidate*, it folds the unique content into the Atlas and proves it's captured before proposing removal).\n\n`;
if (nResolved) {
  md += `**${nResolved} file${nResolved === 1 ? '' : 's'} already handled.** Resolved entries keep their id, render in the **resolved** filter with the closing commit, and are tracked in \`.resolved.json\`.\n\n`;
}
md += '## Reference\n\n';
md += 'Every existing doc, with its supersession verdict. `remove` = the Atlas covers it fully; `consolidate` = save the unique bits first; `keep` = distinct purpose. Handled files carry the **resolved** chip.\n\n';
md += '| ID {remove} | Verdict | File | Superseded by | Save first (unique) | Recommendation |\n';
md += '|---|---|---|---|---|---|\n';
files.forEach((f) => {
  if (f._res) {
    const note = trunc(f._res.note || '', 80);
    md += `| ${f.id} {resolved} | resolved (was ${f.verdict}) | \`${clean(f.file)}\` | ${code(f.supersededBy) || '—'} | — | resolved in \`${clean(f._res.resolvedIn)}\`${note ? ' — ' + note : ''} |\n`;
  } else {
    md += `| ${f.id} {${f.verdict}} | ${f.verdict} | \`${clean(f.file)}\` | ${code(f.supersededBy) || '—'} | ${trunc(arr(f.unique).join('; ') || '—', 90)} | ${trunc(f.recommendation, 90)} |\n`;
  }
});
md += '\n## Gotchas\n\n';
md += 'Before removing anything, save what only the old doc has (resolved files omitted):\n\n';
const cons = open.filter((f) => f.verdict === 'consolidate' || arr(f.unique).length);
if (cons.length) {
  cons.slice(0, 14).forEach((f) => {
    md += `- **${clean(f.file)}** (${f.id}, ${f.verdict}): unique content to preserve — ${trunc(arr(f.unique).join('; ') || 'none identified', 160)}.\n`;
  });
} else {
  md += '- No outstanding file carries unique content that the Atlas does not already cover.\n';
}
md += '\n## Related\n\n';
md += 'Each file is superseded by one or more code-truth Atlas domains — the trustworthy version of the same material: ';
md += (allPages.length ? allPages.map((p) => `[[${p}]]`).join(' · ') : 'link the relevant domain pages here') + '.\n';

const outPath = path.join(ATLAS_ROOT, 'domains', 'doc-remediation.md');
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, md);
console.error(`[doc-remediation] wrote ${path.relative(ATLAS_ROOT, outPath)} — ${files.length} files (${t('remove')} remove, ${t('consolidate')} consolidate, ${t('keep')} keep, ${nResolved} resolved)`);
console.error(`[doc-remediation] ensure the 'doc-remediation' domain is in atlas.config.json and run build-atlas.mjs`);
