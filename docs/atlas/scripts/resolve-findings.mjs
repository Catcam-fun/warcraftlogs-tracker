#!/usr/bin/env node
/* ============================================================================
 * resolve-findings.mjs — resolve a finding-ID spec into the concrete findings
 * to remediate, pulled from the Atlas Reconciliation page and/or the Audit
 * Atlas. The atlas-remediate skill (and any workflow) uses this to know exactly
 * what to work on and where the cited code lives.
 *
 * Zero-dependency (Node >= 16). Reads the generated Markdown, not the HTML.
 *
 * Usage:
 *   node resolve-findings.mjs <spec>
 *   ATLAS_ROOT=docs/atlas AUDIT_ROOT=docs/audit node resolve-findings.mjs <spec>
 *
 * <spec> forms:
 *   RC-001                      one finding
 *   RC-001,RC-005,SEC-002       a list
 *   RC-001..RC-010              an inclusive range (same prefix)
 *   conflict | stale | gap | ok all reconcile findings of that verdict
 *   critical|high|medium|low|info  all audit findings of that severity
 *   all                         everything
 *
 * Emits JSON on stdout: { spec, count, findings: [ {id, kind, tag, source,
 *   location, locations[], title, detail} ] } and a human summary on stderr.
 * ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';

const ATLAS_ROOT = path.resolve(process.env.ATLAS_ROOT || 'docs/atlas');
const AUDIT_ROOT = path.resolve(process.env.AUDIT_ROOT || 'docs/audit');
const rawArgs = process.argv.slice(2);
const includeResolved = rawArgs.includes('--include-resolved');
const spec = (rawArgs.find((a) => !a.startsWith('--')) || '').trim();
if (!spec) { console.error('usage: node resolve-findings.mjs <spec> [--include-resolved]  (e.g. RC-001, RC-001..RC-010, conflict, high, all)'); process.exit(2); }

// resolved ledger — findings recorded here are already fixed
let ledger = {};
try { ledger = JSON.parse(fs.readFileSync(path.join(ATLAS_ROOT, '.resolved.json'), 'utf8')); } catch {}

const FILE_LINE = /([A-Za-z0-9_.\/\[\]-]+\.(?:ts|tsx|js|mjs|sql|tf|json|yml|yaml|py|go|rb|rs|php|java|cs|sh|md):\d+)/g;
const ROW = /^\|\s*([A-Z][A-Z0-9]*-\d+)\s*\{(\w+)\}\s*\|(.*)$/;   // | ID {token} | ...
const RECONCILE_VERDICTS = new Set(['conflict', 'stale', 'gap', 'ok']);
const DOC_VERDICTS = new Set(['remove', 'consolidate', 'keep']);     // documentation-remediation
const SEVERITIES = new Set(['critical', 'high', 'medium', 'low', 'info']);

function listMd(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  (function walk(d) {
    for (const n of fs.readdirSync(d)) {
      if (['build', 'scripts', 'assets'].includes(n)) continue;
      const p = path.join(d, n);
      const s = fs.statSync(p);
      if (s.isDirectory()) walk(p);
      else if (n.endsWith('.md')) out.push(p);
    }
  })(dir);
  return out;
}

/* pull the "### ID — ... " body block out of a page (audit detail), or the
 * reconcile gotcha bullet "- **...** (ID, ...)", capped. */
