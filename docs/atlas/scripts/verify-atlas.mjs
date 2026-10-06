#!/usr/bin/env node
/**
 * verify-atlas.mjs — Project Atlas sync checker (zero dependencies).
 *
 * Recomputes each .md body hash and compares it to the stamped frontmatter hash,
 * checks the expected generated .html exists, and checks the hash embedded in the
 * .html matches the recomputed body hash (so a hand-edited .html is caught).
 *
 * Exit 0 = in sync. Exit 1 = drift, with a clear per-page report.
 *
 * Usage:
 *   node verify-atlas.mjs
 *   ATLAS_ROOT=/path/to/docs/atlas node verify-atlas.mjs
 *
 * node:fs / node:path / node:crypto ONLY.
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const ATLAS_ROOT = process.env.ATLAS_ROOT
  ? path.resolve(process.env.ATLAS_ROOT)
  : path.resolve(process.cwd(), 'docs/atlas');

function fail(msg) { console.error(msg); }

function loadConfig() {
  const p = path.join(ATLAS_ROOT, 'atlas.config.json');
  if (!fs.existsSync(p)) {
    fail(`[verify] No atlas.config.json at ${p}`);
    process.exit(1);
  }
  const cfg = JSON.parse(fs.readFileSync(p, 'utf8'));
  cfg.paths = cfg.paths || {};
  cfg._root = ATLAS_ROOT;
  cfg._domainsDir = path.join(ATLAS_ROOT, cfg.paths.domains || 'domains');
  cfg._buildDir = path.join(ATLAS_ROOT, cfg.paths.build || 'build');
  cfg._hubMd = path.join(ATLAS_ROOT, cfg.paths.hub || 'hub.md');
  cfg.options = cfg.options || {};
  if (cfg.options.search == null) cfg.options.search = true;
  return cfg;
}

function splitFrontmatter(raw) {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!m) return { fm: '', body: raw };
  return { fm: m[1], body: m[2] };
}
function stampedHash(fm) {
  const m = fm.match(/^content_hash:\s*(\S+)\s*$/m);
  return m ? m[1] : null;
}
function normalizeBody(body) {
  return body.replace(/\r\n/g, '\n').split('\n').map((l) => l.replace(/\s+$/, '')).join('\n').replace(/\n+$/, '') + '\n';
}
function hashBody(body) {
  return 'sha256:' + crypto.createHash('sha256').update(normalizeBody(body), 'utf8').digest('hex');
}

function htmlRelFor(relPath) {
  return relPath.replace(/^domains[\/\\]/, '').replace(/\.md$/, '.html');
}

function embeddedHtmlHash(html) {
  const m = html.match(/<meta name="atlas-content-hash" content="([^"]*)"/);
  return m ? m[1] : null;
}
function embeddedIntegrity(html) {
  const m = html.match(/<meta name="atlas-html-integrity" content="([^"]*)"/);
  return m ? m[1] : null;
}
/* recompute the HTML self-integrity hash: blank the integrity field, hash the rest.
 * Mirrors build-atlas.mjs exactly. A mismatch means the .html was hand-edited. */
function recomputeIntegrity(html) {
  const blanked = html.replace(/(<meta name="atlas-html-integrity" content=")[^"]*(">)/, '$1$2');
  return 'sha256:' + crypto.createHash('sha256').update(blanked, 'utf8').digest('hex');
}

function walkDomains(cfg) {
  const out = [];
  if (!fs.existsSync(cfg._domainsDir)) return out;
  function walk(dir, rel) {
    for (const name of fs.readdirSync(dir).sort()) {
      const abs = path.join(dir, name);
      if (fs.statSync(abs).isDirectory()) walk(abs, path.join(rel, name));
      else if (name.endsWith('.md')) out.push({ abs, relPath: path.join('domains', rel, name) });
    }
  }
  walk(cfg._domainsDir, '');
  return out;
}

function main() {
  const cfg = loadConfig();
  const problems = [];
  let checked = 0;

  const mdFiles = [];
  if (fs.existsSync(cfg._hubMd)) mdFiles.push({ abs: cfg._hubMd, relPath: 'hub.md', html: 'index.html' });
  else problems.push(`hub.md missing at ${cfg._hubMd}`);
  for (const d of walkDomains(cfg)) mdFiles.push({ abs: d.abs, relPath: d.relPath, html: htmlRelFor(d.relPath) });

  for (const f of mdFiles) {
    checked++;
    const raw = fs.readFileSync(f.abs, 'utf8');
    const { fm, body } = splitFrontmatter(raw);
    const recomputed = hashBody(body);
    const stamped = stampedHash(fm);

    if (!stamped) {
      problems.push(`STALE  ${f.relPath}: no content_hash stamped — run build-atlas.mjs.`);
    } else if (stamped !== recomputed) {
      problems.push(`STALE  ${f.relPath}: body changed since last build.\n         stamped:    ${stamped}\n         recomputed: ${recomputed}\n         -> run build-atlas.mjs and commit both files.`);
    }

    // html existence + embedded-hash match
    const htmlPath = path.join(cfg._buildDir, f.html);
    if (!fs.existsSync(htmlPath)) {
      problems.push(`MISSING ${f.relPath}: expected HTML not found at ${path.relative(cfg._root, htmlPath)} — run build-atlas.mjs.`);
    } else {
      const html = fs.readFileSync(htmlPath, 'utf8');
      const embedded = embeddedHtmlHash(html);
      if (embedded == null) {
        problems.push(`HAND-EDIT ${f.html}: no embedded atlas-content-hash — file may have been hand-edited or built by an older generator.`);
      } else if (embedded !== recomputed) {
        problems.push(`STALE  ${f.html}: embedded content hash does not match the markdown body.\n         html:     ${embedded}\n         markdown: ${recomputed}\n         -> the .md changed without a rebuild. Edit the .md and run build-atlas.mjs.`);
      }
      // self-integrity: catches ANY hand-edit to the generated HTML itself
      const integrity = embeddedIntegrity(html);
      if (integrity == null) {
        problems.push(`HAND-EDIT ${f.html}: no embedded atlas-html-integrity — built by an older generator or hand-edited.`);
      } else if (integrity !== recomputeIntegrity(html)) {
        problems.push(`HAND-EDIT ${f.html}: the generated HTML was modified by hand.\n         -> Never edit HTML by hand. Edit ${f.relPath} and run build-atlas.mjs.`);
      }
    }
  }

  if (cfg.options.search !== false) {
    const idxPath = path.join(cfg._buildDir, 'search-index.js');
    if (!fs.existsSync(idxPath)) {
      problems.push(`MISSING search-index.js: expected at ${path.relative(cfg._root, idxPath)} — run build-atlas.mjs.`);
    }
  }

  if (problems.length) {
    console.error(`\n[verify] FAIL — ${problems.length} issue(s) across ${checked} page(s):\n`);
    problems.forEach((p) => console.error('  • ' + p));
    console.error(`\n[verify] The Atlas HTML is out of sync with its canonical markdown.`);
    process.exit(1);
  }

  console.log(`[verify] OK — ${checked} page(s) in sync (markdown hashes match stamped + embedded HTML hashes).`);
  process.exit(0);
}

main();
