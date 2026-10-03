#!/usr/bin/env node
/* ============================================================================
 * render-reconciliation.mjs — turn Pass-3 reconcile discrepancies into a
 * rendered Atlas PAGE (domains/reconciliation.md), so the docs-vs-code diff is
 * clickable in the interactive doc, not a flat report.
 *
 * The reconcile pass (source-policy.md Pass 3) compares each hand-written doc
 * against the CURRENT code and emits discrepancies. Feed them here; this writes
 * a single-file `reconciliation` domain page with a verdict-filterable table.
 *
 * LEDGER-AWARE + RE-RENDERABLE. On first run with an input file, it persists a
 * snapshot of the discrepancies to <ATLAS_ROOT>/.reconcile.json so the page can
 * be re-rendered later WITHOUT the original input (and without re-running the
 * whole reconcile, which would renumber the stable RC-### ids). On every run it
 * reads <ATLAS_ROOT>/.resolved.json (the resolved ledger written by
 * record-resolved.mjs) and marks any finding whose id is in the ledger as
 * RESOLVED — it keeps its id, moves to the `resolved` filter chip, cites the
 * fixing commit, and drops out of the open tallies and the conflict callouts.
 * So after `atlas-remediate` records a fix, re-running this (no arg) + rebuilding
 * makes the HTML reflect the closure.
 *
 * Zero-dependency (Node >= 16). Companion to build-atlas.mjs / record-resolved.mjs.
 *
 * Usage:
 *   ATLAS_ROOT=docs/atlas node render-reconciliation.mjs <discrepancies.json>  # first render (persists snapshot)
 *   ATLAS_ROOT=docs/atlas node render-reconciliation.mjs                       # re-render from the snapshot + ledger
 * then add a domain to atlas.config.json:
 *   { "id": "reconciliation", "title": "Docs ⇄ Code Reconciliation",
 *     "axis": "layer", "color": "amber", "kicker": "Meta · Docs vs code drift" }
 * and rebuild: `node build-atlas.mjs`.
 *
 * Input JSON shape:
 *   { "discrepancies": [ { "id"?, "doc", "topic", "verdict", "docClaim",
 *                          "docSource"?, "codeTruth", "note"? }, ... ],
 *     "docMap"?: { "<doc-id>": "<display path>" } }
 *   verdict ∈ conflict | stale | gap | ok
 *     conflict = the doc is wrong; stale = was true, code moved on;
 *     gap = described-but-absent (or code-does/doc-omits); ok = verified aligned.
 * ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';

const ATLAS_ROOT = process.env.ATLAS_ROOT
  ? path.resolve(process.env.ATLAS_ROOT)
  : path.resolve(process.cwd(), 'docs/atlas');

const SNAPSHOT = path.join(ATLAS_ROOT, '.reconcile.json');
const LEDGER = path.join(ATLAS_ROOT, '.resolved.json');

// SELF-HEAL: recover findings that live in the rendered page but are absent from
// the snapshot, and fold them back in. This repairs the drift left by an update
// that wrote reconciliation.md WITHOUT persisting .reconcile.json — otherwise a
// plain re-render silently DROPS those findings. Runs on every re-render, so any
// project carrying this drift heals itself the first time this script runs there.
// Reconstructs each orphan's fields from its page row (lossy only for the trailing
// file-ref and any text the page already truncated); logs exactly what it recovered.
function healSnapshotFromPage(snap) {
  const pagePath = path.join(ATLAS_ROOT, 'domains', 'reconciliation.md');
  if (!fs.existsSync(pagePath)) return snap;
  const known = new Set((snap.discrepancies || []).map((d) => d.id).filter(Boolean));
  const recovered = [];
  for (const line of fs.readFileSync(pagePath, 'utf8').split('\n')) {
    if (!/^\|\s*RC-\d+\s*\{/.test(line)) continue;           // finding rows only (skips header/separator)
    const cells = line.split('|').slice(1, -1).map((c) => c.trim());
    if (cells.length < 5) continue;
    const id = (cells[0].match(/RC-\d+/) || [])[0];
    if (!id || known.has(id)) continue;
    const doc = cells[2].replace(/`/g, '').trim();
    const topic = cells[3];
    const resM = cells[1].match(/^resolved \(was (\w+)\)/);   // resolved rows hide the drift; keep the original verdict
    if (resM) {
      recovered.push({ id, doc, topic, verdict: resM[1], docClaim: '', codeTruth: '', note: '(recovered from page by self-heal)' });
    } else {
      const [dc, ct] = cells[4].split(/\s*→\s*code:\s*/);
      recovered.push({
        id, doc, topic, verdict: cells[1],
        docClaim: (dc || '').replace(/^doc:\s*/, '').trim(),
        codeTruth: (ct || '').replace(/\s*\(`[^`]+`\)\s*$/, '').trim(),
        note: '(recovered from page by self-heal)',
      });
    }
    known.add(id);
  }
  if (recovered.length) {
    snap = { ...snap, discrepancies: (snap.discrepancies || []).concat(recovered) };
    fs.mkdirSync(path.dirname(SNAPSHOT), { recursive: true });
    fs.writeFileSync(SNAPSHOT, JSON.stringify(snap, null, 2) + '\n');
    console.error(`[reconcile] SELF-HEAL: recovered ${recovered.length} finding(s) that were in the page but missing from the snapshot and folded them back into ${path.relative(ATLAS_ROOT, SNAPSHOT)} — ${recovered.map((r) => r.id).join(', ')}.`);
    console.error('[reconcile]   (cause: a prior update wrote reconciliation.md without persisting .reconcile.json; now repaired so future re-renders are non-destructive.)');
  }
  return snap;
}

// Next stable id given the ids already in the snapshot (RC-<max+1>), so a merge
// ADDS findings without renumbering — the ledger keys off these ids.
function maxRcNum(discs) {
  return (discs || []).reduce((mx, d) => {
    const m = /^RC-(\d+)$/.exec(d.id || '');
    return m ? Math.max(mx, +m[1]) : mx;
  }, 0);
}

// Input: an explicit discrepancies file, or the previously-persisted snapshot when
// re-rendering after a remediation. An explicit input MERGES into the existing
// snapshot (upsert by id; new id-less findings get RC-<max+1>) so a scoped/partial
// input can never silently drop the rest — pass --replace for a deliberate full
// overwrite (e.g. a fresh whole-repo reconcile).
const argv = process.argv.slice(2);
const REPLACE = argv.includes('--replace');
const inPath = argv.find((a) => a !== '--replace') || null;
const hadSnapshot = fs.existsSync(SNAPSHOT);
let input;
if (inPath && fs.existsSync(inPath)) {
  const incoming = JSON.parse(fs.readFileSync(inPath, 'utf8'));
  if (hadSnapshot && !REPLACE) {
    const existing = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8'));
    const order = (existing.discrepancies || []).slice();
    const byId = new Map(order.filter((d) => d.id).map((d) => [d.id, d]));
    let next = maxRcNum(order);
    for (const d of incoming.discrepancies || []) {
      if (!d.id) d.id = 'RC-' + String(++next).padStart(3, '0');
      if (byId.has(d.id)) Object.assign(byId.get(d.id), d);   // update in place (same ref lives in `order`)
      else { byId.set(d.id, d); order.push(d); }               // append genuinely new finding
    }
    input = { discrepancies: order, docMap: { ...(existing.docMap || {}), ...(incoming.docMap || {}) } };
    console.error(`[reconcile] merged ${(incoming.discrepancies || []).length} finding(s) from ${path.basename(inPath)} into the existing snapshot (upsert by id; use --replace to overwrite wholesale).`);
  } else {
    input = incoming;
    if (REPLACE && hadSnapshot) console.error('[reconcile] --replace: overwriting the existing snapshot wholesale.');
  }
  fs.mkdirSync(path.dirname(SNAPSHOT), { recursive: true });
  fs.writeFileSync(SNAPSHOT, JSON.stringify(input, null, 2) + '\n');
} else if (hadSnapshot) {
  input = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8'));
  console.error(`[reconcile] no input file given — re-rendering from snapshot ${path.relative(ATLAS_ROOT, SNAPSHOT)}`);
  input = healSnapshotFromPage(input);
} else {
  console.error('usage: ATLAS_ROOT=docs/atlas node render-reconciliation.mjs <discrepancies.json> [--replace]');
  console.error('   or: ATLAS_ROOT=docs/atlas node render-reconciliation.mjs   (re-render from .reconcile.json once it exists)');
  process.exit(2);
}

let ledger = {};
try { ledger = JSON.parse(fs.readFileSync(LEDGER, 'utf8')); } catch { ledger = {}; }

const docMap = input.docMap || {};
const VORD = { conflict: 0, stale: 1, gap: 2, ok: 3 };

const disc = (input.discrepancies || []).slice()
  .sort((a, b) => (VORD[a.verdict] ?? 9) - (VORD[b.verdict] ?? 9));
// Assign stable ids BEFORE consulting the ledger (the ledger is keyed by these ids).
disc.forEach((d, i) => { if (!d.id) d.id = 'RC-' + String(i + 1).padStart(3, '0'); });
disc.forEach((d) => { d._res = ledger[d.id] || null; });

const open = disc.filter((d) => !d._res);
const resolved = disc.filter((d) => d._res);
const nResolved = resolved.length;

const tally = open.reduce((m, d) => ((m[d.verdict] = (m[d.verdict] || 0) + 1), m), {});
const t = (k) => tally[k] || 0;
const docName = (d) => docMap[d] || d;
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').replace(/\|/g, '/').trim();
const trunc = (s, n) => { s = clean(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
const fileLine = (s) => {
  const m = String(s).match(/([A-Za-z0-9_.\/\[\]-]+\.(?:ts|tsx|js|mjs|sql|tf|json|yml|yaml|py|go|rb|rs):\d+)/);
  return m ? m[1] : '';
};
const openConflicts = open.filter((d) => d.verdict === 'conflict');

let md = '';
md += '---\n';
md += 'id: reconciliation\n';
md += 'title: Docs ⇄ Code Reconciliation\n';
md += 'status: documented\n';
md += 'summary:\n';
md += '  - "Pass 3 of the source policy: every hand-written doc diffed against the CURRENT code — the code wins."\n';
md += `  - "${t('conflict')} conflicts (doc is wrong), ${t('stale')} stale (code moved on), ${t('gap')} gaps, ${t('ok')} verified-aligned${nResolved ? `, ${nResolved} resolved` : ''}."\n`;
md += '  - "Filter the table by verdict; start with conflict — those are the misleads. Fixed findings move to the resolved filter."\n';
md += 'tagline: Where the prose docs disagree with the code — generated by diffing both.\n';
md += 'invariants:\n';
openConflicts.slice(0, 6).forEach((c) => {
  md += `  - "MUST update ${docName(c.doc)}: ${clean(c.topic).replace(/"/g, '')} (${c.id})."\n`;
});
md += 'links: []\n';
// No blank line after the closing '---': build-atlas's stampHash strips a leading
// body newline when it re-stamps content_hash, so emitting the already-normalized
// form keeps a single render→build→verify pass in sync (no spurious hash lag).
md += '---\n';
md += '## Summary\n\n';
md += 'This is the **reconciliation pass** (Pass 3) of the Atlas source policy. Each hand-written doc was compared, claim by claim, against the **current code** (the source of truth). Every row below is a place they disagree, classified **conflict** (the doc is wrong), **stale** (was true, the code has since changed), **gap** (described-but-absent, or code-does-but-doc-omits), or **ok** (verified correct). Filter by verdict; start with **conflict**.\n\n';
md += `**${t('conflict')} conflicts · ${t('stale')} stale · ${t('gap')} gaps · ${t('ok')} aligned${nResolved ? ` · ${nResolved} resolved` : ''}.** The code-truth Atlas pages are the trustworthy source; these docs need editing to match.\n\n`;
if (nResolved) {
  md += `**${nResolved} finding${nResolved === 1 ? '' : 's'} already fixed.** Resolved findings keep their id, render in the **resolved** filter with the fixing commit, and are tracked in \`.resolved.json\` — so this page stays accurate as fixes land (re-rendered from \`.reconcile.json\` + the ledger, no full re-diff).\n\n`;
}
md += '**Fixing these →** run the **`atlas-remediate`** skill with a finding-ID spec: `atlas-remediate RC-001` (one), `atlas-remediate RC-001..RC-010` (a range), `atlas-remediate RC-001,RC-005` (a list), or `atlas-remediate conflict` (all conflicts). It resolves each finding, gathers the surrounding code context, decides whether the fix is a doc edit or a code change, applies it (writing a failing test first for code changes), proves the finding is closed, records it in the ledger, and re-renders this page so the row flips to **resolved**.\n\n';
md += '## Reference\n\n';
md += 'Every doc⇄code discrepancy, filterable by verdict. Fixed findings carry the **resolved** chip and the commit that closed them.\n\n';
md += '| ID {conflict} | Verdict | Doc | Topic | The drift (doc → code) |\n';
md += '|---|---|---|---|---|\n';
disc.forEach((d) => {
  if (d._res) {
    const note = trunc(d._res.note || '', 100);
    const drift = `resolved in \`${clean(d._res.resolvedIn)}\`${note ? ' — ' + note : ''}`;
    md += `| ${d.id} {resolved} | resolved (was ${d.verdict}) | \`${docName(d.doc)}\` | ${trunc(d.topic, 60)} | ${drift} |\n`;
  } else {
    const fl = fileLine(d.codeTruth);
    const drift = 'doc: ' + trunc(d.docClaim, 90) + ' → code: ' + trunc(d.codeTruth, 110) + (fl ? ' (`' + fl + '`)' : '');
    md += `| ${d.id} {${d.verdict}} | ${d.verdict} | \`${docName(d.doc)}\` | ${trunc(d.topic, 60)} | ${clean(drift)} |\n`;
  }
});
md += '\n## Gotchas\n\n';
md += 'The conflicts most likely to mislead a reader who trusts the docs (resolved ones omitted):\n\n';
if (openConflicts.length) {
  openConflicts.slice(0, 14).forEach((c) => {
    const fl = fileLine(c.codeTruth);
    md += `- **${clean(c.topic)}** (${c.id}, \`${docName(c.doc)}\`): the doc says “${trunc(c.docClaim, 140)}”, but the code ${trunc(c.codeTruth, 160)}${fl ? ' (`' + fl + '`)' : ''}.\n`;
  });
} else {
  md += '- No open conflicts remain — every conflicting claim has been resolved.\n';
}
md += '\n## Related\n\n';
md += 'Each discrepancy belongs to a code-truth Atlas domain — the trustworthy version of the same material. Link the relevant domain pages here.\n';

const outPath = path.join(ATLAS_ROOT, 'domains', 'reconciliation.md');
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, md);
console.error(`[reconcile] wrote ${path.relative(ATLAS_ROOT, outPath)} — ${disc.length} rows (${t('conflict')} conflict, ${t('stale')} stale, ${t('gap')} gap, ${t('ok')} ok, ${nResolved} resolved)`);
console.error(`[reconcile] now ensure the 'reconciliation' domain is in atlas.config.json and run build-atlas.mjs`);