function detailFor(id, text) {
  const h = text.indexOf(`### ${id}`);
  if (h >= 0) {
    const rest = text.slice(h);
    const next = rest.slice(3).search(/\n##+\s/);
    return rest.slice(0, next >= 0 ? next + 3 : 1400).trim();
  }
  const re = new RegExp(`^-\\s+\\*\\*.*\\(${id}[,)].*$`, 'm');
  const m = text.match(re);
  return m ? m[0].trim() : '';
}

const findings = {};            // id -> finding
const sources = [
  { root: ATLAS_ROOT, kind: 'reconcile-or-atlas' },
  { root: AUDIT_ROOT, kind: 'audit' },
];
for (const { root, kind } of sources) {
  for (const file of listMd(root)) {
    const text = fs.readFileSync(file, 'utf8');
    const isHub = /\/hub\.md$/.test(file);
    for (const line of text.split(/\r?\n/)) {
      const m = line.match(ROW);
      if (!m) continue;
      const [, id, tag, restRaw] = m;
      // hub overview tables duplicate the per-area/reconcile rows but lack locations — skip if we already have a better record
      const rest = restRaw;
      const cells = rest.split('|').map((c) => c.trim());
      const locs = [...rest.matchAll(FILE_LINE)].map((x) => x[1]);
      const finalKind = RECONCILE_VERDICTS.has(tag) ? 'reconcile' : DOC_VERDICTS.has(tag) ? 'doc' : 'audit';
      const title = cells.find((c) => c && !/^\w+$/.test(c) && !c.startsWith('`')) || cells[cells.length - 1] || '';
      const prev = findings[id];
      // prefer a record that has a location / detail (area & reconcile pages) over the hub roll-up
      if (prev && (prev.locations.length || prev.detail) && (isHub || !locs.length)) continue;
      findings[id] = {
        id, kind: finalKind, tag,
        source: path.relative(process.cwd(), file),
        location: locs[0] || '',
        locations: locs,
        title: title.replace(/`/g, ''),
        detail: detailFor(id, text),
      };
    }
  }
}

for (const id of Object.keys(findings)) findings[id].resolved = ledger[id] || null;

/* ---- apply the spec ---- */
const ids = Object.keys(findings);
function pick() {
  const s = spec.toLowerCase();
  if (s === 'all') return ids;
  if (RECONCILE_VERDICTS.has(s) || DOC_VERDICTS.has(s)) return ids.filter((i) => findings[i].tag === s);
  if (SEVERITIES.has(s)) return ids.filter((i) => findings[i].tag.toLowerCase() === s);
  if (/\.\./.test(spec)) {                                   // range RC-001..RC-010
    const [a, b] = spec.split('..').map((x) => x.trim());
    const pa = a.match(/^([A-Z][A-Z0-9]*)-(\d+)$/i), pb = b.match(/^([A-Z][A-Z0-9]*)-(\d+)$/i);
    if (pa && pb && pa[1].toUpperCase() === pb[1].toUpperCase()) {
      const pre = pa[1].toUpperCase(), lo = +pa[2], hi = +pb[2];
      return ids.filter((i) => { const mm = i.match(/^([A-Z][A-Z0-9]*)-(\d+)$/); return mm && mm[1] === pre && +mm[2] >= lo && +mm[2] <= hi; });
    }
    return [];
  }
  // comma list / single
  const want = new Set(spec.split(',').map((x) => x.trim().toUpperCase()));
  return ids.filter((i) => want.has(i.toUpperCase()));
}
const picked = pick().sort();
const openIds = includeResolved ? picked : picked.filter((i) => !findings[i].resolved);
const resolvedIds = picked.filter((i) => findings[i].resolved);
const result = {
  spec,
  count: openIds.length,
  unresolved: spec.includes(',') ? spec.split(',').map((x) => x.trim().toUpperCase()).filter((w) => !findings[w]) : [],
  findings: openIds.map((i) => findings[i]),
  resolved: resolvedIds.map((i) => findings[i]),
};
process.stdout.write(JSON.stringify(result, null, 2) + '\n');

console.error(`\n[resolve] spec "${spec}" → ${openIds.length} open finding(s)${resolvedIds.length ? `, ${resolvedIds.length} already resolved` : ''} (of ${ids.length} known)`);
openIds.forEach((i) => { const f = findings[i]; console.error(`  ${f.id} [${f.tag}/${f.kind}] ${f.title.slice(0, 64)}  ${f.location ? '@ ' + f.location : ''}`); });
resolvedIds.forEach((i) => { const f = findings[i]; console.error(`  ${f.id} ✅ resolved in ${f.resolved.resolvedIn}${includeResolved ? ' (included)' : ' (skipped)'}`); });
if (result.unresolved.length) console.error(`  UNRESOLVED ids: ${result.unresolved.join(', ')}`);
console.error('');
