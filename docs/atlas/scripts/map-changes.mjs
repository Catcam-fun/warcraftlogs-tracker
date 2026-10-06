#!/usr/bin/env node
/* ============================================================================
 * map-changes.mjs — given a set of changed code files, find which Atlas pages
 * reference them, so an incremental update touches only what actually moved.
 *
 * Zero-dependency (Node >= 16, node:fs/path only). Companion to project-atlas's
 * build-atlas.mjs / verify-atlas.mjs.
 *
 * Usage:
 *   ATLAS_ROOT=docs/atlas node map-changes.mjs <changed-file> [<changed-file> ...]
 *   git diff --name-only <A>..<B> | ATLAS_ROOT=docs/atlas node map-changes.mjs
 *   git diff --name-only HEAD       | ATLAS_ROOT=docs/atlas node map-changes.mjs   # working tree
 *
 * It reads each page's frontmatter `anchors:` (the file:line citations) plus the
 * domain folder layout, and emits JSON on stdout:
 *   - affectedPages : pages whose anchors reference a changed file (hard) or a
 *                     file in the same directory as one of its anchors (soft/dir)
 *   - pagesByFile   : changed file -> [page ids]
 *   - unmatchedFiles: changed code files no page references (candidate NEW pages)
 *   - a human summary on stderr.
 *
 * Heuristic, not authoritative: it proposes the work-list; the agent decides.
 * ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';

const ATLAS_ROOT = process.env.ATLAS_ROOT
  ? path.resolve(process.env.ATLAS_ROOT)
  : path.resolve(process.cwd(), 'docs/atlas');

/* ---- collect the changed-file list (argv first, else stdin) ---- */
function readStdin() {
  try { return fs.readFileSync(0, 'utf8'); } catch { return ''; }
}
let changed = process.argv.slice(2).filter(Boolean);
if (!changed.length) {
  changed = readStdin().split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}
