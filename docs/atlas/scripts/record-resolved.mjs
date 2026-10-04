#!/usr/bin/env node
/* ============================================================================
 * record-resolved.mjs — write/maintain the Atlas resolved ledger
 * (docs/atlas/.resolved.json), keyed by stable finding ID, so already-fixed
 * findings stay ✅ resolved across regenerations of the Reconciliation and
 * Documentation-Remediation pages (the renderers + resolve-findings.mjs read it).
 *
 * Zero-dependency (Node >= 16). Companion to resolve-findings.mjs.
 *
 * Usage:
 *   node record-resolved.mjs <ID> --in <commit> --note "<text>" [--kind reconcile|doc|audit] [--at YYYY-MM-DD]
 *   node record-resolved.mjs --reopen <ID>
 *   ATLAS_ROOT=docs/atlas node record-resolved.mjs RC-004 --in a1b2c3d --note "enforce 2FA"
 *
 * Ledger shape: { "<ID>": { resolvedIn, resolvedAt, kind, note }, ... } (key-sorted).
 * ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';

const ATLAS_ROOT = path.resolve(process.env.ATLAS_ROOT || 'docs/atlas');
const LEDGER = path.join(ATLAS_ROOT, '.resolved.json');

function parseArgs(argv) {
  const a = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--in') a.in = argv[++i];
    else if (t === '--note') a.note = argv[++i];
    else if (t === '--kind') a.kind = argv[++i];
    else if (t === '--at') a.at = argv[++i];
    else if (t === '--reopen') a.reopen = argv[++i];
    else a._.push(t);
  }
  return a;
}
function inferKind(id) {
  const p = (id.split('-')[0] || '').toUpperCase();
  if (p === 'RC') return 'reconcile';
  if (p === 'DOC') return 'doc';
  return 'audit';
}
function today() { return new Date().toISOString().slice(0, 10); } // standalone CLI — Date is fine
function loadLedger() {
  try { return JSON.parse(fs.readFileSync(LEDGER, 'utf8')); } catch { return {}; }
}
function saveLedger(led) {
  const sorted = {};
  Object.keys(led).sort().forEach((k) => { sorted[k] = led[k]; });
  fs.mkdirSync(path.dirname(LEDGER), { recursive: true });
  fs.writeFileSync(LEDGER, JSON.stringify(sorted, null, 2) + '\n');
}

const args = parseArgs(process.argv.slice(2));
const ledger = loadLedger();

if (args.reopen) {
  const id = String(args.reopen).toUpperCase();
  if (ledger[id]) { delete ledger[id]; saveLedger(ledger); console.error(`[resolved] reopened ${id} — removed from ${path.relative(process.cwd(), LEDGER)}`); }
  else console.error(`[resolved] ${id} not in ledger; nothing to reopen`);
  process.exit(0);
}

const id = String(args._[0] || '').toUpperCase();
if (!id || !/^[A-Z][A-Z0-9]*-\d+$/.test(id)) {
  console.error('usage: node record-resolved.mjs <ID> --in <commit> --note "<text>" [--kind ...] [--at YYYY-MM-DD]');
  console.error('       node record-resolved.mjs --reopen <ID>');
  process.exit(2);
}
if (!args.in || !args.note) {
  console.error('error: --in <commit> and --note "<text>" are required');
  process.exit(2);
}
ledger[id] = {
  resolvedIn: String(args.in),
  resolvedAt: args.at || today(),
  kind: args.kind || inferKind(id),
  note: String(args.note),
};
saveLedger(ledger);
console.error(`[resolved] recorded ${id} (${ledger[id].kind}) → ${path.relative(process.cwd(), LEDGER)} — resolvedIn ${ledger[id].resolvedIn}`);