// normalize: strip leading ./, ignore the atlas's own generated output + the docs themselves
const ATLAS_REL = path.relative(process.cwd(), ATLAS_ROOT) || '.';
changed = changed
  .map((f) => f.replace(/^\.\//, ''))
  .filter((f) => !f.startsWith(path.join(ATLAS_REL, 'build')))
  .filter((f) => f !== path.join(ATLAS_REL, 'agent-index.md'));

if (!fs.existsSync(ATLAS_ROOT)) {
  console.error(`[map-changes] No atlas at ${ATLAS_ROOT}. Set ATLAS_ROOT or run project-atlas first.`);
  process.exit(2);
}

/* ---- minimal frontmatter parse: id, title, status, axis, anchors{}, links[] ---- */
function parsePage(absPath, relPath) {
  const raw = fs.readFileSync(absPath, 'utf8');
  const m = raw.match(/^---\n([\s\S]*?)\n---/);
  const fm = m ? m[1] : '';
  const lines = fm.split(/\r?\n/);
  const out = { id: null, title: null, status: null, axis: null, anchors: {}, links: [], mdPath: relPath };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let mm;
    if ((mm = line.match(/^id:\s*(.+?)\s*$/))) out.id = unquote(mm[1]);
    else if ((mm = line.match(/^title:\s*(.+?)\s*$/))) out.title = unquote(mm[1]);
    else if ((mm = line.match(/^status:\s*(.+?)\s*$/))) out.status = unquote(mm[1]);
    else if ((mm = line.match(/^axis:\s*(.+?)\s*$/))) out.axis = unquote(mm[1]);
    else if (/^links:\s*$/.test(line)) {
      // block list
      for (let j = i + 1; j < lines.length && /^\s+-\s+/.test(lines[j]); j++) {
        out.links.push(unquote(lines[j].replace(/^\s+-\s+/, '').trim()));
      }
    } else if ((mm = line.match(/^links:\s*\[(.*)\]\s*$/))) {
      out.links = mm[1].split(',').map((s) => unquote(s.trim())).filter(Boolean);
    } else if (/^anchors:\s*$/.test(line)) {
      // block map of key: file:line
      for (let j = i + 1; j < lines.length && /^\s+\S/.test(lines[j]); j++) {
        const a = lines[j].match(/^\s+([\w.-]+):\s*(.+?)\s*$/);
        if (a) out.anchors[a[1]] = unquote(a[2]);
      }
    }
  }
  if (!out.id) out.id = relPath.replace(/^domains[\/]/, '').replace(/\.md$/, '').replace(/\//g, '-');
  return out;
}
function unquote(s) { return s.replace(/^["']|["']$/g, ''); }

/* ---- gather all pages (hub + domains tree) ---- */
function walk(dir, acc) {
  if (!fs.existsSync(dir)) return acc;
  for (const name of fs.readdirSync(dir).sort()) {
    const abs = path.join(dir, name);
    const st = fs.statSync(abs);
    if (st.isDirectory()) walk(abs, acc);
    else if (name.endsWith('.md')) acc.push(abs);
  }
  return acc;
}
const domainsDir = path.join(ATLAS_ROOT, 'domains');
const hubMd = path.join(ATLAS_ROOT, 'hub.md');
const pageFiles = [];
if (fs.existsSync(hubMd)) pageFiles.push(hubMd);
walk(domainsDir, pageFiles);

const pages = pageFiles.map((abs) => parsePage(abs, path.relative(ATLAS_ROOT, abs)));

/* anchor file (strip :line) -> normalized repo-relative path */
function anchorFile(v) { return v.split(':')[0].replace(/^\.\//, '').trim(); }

/* index: file -> pages, dir -> pages */
const byFile = new Map();
const byDir = new Map();
for (const p of pages) {
  const seenFiles = new Set();
  for (const v of Object.values(p.anchors)) {
    const f = anchorFile(v);
    if (!f || seenFiles.has(f)) continue;
    seenFiles.add(f);
    (byFile.get(f) || byFile.set(f, []).get(f)).push(p);
    const d = path.dirname(f);
    (byDir.get(d) || byDir.set(d, []).get(d)).push(p);
  }
  p._files = [...seenFiles];
}

/* ---- map each changed file ---- */
const pagesByFile = {};
const affected = new Map(); // id -> { page, reason, files:Set }
const unmatched = [];

function touch(page, file, reason) {
  let a = affected.get(page.id);
  if (!a) { a = { page, reason, files: new Set() }; affected.set(page.id, a); }
  a.files.add(file);
  if (reason === 'anchor') a.reason = 'anchor'; // hard beats soft
}

for (const f of changed) {
  const hard = byFile.get(f) || [];
  const soft = (byDir.get(path.dirname(f)) || []).filter((p) => !hard.includes(p));
  const ids = [];
  for (const p of hard) { touch(p, f, 'anchor'); ids.push(p.id); }
  for (const p of soft) { touch(p, f, 'dir'); if (!ids.includes(p.id)) ids.push(p.id); }
  if (ids.length) pagesByFile[f] = ids;
  else unmatched.push(f);
}

const affectedPages = [...affected.values()].map((a) => ({
  id: a.page.id,
  title: a.page.title,
  mdPath: a.page.mdPath,
  status: a.page.status,
  axis: a.page.axis || 'layer',
  reason: a.reason,            // 'anchor' (direct hit) or 'dir' (same-module change)
  files: [...a.files],
})).sort((x, y) => (x.reason === y.reason ? 0 : x.reason === 'anchor' ? -1 : 1));

const result = {
  atlasRoot: ATLAS_ROOT,
  changedFiles: changed.length,
  pageCount: pages.length,
  affectedPages,
  pagesByFile,
  unmatchedFiles: unmatched,
};

process.stdout.write(JSON.stringify(result, null, 2) + '\n');

/* human summary -> stderr */
const direct = affectedPages.filter((p) => p.reason === 'anchor');
const near = affectedPages.filter((p) => p.reason === 'dir');
console.error(`\n[map-changes] ${changed.length} changed file(s) vs ${pages.length} atlas page(s)`);
console.error(`  ${direct.length} page(s) directly cite a changed file:`);
direct.forEach((p) => console.error(`    • ${p.id} (${p.mdPath})  ← ${p.files.join(', ')}`));
if (near.length) {
  console.error(`  ${near.length} page(s) in the same module as a change (review):`);
  near.forEach((p) => console.error(`    • ${p.id} (${p.mdPath})`));
}
if (unmatched.length) {
  console.error(`  ${unmatched.length} changed file(s) no page references — candidate NEW pages/domains:`);
  unmatched.slice(0, 40).forEach((f) => console.error(`    + ${f}`));
  if (unmatched.length > 40) console.error(`    … and ${unmatched.length - 40} more`);
}
console.error('');
