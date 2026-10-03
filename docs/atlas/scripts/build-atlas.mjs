#!/usr/bin/env node
/**
 * build-atlas.mjs — Project Atlas static-site generator (zero dependencies).
 *
 * Turns canonical Markdown (hub.md + domains/** /*.md) into a styled, interactive
 * "Project Atlas": a HUB page + DOMAIN LANDING pages + deep SUB-PAGES, for humans
 * (rich HTML) and agents (the markdown itself + agent-index.md).
 *
 * Usage:
 *   node build-atlas.mjs                 # config at docs/atlas/atlas.config.json (default)
 *   ATLAS_ROOT=/path/to/docs/atlas node build-atlas.mjs
 *
 * Pipeline: loadConfig -> read pages -> parseFrontmatter -> splitSections ->
 *           parseBlocks -> SECTION renderers -> assemble page -> stamp hash -> write.
 *
 * node:fs / node:path / node:url / node:crypto ONLY.
 */

import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import crypto from 'node:crypto';

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));

/* ============================================================================
 * 0. Paths & config
 * ========================================================================== */

const ATLAS_ROOT = process.env.ATLAS_ROOT
  ? path.resolve(process.env.ATLAS_ROOT)
  : path.resolve(process.cwd(), 'docs/atlas');

const TEMPLATE_PATH = path.resolve(__dirname, '..', 'assets', 'template.html');

function loadConfig() {
  const configPath = path.join(ATLAS_ROOT, 'atlas.config.json');
  if (!fs.existsSync(configPath)) {
    fail(`No atlas.config.json found at ${configPath}\n` +
      `Set ATLAS_ROOT or run from a project with docs/atlas/atlas.config.json.`);
  }
  let cfg;
  try {
    cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  } catch (e) {
    fail(`atlas.config.json is not valid JSON: ${e.message}`);
  }
  cfg.brand = cfg.brand || {};
  cfg.paths = cfg.paths || {};
  cfg.options = cfg.options || {};
  cfg.flows = cfg.flows || [];
  cfg.environments = cfg.environments || [];
  cfg.domains = cfg.domains || [];
  cfg.nav = cfg.nav || {};
  // resolve dir paths relative to ATLAS_ROOT
  cfg._root = ATLAS_ROOT;
  cfg._domainsDir = path.join(ATLAS_ROOT, cfg.paths.domains || 'domains');
  cfg._buildDir = path.join(ATLAS_ROOT, cfg.paths.build || 'build');
  cfg._hubMd = path.join(ATLAS_ROOT, cfg.paths.hub || 'hub.md');
  if (cfg.options.maxDepth == null) cfg.options.maxDepth = 3;
  if (cfg.options.agentIndex == null) cfg.options.agentIndex = true;
  if (cfg.options.search == null) cfg.options.search = true;
  return cfg;
}

function fail(msg) {
  console.error('\n[project-atlas] BUILD FAILED');
  console.error(msg);
  process.exit(1);
}

/* ============================================================================
 * 1. HTML escaping & small helpers
 * ========================================================================== */

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function escAttr(s) { return esc(s).replace(/'/g, '&#39;'); }
function slugify(s) {
  return String(s).toLowerCase().trim()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'section';
}

/* color class helper: map a semantic / status / short colour name to a card class */
function colorClass(name) {
  switch (name) {
    case 'process': case 'blue': return 'c-blue';
    case 'safe': case 'documented': case 'green': return 'c-green';
    case 'caution': case 'needs-update': case 'amber': return 'c-amber';
    case 'never': case 'red': return 'c-red';
    case 'structural': case 'teal': default: return 'c-teal';
  }
}

/* ============================================================================
 * 2. Frontmatter + section parsing
 * ========================================================================== */

/**
 * Split a raw .md into { frontmatter (raw string), body }.
 */
function splitFrontmatter(raw) {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!m) return { fm: '', body: raw };
  return { fm: m[1], body: m[2] };
}

/**
 * A deliberately small, robust YAML-ish parser. Supports:
 *   key: value
 *   key:
 *     - item
 *     - item
 *   key:
 *     subkey: value         (one level of nested map -> object)
 * Values: strings (optionally quoted), [inline, arrays], numbers.
 * It is NOT general YAML; it covers the frontmatter schema documented in the spec.
 */
function parseFrontmatter(fm) {
  const out = {};
  const lines = fm.split(/\r?\n/);
  let i = 0;
  function unquote(v) {
    v = v.trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      return v.slice(1, -1);
    }
    return v;
  }
  function parseScalar(v) {
    v = v.trim();
    if (v === '') return '';
    if (v.startsWith('[') && v.endsWith(']')) {
      const inner = v.slice(1, -1).trim();
      if (!inner) return [];
      return inner.split(',').map((s) => unquote(s));
    }
    if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
    if (v === 'true') return true;
    if (v === 'false') return false;
    return unquote(v);
  }
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim() || line.trim().startsWith('#')) { i++; continue; }
    const km = line.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
    if (!km) { i++; continue; }
    const key = km[1];
    const rest = km[2];
    if (rest.trim() !== '') {
      out[key] = parseScalar(rest);
      i++;
      continue;
    }
    // block: peek next lines for list items or nested map
    const items = [];
    const map = {};
    let isList = false, isMap = false;
    let j = i + 1;
    while (j < lines.length) {
      const l = lines[j];
      if (!l.trim()) { j++; continue; }
      const indent = l.match(/^(\s*)/)[1].length;
      if (indent === 0) break;
      const li = l.trim();
      if (li.startsWith('- ')) {
        isList = true;
        items.push(unquote(li.slice(2)));
      } else {
        const mm = li.match(/^([A-Za-z0-9_./-]+):\s*(.*)$/);
        if (mm) { isMap = true; map[mm[1]] = parseScalar(mm[2]); }
      }
      j++;
    }
    if (isList) out[key] = items;
    else if (isMap) out[key] = map;
    else out[key] = '';
    i = j;
  }
  return out;
}

/**
 * splitSections: divide the markdown body into "## Heading" blocks.
 * Returns [{ heading, raw }] in document order. Content before the first
 * "## " heading is captured under heading "" (lead).
 */
function splitSections(body) {
  const lines = body.split(/\r?\n/);
  const sections = [];
  let cur = { heading: '', lines: [] };
  let inFence = false;
  for (const line of lines) {
    if (/^```/.test(line)) inFence = !inFence;
    const hm = !inFence && line.match(/^##\s+(.+?)\s*$/);
    if (hm && !line.startsWith('###')) {
      if (cur.heading || cur.lines.some((l) => l.trim())) sections.push(cur);
      cur = { heading: hm[1].trim(), lines: [] };
    } else {
      cur.lines.push(line);
    }
  }
  if (cur.heading || cur.lines.some((l) => l.trim())) sections.push(cur);
  return sections.map((s) => ({ heading: s.heading, raw: s.lines.join('\n') }));
}

/* extract a fenced code block of a given "info string" (lang). Returns the
 * inner text or null. e.g. fencedBlock(raw, 'steps') -> contents of ```steps ... ``` */
function fencedBlock(raw, lang) {
  const re = new RegExp('```' + lang + '\\s*\\n([\\s\\S]*?)\\n```', 'm');
  const m = raw.match(re);
  return m ? m[1] : null;
}

/* remove a fenced block (so it isn't double-rendered as prose) */
function stripFenced(raw, lang) {
  const re = new RegExp('```' + lang + '\\s*\\n[\\s\\S]*?\\n```\\n?', 'm');
  return raw.replace(re, '');
}

/* ============================================================================
 * 3. Inline + block markdown renderer (hand-rolled)
 * ========================================================================== */

const GLOSSARY = {}; // term(lowercased) -> definition, populated per-page for tooltips

/** inline: **bold** *italic* `code` [text](url) [[wikilink]] */
function inline(text, ctx) {
  ctx = ctx || {};
  // protect code spans first
  const codes = [];
  let s = text.replace(/`([^`]+)`/g, (_, c) => {
    codes.push(c);
    return ` CODE${codes.length - 1} `;
  });
  s = esc(s);
  // links [text](url)
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, href) => {
    return `<a class="inline" href="${escAttr(href)}">${t}</a>`;
  });
  // wikilinks [[id]] or [[id|label]]
  s = s.replace(/\[\[([^\]]+)\]\]/g, (_, body) => {
    const parts = body.split('|');
    const id = parts[0].trim();
    const label = (parts[1] || id).trim();
    const target = ctx.linkResolver ? ctx.linkResolver(id) : null;
    if (target) return `<a class="inline" href="${escAttr(target)}">${esc(label)}</a>`;
    return `<span class="term" title="unlinked: ${escAttr(id)}">${esc(label)}</span>`;
  });
  // bold then italic
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  // glossary terms: wrap any known term not already inside a tag
  // restore code spans
  s = s.replace(/ CODE(\d+) /g, (_, n) => `<code>${esc(codes[Number(n)])}</code>`);
  return s;
}

/**
 * parseBlocks: turn a chunk of markdown into HTML blocks.
 * Handles: paragraphs, headings (###/####), ul/ol lists, fenced code,
 * tables (| .. |), blockquotes (>). Returns HTML string.
 */
function parseBlocks(raw, ctx) {
  ctx = ctx || {};
  const lines = raw.split(/\r?\n/);
  let html = '';
  let i = 0;
  let para = [];
  function flushPara() {
    if (para.length) {
      const text = para.join(' ').trim();
      if (text) html += `<p>${inline(text, ctx)}</p>\n`;
      para = [];
    }
  }
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // fenced code
    if (/^```/.test(trimmed)) {
      flushPara();
      const langInfo = trimmed.replace(/^```/, '').trim();
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i].trim())) { buf.push(lines[i]); i++; }
      i++; // closing fence
      // known structured langs handled by section renderers; render others as code
      html += `<pre class="code" data-lang="${escAttr(langInfo)}">${esc(buf.join('\n'))}</pre>\n`;
      continue;
    }

    // headings
    const h = trimmed.match(/^(#{3,4})\s+(.+)$/);
    if (h) {
      flushPara();
      const level = h[1].length;
      html += `<h${level === 3 ? 4 : 5}>${inline(h[2], ctx)}</h${level === 3 ? 4 : 5}>\n`;
      i++;
      continue;
    }

    // table: header row followed by separator row of dashes
    if (/^\|.*\|/.test(trimmed) && i + 1 < lines.length && /^\|[\s:|-]+\|/.test(lines[i + 1].trim())) {
      flushPara();
      html += renderTable(lines, i, ctx).html;
      i = renderTable(lines, i, ctx).next;
      continue;
    }

    // blockquote
    if (/^>\s?/.test(trimmed)) {
      flushPara();
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
        buf.push(lines[i].trim().replace(/^>\s?/, ''));
        i++;
      }
      html += `<blockquote>${parseBlocks(buf.join('\n'), ctx)}</blockquote>\n`;
      continue;
    }

    // unordered list
    if (/^[-*]\s+/.test(trimmed)) {
      flushPara();
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ''));
        i++;
      }
      html += '<ul class="clean">' + items.map((it) => `<li>${inline(it, ctx)}</li>`).join('') + '</ul>\n';
      continue;
    }

    // ordered list
    if (/^\d+\.\s+/.test(trimmed)) {
      flushPara();
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
        i++;
      }
      html += '<ol class="clean">' + items.map((it) => `<li>${inline(it, ctx)}</li>`).join('') + '</ol>\n';
      continue;
    }

    // blank line -> paragraph break
    if (trimmed === '') { flushPara(); i++; continue; }

    para.push(trimmed);
    i++;
  }
  flushPara();
  return html;
}

function renderTable(lines, start, ctx) {
  const headerCells = splitRow(lines[start]);
  let i = start + 2; // skip header + separator
  const rows = [];
  while (i < lines.length && /^\|.*\|/.test(lines[i].trim())) {
    rows.push(splitRow(lines[i]));
    i++;
  }
  let html = '<table class="matrix"><thead><tr>';
  html += headerCells.map((c) => `<th>${inline(c, ctx)}</th>`).join('');
  html += '</tr></thead><tbody>';
  for (const r of rows) {
    html += '<tr>' + r.map((c) => `<td>${inline(c, ctx)}</td>`).join('') + '</tr>';
  }
  html += '</tbody></table>\n';
  return { html, next: i };
}
function splitRow(line) {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|')) t = t.slice(0, -1);
  return t.split('|').map((c) => c.trim());
}

/* ============================================================================
 * 4. Structured diagram renderer (```diagram block -> auto-laid-out SVG)
 *
 * Diagram schema (one directive per line):
 *   lane <id> <Label...>           # a horizontal swimlane (rendered top->bottom)
 *   node <id> [lane=<laneId>] [color=process|safe|caution|never|structural] "Title" "subtitle"
 *   edge <from> -> <to> [color=...] "label"
 *   band <color> "Label"           # a full-width cross-cutting band (drawn behind)
 * Nodes without a lane fall into a default lane. Nodes are auto-placed left->right
 * in the order declared within each lane. Edges are drawn as orthogonal-ish paths.
 * ========================================================================== */

function parseDiagram(text) {
  const lanes = [];          // {id, label}
  const laneById = {};
  const nodes = [];          // {id, lane, color, title, sub}
  const nodeById = {};
  const edges = [];          // {from, to, color, label}
  const bands = [];          // {color, label}
  function quoted(str) {
    const out = [];
    const re = /"([^"]*)"/g; let m;
    while ((m = re.exec(str))) out.push(m[1]);
    return out;
  }
  for (let line of text.split(/\r?\n/)) {
    line = line.trim();
    if (!line || line.startsWith('#')) continue;
    const [, kw, rest = ''] = line.match(/^(\w+)\s*(.*)$/) || [];
    if (kw === 'lane') {
      const lm = rest.match(/^(\S+)\s+(.*)$/);
      if (lm) {
        const lane = { id: lm[1], label: lm[2].replace(/^"|"$/g, '') };
        lanes.push(lane); laneById[lane.id] = lane;
      }
    } else if (kw === 'node') {
      const idm = rest.match(/^(\S+)\s*(.*)$/);
      if (!idm) continue;
      const id = idm[1];
      const attrsAndText = idm[2];
      const lane = (attrsAndText.match(/lane=(\S+)/) || [])[1] || null;
      const color = (attrsAndText.match(/color=(\w+)/) || [])[1] || null;
      const q = quoted(attrsAndText);
      const node = { id, lane, color, title: q[0] || id, sub: q[1] || '' };
      nodes.push(node); nodeById[id] = node;
    } else if (kw === 'edge') {
      const em = rest.match(/^(\S+)\s*->\s*(\S+)\s*(.*)$/);
      if (!em) continue;
      const color = (em[3].match(/color=(\w+)/) || [])[1] || 'process';
      const q = quoted(em[3]);
      edges.push({ from: em[1], to: em[2], color, label: q[0] || '' });
    } else if (kw === 'band') {
      const bm = rest.match(/^(\w+)\s*(.*)$/);
      if (bm) bands.push({ color: bm[1], label: quoted(bm[2])[0] || bm[2] });
    }
  }
  // default lane for orphan nodes
  if (nodes.some((n) => !n.lane)) {
    const def = { id: '__default', label: '' };
    if (!laneById['__default']) { lanes.unshift(def); laneById['__default'] = def; }
    nodes.forEach((n) => { if (!n.lane) n.lane = '__default'; });
  }
  return { lanes, laneById, nodes, nodeById, edges, bands };
}

/* wrap a label into <=maxLines lines of <=maxChars, breaking on spaces (and inside
 * over-long tokens on '/' or hard-slicing); ellipsizes if it still overflows. Keeps
 * SVG node/edge text inside its box instead of overflowing into neighbours. */
function wrapLabel(str, maxChars, maxLines) {
  str = String(str == null ? '' : str).trim();
  if (!str) return [''];
  let toks = str.split(/\s+/).flatMap((t) => (t.length > maxChars ? t.split(/(?<=\/)/) : [t]));
  toks = toks.flatMap((t) => {
    if (t.length <= maxChars) return [t];
    const parts = []; for (let i = 0; i < t.length; i += maxChars) parts.push(t.slice(i, i + maxChars));
    return parts;
  });
  const lines = []; let cur = '';
  for (const t of toks) {
    const cand = cur ? cur + ' ' + t : t;
    if (!cur || cand.length <= maxChars) cur = cand;
    else { lines.push(cur); cur = t; }
  }
  if (cur) lines.push(cur);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    let last = kept[maxLines - 1];
    if (last.length > maxChars - 1) last = last.slice(0, maxChars - 1).replace(/\s+\S*$/, '');
    kept[maxLines - 1] = last.replace(/[\s/]+$/, '') + '…';
    return kept;
  }
  return lines;
}

function renderDiagramSVG(spec) {
  const NODE_W = 168, GAP_X = 52, GAP_Y = 86;
  const PAD_X = 24, LANE_LABEL_H = 22, TOP = 16;
  const TITLE_MAX = 22, EDGE_MAX = 18;
  const TLH = 14, SUBH = 11, PADV = 11, SUBGAP = 4;

  // pre-wrap node titles, then size every node to the tallest (keeps lanes aligned)
  spec.nodes.forEach((n) => { n._lines = wrapLabel(n.title, TITLE_MAX, 3); });
  const maxLines = Math.max(1, ...spec.nodes.map((n) => n._lines.length));
  const anySub = spec.nodes.some((n) => n.sub);
  const NODE_H = PADV * 2 + maxLines * TLH + (anySub ? SUBGAP + SUBH : 0);

  // position nodes per lane
  const lanesUsed = spec.lanes.filter((l) => spec.nodes.some((n) => n.lane === l.id));
  const layout = {}; // nodeId -> {x,y,w,h}
  let maxCols = 0;
  lanesUsed.forEach((lane, li) => {
    const laneNodes = spec.nodes.filter((n) => n.lane === lane.id);
    maxCols = Math.max(maxCols, laneNodes.length);
    const y = TOP + li * (NODE_H + GAP_Y) + LANE_LABEL_H;
    laneNodes.forEach((n, ci) => {
      const x = PAD_X + ci * (NODE_W + GAP_X);
      layout[n.id] = { x, y, w: NODE_W, h: NODE_H };
    });
  });
  const width = PAD_X * 2 + maxCols * NODE_W + (maxCols - 1) * GAP_X;
  const height = TOP + lanesUsed.length * (NODE_H + GAP_Y) + LANE_LABEL_H;
  const W = Math.max(width, 720);

  let svg = `<svg viewBox="0 0 ${W} ${height}" role="img" preserveAspectRatio="xMinYMin meet" aria-label="Structured diagram">`;
  // arrow markers
  svg += `<defs>`;
  ['process', 'safe', 'caution', 'never', 'structural'].forEach((c) => {
    const fill = { process: 'var(--blue)', safe: 'var(--green)', caution: 'var(--amber)', never: 'var(--red)', structural: 'var(--teal)' }[c];
    svg += `<marker id="arr-${c}" markerWidth="9" markerHeight="9" refX="7" refY="3.2" orient="auto"><path d="M0,0 L7,3.2 L0,6.4 Z" fill="${fill}"/></marker>`;
  });
  svg += `</defs>`;

  // cross-cutting bands (drawn behind, full width)
  const bandColor = { process: 'var(--blue)', safe: 'var(--green)', caution: 'var(--amber)', never: 'var(--red)', structural: 'var(--teal)' };
  spec.bands.forEach((b, bi) => {
    const by = TOP + 2 + bi * 4;
    svg += `<rect x="6" y="${by}" width="${W - 12}" height="${height - by - 6}" rx="9" fill="none" stroke="${bandColor[b.color] || 'var(--ink-faint)'}" stroke-width="1.2" stroke-dasharray="2 6" opacity="0.5"/>`;
    svg += `<text class="bandlab" x="${W - 16}" y="${by + 16}" text-anchor="end" fill="${bandColor[b.color] || 'var(--ink-faint)'}">${esc(b.label)}</text>`;
  });

  // lane captions
  lanesUsed.forEach((lane, li) => {
    if (!lane.label) return;
    const y = TOP + li * (NODE_H + GAP_Y) + LANE_LABEL_H - 8;
    svg += `<text class="lanecap" x="${PAD_X}" y="${y}">${esc(lane.label)}</text>`;
  });

  // edge label: wrap to <=2 lines, centered, on an opaque plate so parallel labels
  // stay legible and don't read as one run-on string.
  function edgeLabel(lx, ly, label) {
    const lines = wrapLabel(label, EDGE_MAX, 2);
    const lh = 10;
    const w = Math.max(1, ...lines.map((s) => s.length)) * 5.3 + 8;
    const h = lines.length * lh + 3;
    let s = `<rect x="${(lx - w / 2).toFixed(1)}" y="${(ly - h + 3).toFixed(1)}" width="${w.toFixed(1)}" height="${h}" rx="3" fill="var(--paper)" opacity="0.9"/>`;
    lines.forEach((ln, i) => {
      s += `<text class="elabel" x="${lx.toFixed(1)}" y="${(ly - (lines.length - 1 - i) * lh).toFixed(1)}" text-anchor="middle">${esc(ln)}</text>`;
    });
    return s;
  }

  // edges
  spec.edges.forEach((e) => {
    const a = layout[e.from], b = layout[e.to];
    if (!a || !b) return;
    let d, lx, ly;
    if (a.y === b.y) {
      // same lane, horizontal
      const ax = a.x + a.w, ay = a.y + a.h / 2;
      const bx = b.x;
      d = `M${ax},${ay} H${bx}`;
      lx = (ax + bx) / 2; ly = ay - 7;
    } else {
      // different lanes: down/right elbow — label centered on the horizontal run
      const ax = a.x + a.w / 2, ay = a.y + a.h;
      const bx = b.x + b.w / 2, by = b.y;
      const midY = (ay + by) / 2;
      d = `M${ax},${ay} V${midY} H${bx} V${by}`;
      lx = (ax + bx) / 2; ly = midY - 5;
    }
    svg += `<path class="edge ${e.color}" d="${d}" marker-end="url(#arr-${e.color})"/>`;
    if (e.label) svg += edgeLabel(lx, ly, e.label);
  });

  // nodes — title wrapped onto multiple lines, vertically centered, sub below
  spec.nodes.forEach((n) => {
    const p = layout[n.id]; if (!p) return;
    const cls = 'nbox' + (n.color ? ' ' + n.color : '');
    const cx = p.x + p.w / 2;
    const lines = n._lines || [n.title];
    const contentH = lines.length * TLH + (n.sub ? SUBGAP + SUBH : 0);
    const top = p.y + (p.h - contentH) / 2;
    svg += `<g>`;
    svg += `<rect class="${cls}" x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="6"/>`;
    lines.forEach((ln, i) => {
      svg += `<text class="ntitle" x="${cx}" y="${(top + 11 + i * TLH).toFixed(1)}" text-anchor="middle">${esc(ln)}</text>`;
    });
    if (n.sub) svg += `<text class="nsub" x="${cx}" y="${(top + lines.length * TLH + SUBGAP + 8).toFixed(1)}" text-anchor="middle">${esc(n.sub)}</text>`;
    svg += `</g>`;
  });

  svg += `</svg>`;
  return { svg, minWidth: W };
}

/* ============================================================================
 * 5. Section renderers (keyed by the section catalogue)
 *    Each returns { html, tocLabel } or null. ctx carries page + link resolver.
 * ========================================================================== */

function sectionId(heading) { return slugify(heading); }

function renderSummary(sec, ctx) {
  return parseBlocks(sec.raw, ctx);
}

function renderHowItWorks(sec, ctx) {
  // drive the stepper from a ```steps block, else from an ordered list.
  let html = '';
  const stepsBlock = fencedBlock(sec.raw, 'steps');
  let prose = stripFenced(sec.raw, 'steps');
  let steps = null;
  if (stepsBlock) {
    steps = parseSteps(stepsBlock, ctx);
  } else {
    // try to capture top-level ordered list as steps
    const olItems = captureOrderedList(sec.raw);
    if (olItems.length >= 2) {
      steps = olItems.map((it, idx) => ({
        title: `Step ${idx + 1}`,
        short: it.title,
        sub: '',
        body: inline(it.body || it.title, ctx),
        gotcha: ''
      }));
      prose = removeOrderedList(sec.raw);
    }
  }
  html += parseBlocks(prose, ctx);
  if (steps && steps.length) {
    html += renderStepper(steps);
  }
  return html;
}

/* steps block format:
 *   - title: Tick fires | short: timer wakes a worker
 *     body: On a timer a worker wakes up...
 *     gotcha: Recursive setTimeout is deliberate...
 * Each step starts with "- title:". Continuation keys (body/gotcha/short/sub) follow.
 */
function parseSteps(text, ctx) {
  const steps = [];
  let cur = null;
  for (let line of text.split(/\r?\n/)) {
    const startm = line.match(/^\s*-\s+(.*)$/);
    if (startm) {
      if (cur) steps.push(cur);
      cur = { title: '', short: '', sub: '', body: '', gotcha: '' };
      line = startm[1];
      const kv = splitInlineKV(line);
      Object.assign(cur, kv);
      continue;
    }
    const contm = line.match(/^\s+(\w+):\s*(.*)$/);
    if (contm && cur) {
      cur[contm[1]] = contm[2];
    }
  }
  if (cur) steps.push(cur);
  return steps.map((s, i) => ({
    title: s.title ? inline(s.title, ctx) : `Step ${i + 1}`,
    short: s.short || s.title || `Step ${i + 1}`,
    sub: s.sub || '',
    body: inline(s.body || '', ctx),
    gotcha: s.gotcha ? inline(s.gotcha, ctx) : ''
  }));
}
function splitInlineKV(line) {
  // "title: X | short: Y | sub: Z"
  const out = {};
  line.split('|').forEach((seg) => {
    const m = seg.match(/^\s*(\w+):\s*(.*)$/);
    if (m) out[m[1].trim()] = m[2].trim();
  });
  if (!out.title && !Object.keys(out).length) out.title = line.trim();
  return out;
}
function captureOrderedList(raw) {
  const items = [];
  const lines = raw.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].trim().match(/^\d+\.\s+(.+)$/);
    if (m) {
      // split "Title — body" or "Title: body"
      const t = m[1];
      const sep = t.match(/^(.+?)\s*[—:-]\s+(.+)$/);
      items.push(sep ? { title: sep[1], body: sep[2] } : { title: t, body: '' });
    }
  }
  return items;
}
function removeOrderedList(raw) {
  return raw.split(/\r?\n/).filter((l) => !/^\s*\d+\.\s+/.test(l)).join('\n');
}

function renderStepper(steps) {
  const cols = Math.min(steps.length, 7);
  let tabs = '';
  steps.forEach((s, i) => {
    tabs += `<button class="step" role="tab" aria-selected="${i === 0 ? 'true' : 'false'}" data-step="${i}">` +
      `<span class="sn">STEP ${i + 1}</span>` +
      `<span class="st">${esc(stripTags(s.short))}</span>` +
      `<span class="sd">${esc(s.sub)}</span></button>`;
  });
  const data = steps.map((s) => ({ title: s.title, body: s.body || `<p>${esc(s.short)}</p>`, gotcha: s.gotcha }));
  return `<div class="stepper-wrap"><div class="stepper" role="tablist" style="--step-cols:${cols}">${tabs}</div>` +
    `<div class="panel" role="tabpanel"></div>` +
    `<script type="application/json">${JSON.stringify(data).replace(/</g, '\\u003c')}</script></div>`;
}
function stripTags(s) { return String(s).replace(/<[^>]+>/g, ''); }

function renderReference(sec, ctx) {
  // an inventory: filterable table with chips driven by a data-domain column.
  // convention: a markdown table whose FIRST column header is "Item" (or any),
  // and rows carry a domain via a trailing `{domain}` token in the first cell,
  // OR via a fenced ```inventory block. We support the table-with-{domain}.
  let html = '';
  // detect a table
  const lines = sec.raw.split(/\r?\n/);
  let tableStart = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^\|.*\|/.test(lines[i].trim()) && i + 1 < lines.length && /^\|[\s:|-]+\|/.test(lines[i + 1].trim())) {
      tableStart = i; break;
    }
  }
  // prose before the table
  if (tableStart > 0) html += parseBlocks(lines.slice(0, tableStart).join('\n'), ctx);
  else if (tableStart === -1) return parseBlocks(sec.raw, ctx);

  const header = splitRow(lines[tableStart]);
  let i = tableStart + 2;
  const rows = [];
  while (i < lines.length && /^\|.*\|/.test(lines[i].trim())) { rows.push(splitRow(lines[i])); i++; }

  // collect domains from {domain} tokens in first cell
  const domainSet = [];
  const parsed = rows.map((r) => {
    const cells = r.slice();
    let domain = '';
    const dm = cells[0].match(/\{([^}]+)\}\s*$/);
    if (dm) { domain = slugify(dm[1]); cells[0] = cells[0].replace(/\{[^}]+\}\s*$/, '').trim(); if (!domainSet.includes(domain)) domainSet.push(domain); }
    return { cells, domain };
  });

  const hasDomains = domainSet.length > 0;
  html += `<div class="inventory">`;
  if (hasDomains) {
    html += `<div class="filterbar" role="group" aria-label="Filter inventory">` +
      `<span class="fl">Filter</span>` +
      `<button class="fchip" data-filter="all" aria-pressed="true">All</button>`;
    domainSet.forEach((d) => {
      html += `<button class="fchip" data-filter="${escAttr(d)}" aria-pressed="false">${esc(d)}</button>`;
    });
    html += `<span class="inv-count">${rows.length} / ${rows.length}</span></div>`;
  }
  html += `<table class="inv"><thead><tr>${header.map((h) => `<th>${inline(h, ctx)}</th>`).join('')}</tr></thead><tbody>`;
  parsed.forEach((p) => {
    html += `<tr${p.domain ? ` data-domain="${escAttr(p.domain)}"` : ''}>` +
      p.cells.map((c) => `<td>${inline(c, ctx)}</td>`).join('') + `</tr>`;
  });
  html += `</tbody></table></div>`;
  // any trailing prose
  if (i < lines.length) html += parseBlocks(lines.slice(i).join('\n'), ctx);
  return html;
}

function renderDiagram(sec, ctx) {
  const block = fencedBlock(sec.raw, 'diagram');
  let html = parseBlocks(stripFenced(sec.raw, 'diagram'), ctx);
  if (!block) return html;
  const spec = parseDiagram(block);
  const { svg, minWidth } = renderDiagramSVG(spec);
  // legend keys from edge colours present
  const colorsUsed = [...new Set(spec.edges.map((e) => e.color))];
  const keyLabel = { process: 'Process', safe: 'Safe', caution: 'Caution', never: 'Never', structural: 'Structural' };
  let keys = '';
  colorsUsed.forEach((c) => { keys += `<span class="mkey ${c}"><i></i>${keyLabel[c] || c}</span>`; });
  const title = ctx.diagramTitle || 'Diagram';
  html += `<div class="map"><div class="map-h"><span class="mt">${esc(title)}</span><span class="keys">${keys}</span></div>` +
    `<div class="svgwrap"><div style="min-width:${minWidth}px">${svg}</div></div></div>`;
  return html;
}

function renderContext(sec, ctx) {
  // ```context block: lines "depends-on: id — note", "provides: ...", "relied-on-by: ..."
  const block = fencedBlock(sec.raw, 'context');
  let html = parseBlocks(stripFenced(sec.raw, 'context'), ctx);
  if (!block) return html;
  const buckets = { 'depends-on': [], 'provides': [], 'relied-on-by': [] };
  for (let line of block.split(/\r?\n/)) {
    line = line.trim();
    if (!line || line.startsWith('#')) continue;
    const m = line.match(/^(depends-on|provides|relied-on-by)\s*:\s*(.+)$/);
    if (m) buckets[m[1]].push(m[2].trim());
  }
  const col = (cls, label, items) => {
    if (!items.length) return '';
    return `<div class="ctxcol ${cls}"><span class="cl">${label}</span><ul>` +
      items.map((it) => `<li>${inline(it, ctx)}</li>`).join('') + `</ul></div>`;
  };
  html += `<div class="ctx">` +
    col('dep', 'Depends on', buckets['depends-on']) +
    col('prov', 'Provides', buckets['provides']) +
    col('rely', 'Relied on by', buckets['relied-on-by']) +
    `<div class="ctxhere">You are here · <b>${esc(ctx.pageTitle || '')}</b></div>` +
    `</div>`;
  return html;
}

function renderStandingUp(sec, ctx) {
  // runs-on / depends-on / config-source as a table (markdown table passes through)
  return parseBlocks(sec.raw, ctx).replace(/class="matrix"/g, 'class="standup"');
}

function renderInvariants(sec, ctx) {
  // bullets starting **MUST** / **NEVER** -> semantic-colored panels
  let html = '';
  const lines = sec.raw.split(/\r?\n/);
  const cards = [];
  let lead = [];
  for (const line of lines) {
    const t = line.trim();
    const m = t.match(/^[-*]\s+\*\*(MUST(?:\s+NOT)?|NEVER)\*\*[:\s]*(.+)$/i)
      || t.match(/^[-*]\s+(MUST(?:\s+NOT)?|NEVER)[:\s]+(.+)$/i);
    if (m) {
      const kind = /never|not/i.test(m[1]) ? 'never' : 'must';
      cards.push({ kind, label: m[1].toUpperCase(), text: m[2] });
    } else if (t) {
      lead.push(t);
    }
  }
  if (lead.length) html += parseBlocks(lead.join('\n'), ctx);
  if (cards.length) {
    html += `<div class="invariants">`;
    cards.forEach((c) => {
      html += `<div class="inv ${c.kind}"><span class="tag"><span class="dot"></span>${esc(c.kind === 'never' ? 'Never' : 'Must')}</span>` +
        `<p>${inline(c.text, ctx)}</p></div>`;
    });
    html += `</div>`;
  }
  return html;
}

function renderEnvironments(sec, ctx) {
  // markdown table (staging vs prod) passes straight through, styled
  return parseBlocks(sec.raw, ctx).replace(/class="matrix"/g, 'class="envtable"');
}

function renderGotchas(sec, ctx) {
  // each "- **title**: body" or "- title :: body" -> <details> accordion
  const lines = sec.raw.split(/\r?\n/);
  const items = [];
  let lead = [];
  let cur = null;
  for (const line of lines) {
    const t = line.trim();
    const start = t.match(/^[-*]\s+(.+)$/);
    if (start) {
      if (cur) items.push(cur);
      let body = start[1];
      let title = body, detail = '';
      const bm = body.match(/^\*\*(.+?)\*\*[:\s]*(.*)$/) || body.match(/^(.+?)\s*::\s*(.*)$/) || body.match(/^(.+?):\s+(.+)$/);
      if (bm) { title = bm[1]; detail = bm[2]; }
      cur = { title, detail };
    } else if (t && cur) {
      cur.detail += (cur.detail ? ' ' : '') + t;
    } else if (t) {
      lead.push(t);
    }
  }
  if (cur) items.push(cur);
  let html = '';
  if (lead.length) html += parseBlocks(lead.join('\n'), ctx);
  if (items.length) {
    html += `<div class="acc">`;
    items.forEach((it) => {
      html += `<details><summary><span class="gtag warn">!</span>${inline(it.title, ctx)}<span class="chev">›</span></summary>` +
        `<div class="body"><p>${inline(it.detail || '', ctx)}</p></div></details>`;
    });
    html += `</div>`;
  }
  return html;
}

function renderGlossary(sec, ctx) {
  // each "- **Term**: definition" -> accordion entry AND feeds tooltip glossary
  const lines = sec.raw.split(/\r?\n/);
  const entries = [];
  let lead = [];
  for (const line of lines) {
    const t = line.trim();
    const m = t.match(/^[-*]\s+\*\*(.+?)\*\*[:\s]*(.+)$/) || t.match(/^[-*]\s+(.+?):\s+(.+)$/);
    if (m) {
      entries.push({ term: m[1].trim(), def: m[2].trim() });
      GLOSSARY[m[1].trim().toLowerCase()] = m[2].trim();
    } else if (t) lead.push(t);
  }
  let html = '';
  if (lead.length) html += parseBlocks(lead.join('\n'), ctx);
  if (entries.length) {
    html += `<div class="acc">`;
    entries.forEach((e) => {
      html += `<details><summary><span class="gtag info">i</span>${esc(e.term)}<span class="chev">›</span></summary>` +
        `<div class="body"><p>${inline(e.def, ctx)}</p></div></details>`;
    });
    html += `</div>`;
  }
  return html;
}

function renderRelated(sec, ctx) {
  // builds link cards from [[id]] wikilinks + frontmatter links
  let html = parseBlocks(sec.raw, ctx);
  const ids = new Set();
  const re = /\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g; let m;
  while ((m = re.exec(sec.raw))) ids.add(m[1].trim());
  (ctx.page.fm.links || []).forEach((l) => ids.add(String(l).trim()));
  const cards = [];
  ids.forEach((id) => {
    const target = ctx.linkResolver(id);
    const meta = ctx.pageIndex[id];
    if (target && meta) {
      cards.push(`<a class="relcard" href="${escAttr(target)}"><span class="arr">→</span><span class="rt">${esc(meta.title)}</span><span class="rd">${esc(meta.status || '')}</span></a>`);
    }
  });
  if (cards.length) html += `<div class="related">${cards.join('')}</div>`;
  return html;
}

/* dispatch table keyed by normalized section heading */
const SECTIONS = {
  'summary': { render: renderSummary },
  'how it works': { render: renderHowItWorks },
  'reference': { render: renderReference },
  'diagram': { render: renderDiagram },
  'context map': { render: renderContext },
  'standing it up': { render: renderStandingUp },
  'invariants': { render: renderInvariants },
  'environments': { render: renderEnvironments },
  'gotchas': { render: renderGotchas },
  'glossary': { render: renderGlossary },
  'related': { render: renderRelated },
};
function normHeading(h) { return h.toLowerCase().trim(); }

/* ============================================================================
 * 6. Page assembly
 * ========================================================================== */

function loadTemplate() {
  if (!fs.existsSync(TEMPLATE_PATH)) fail(`Template not found at ${TEMPLATE_PATH}`);
  return fs.readFileSync(TEMPLATE_PATH, 'utf8');
}

function brandCss(brand) {
  let css = '';
  if (brand.accent) css += `:root{--accent:${brand.accent};}`;
  if (brand.accentSoft) css += `:root{--accent-soft:${brand.accentSoft};}`;
  const f = brand.fonts || {};
  if (f.display) css += `:root{--font-display:${f.display};}`;
  if (f.body) css += `:root{--font-body:${f.body};}`;
  if (f.mono) css += `:root{--font-mono:${f.mono};}`;
  return css;
}

function fontsLink(brand) {
  if (brand.fontsLink === false) return '';
  if (brand.fontsLink) return `<link href="${escAttr(brand.fontsLink)}" rel="stylesheet">`;
  return `<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">`;
}

const LEGEND_HTML = `<div class="legend">
  <span class="lt">Semantic colour key</span>
  <div class="row"><span class="swatch" style="background:var(--green)"></span> Safe / healthy</div>
  <div class="row"><span class="swatch" style="background:var(--amber)"></span> Caution / needs update</div>
  <div class="row"><span class="swatch" style="background:var(--red)"></span> Never / failure</div>
  <div class="row"><span class="swatch" style="background:var(--blue)"></span> Process / in-progress</div>
  <div class="row"><span class="swatch" style="background:var(--teal)"></span> Structural / accent</div>
</div>`;

/**
 * Render the body sections of a page (.md) into HTML + a TOC list.
 */
function renderSections(page, ctx) {
  // glossary is page-scoped: clear so terms from one page don't leak into another
  for (const k of Object.keys(GLOSSARY)) delete GLOSSARY[k];
  let content = '';
  const toc = [];
  const units = [];
  let num = 0;
  for (const sec of page.sections) {
    if (!sec.heading) {
      // lead content before first heading
      const lead = parseBlocks(sec.raw, ctx).trim();
      if (lead) content += `<header class="hero"></header>`; // not used; hero handled separately
      continue;
    }
    const key = normHeading(sec.heading);
    const def = SECTIONS[key];
    let inner;
    if (def) {
      ctx.diagramTitle = sec.heading;
      inner = def.render(sec, ctx);
    } else {
      console.warn(`[project-atlas] WARN: unknown section "${sec.heading}" in ${page.relPath} — rendered as prose.`);
      inner = parseBlocks(sec.raw, ctx);
    }
    if (!inner || !inner.trim()) continue;
    num++;
    const id = sectionId(sec.heading);
    const nn = String(num).padStart(2, '0');
    toc.push({ id, label: sec.heading, n: nn });
    units.push({ id, heading: sec.heading, text: sectionPlainText(sec.raw).slice(0, 500) });
    content += `<section id="${id}"><div class="wrap reveal">` +
      `<div class="sec-head"><span class="num">${nn}</span><h3>${esc(sec.heading)}</h3></div>` +
      inner + `</div></section>\n`;
  }
  // Glossary feeds hover tooltips: wrap the first mention of each known term in
  // body prose with a .term span carrying its definition. Only touches text
  // inside <p>…</p> (never code, headings, attributes, or already-marked terms).
  content = applyGlossaryTooltips(content);
  return { content, toc, units };
}

/**
 * Wrap the first plain-text occurrence of each glossary term (case-insensitive)
 * inside paragraph text with a .term tooltip span. Conservative: skips anything
 * inside tags or <code>, and only the first hit per term to avoid clutter.
 */
function applyGlossaryTooltips(html) {
  const terms = Object.keys(GLOSSARY);
  if (!terms.length) return html;
  // longest first so multi-word terms win
  terms.sort((a, b) => b.length - a.length);
  const used = new Set();
  // process only <p>…</p> spans
  return html.replace(/<p>([\s\S]*?)<\/p>/g, (full, inner) => {
    // skip if inside contains code we shouldn't touch — we still split on tags
    let result = '';
    // tokenize into tag / code / text segments
    const parts = inner.split(/(<[^>]+>|<code>[\s\S]*?<\/code>)/);
    for (let seg of parts) {
      if (!seg) continue;
      if (seg.startsWith('<')) { result += seg; continue; }
      // plain text segment — try to wrap one unused term
      for (const t of terms) {
        if (used.has(t)) continue;
        const re = new RegExp('\\b(' + escapeRe(t) + ')\\b', 'i');
        if (re.test(seg)) {
          const def = GLOSSARY[t];
          seg = seg.replace(re, (m) => `<span class="term" data-tip="${escAttr(def)}">${m}</span>`);
          used.add(t);
          break;
        }
      }
      result += seg;
    }
    return '<p>' + result + '</p>';
  });
}
function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

/* plain-text extraction for the search index: strip markdown syntax + fenced
 * blocks down to searchable prose. Capped by the caller. */
function sectionPlainText(raw) {
  let t = String(raw == null ? '' : raw);
  t = t.replace(/```[\s\S]*?```/g, ' ');                                   // drop fenced blocks
  t = t.replace(/`([^`]+)`/g, '$1');                                       // inline code
  t = t.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, a, b) => b || a); // wikilinks
  t = t.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');                           // links -> text
  t = t.replace(/[#>*_|]+/g, ' ').replace(/(^|\s)-+(\s|$)/g, ' ');         // md punctuation
  t = t.replace(/\s+/g, ' ').trim();
  return t;
}

function renderTocNav(toc, extras) {
  let nav = `<nav class="toc" aria-label="Sections">`;
  toc.forEach((t) => {
    nav += `<a href="#${t.id}"><span class="n">${t.n}</span><span>${esc(t.label)}</span></a>`;
  });
  (extras || []).forEach((e) => {
    nav += `<a href="#${e.id}" class="sub-d"><span class="n">·</span><span>${esc(e.label)}</span></a>`;
  });
  nav += `</nav>`;
  return nav;
}

function renderBreadcrumb(trail, level, maxDepth) {
  if (!trail || trail.length <= 1) return '';
  let html = `<nav class="crumbs" aria-label="Breadcrumb">`;
  trail.forEach((c, i) => {
    if (i === trail.length - 1) {
      html += `<span class="here">${esc(c.label)}</span>`;
    } else {
      html += `<a href="${escAttr(c.href)}">${esc(c.label)}</a><span class="sep" aria-hidden="true">›</span>`;
    }
  });
  html += `<span class="lvl">Level ${level} of ${maxDepth}</span></nav>`;
  return html;
}

function buildHtml(template, parts) {
  const ribbon = parts.ribbon ? `<span class="ribbon">${esc(parts.ribbon)}</span>` : '';
  const uplink = parts.uplink ? `<a class="uplink" href="${escAttr(parts.uplink.href)}">← ${esc(parts.uplink.label)}</a>` : '';
  const subs = {
    LANG: escAttr(parts.lang || 'en'),
    TITLE: esc(parts.title),
    CONTENT_HASH: escAttr(parts.contentHash || ''),
    FONTS_LINK: parts.fontsLink,
    BRAND_CSS: parts.brandCss,
    BRAND_NAME: esc(parts.brandName),
    PAGE_TITLE: esc(parts.pageTitle),
    RIBBON: ribbon,
    PAGE_TAGLINE: esc(parts.tagline || ''),
    UPLINK: uplink,
    ATLASNAV: parts.atlasNav || '',
    SEARCH: parts.search || '',
    SIDEBAR: parts.sidebar,
    LEGEND: LEGEND_HTML,
    BREADCRUMB: parts.breadcrumb || '',
    CONTENT: parts.content,
    FOOTER: parts.footer,
  };
  let out = template;
  // replace ALL occurrences of each placeholder (split/join avoids regex $-escaping
  // pitfalls in the replacement and never leaves a duplicate placeholder behind).
  for (const [key, val] of Object.entries(subs)) {
    out = out.split('{{' + key + '}}').join(val == null ? '' : String(val));
  }
  // HTML self-integrity hash: hash the whole page with the integrity field blanked,
  // then stamp it. verify-atlas recomputes this and fails if the HTML was hand-edited.
  const withBlank = out.split('{{HTML_INTEGRITY}}').join('');
  const integrity = 'sha256:' + crypto.createHash('sha256').update(withBlank, 'utf8').digest('hex');
  out = out.split('{{HTML_INTEGRITY}}').join(integrity);
  return out;
}

/* ============================================================================
 * 7. Content hashing
 * ========================================================================== */

function normalizeBody(body) {
  // strip an existing content_hash line is handled at frontmatter level;
  // here we normalize the BODY: trim trailing whitespace per line, collapse
  // trailing blank lines, normalize line endings.
  return body.replace(/\r\n/g, '\n').split('\n').map((l) => l.replace(/\s+$/, '')).join('\n').replace(/\n+$/, '') + '\n';
}
function hashBody(body) {
  return 'sha256:' + crypto.createHash('sha256').update(normalizeBody(body), 'utf8').digest('hex');
}

/* stamp content_hash into the .md frontmatter (rewrites the file) */
function stampHash(absPath, raw, hash) {
  const { fm, body } = splitFrontmatter(raw);
  let newFm;
  if (/^content_hash:.*$/m.test(fm)) {
    newFm = fm.replace(/^content_hash:.*$/m, `content_hash: ${hash}`);
  } else {
    // insert after id: or at top
    newFm = fm.trimEnd() + `\ncontent_hash: ${hash}`;
  }
  const out = `---\n${newFm}\n---\n${body.replace(/^\n/, '')}`;
  if (out !== raw) fs.writeFileSync(absPath, out);
  return out;
}

/* ============================================================================
 * 8. Read & index all pages
 * ========================================================================== */

function readPage(absPath, relPath) {
  const raw = fs.readFileSync(absPath, 'utf8');
  const { fm, body } = splitFrontmatter(raw);
  const meta = parseFrontmatter(fm);
  const sections = splitSections(body);
  return { absPath, relPath, raw, fm: meta, rawFm: fm, body, sections };
}

function walkDomains(cfg) {
  const pages = [];
  if (!fs.existsSync(cfg._domainsDir)) return pages;
  function walk(dir, rel) {
    for (const name of fs.readdirSync(dir).sort()) {
      const abs = path.join(dir, name);
      const stat = fs.statSync(abs);
      if (stat.isDirectory()) {
        walk(abs, path.join(rel, name));
      } else if (name.endsWith('.md')) {
        // normalize to POSIX separators so Windows '\' never leaks into relPath
        // (htmlRelFor/outPathFor/split('/') all assume '/')
        pages.push(readPage(abs, path.join('domains', rel, name).replace(/\\/g, '/')));
      }
    }
  }
  walk(cfg._domainsDir, '');
  return pages;
}

/* ============================================================================
 * 9. Output-path mapping & link resolution
 * ========================================================================== */

function outPathFor(page, cfg) {
  // domains/backend/index.md -> build/backend/index.html
  // domains/backend/scheduler.md -> build/backend/scheduler.html
  const rel = htmlRelFor(page);
  return path.join(cfg._buildDir, rel);   // path.join re-applies the OS separator for the fs write
}
function htmlRelFor(page) {
  // normalize '\' -> '/' first so this is correct on Windows, then strip the
  // domains/ prefix and swap the extension. Everything downstream (hrefs,
  // split('/'), relUp/relPathBetween, levelOf) depends on this being POSIX '/'.
  return page.relPath.replace(/\\/g, '/').replace(/^domains\//, '').replace(/\.md$/, '.html');
}

/* depth/level: build/index.html (hub) = 1; backend/index.html = 2; backend/x.html = 3 */
function levelOf(page) {
  const rel = htmlRelFor(page);
  const parts = rel.split('/');
  if (rel === 'index.html') return 1;
  if (parts.length === 2 && parts[1] === 'index.html') return 2;
  return 3;
}

/* ============================================================================
 * 10. HUB / DOMAIN / SUB-PAGE builders
 * ========================================================================== */

function statusChip(status) {
  const s = status || 'draft';
  const label = s.replace(/-/g, ' ');
  return `<span class="chip ${esc(s)}"><span class="dot"></span>${esc(label)}</span>`;
}

function domainCard(meta, href, opts) {
  opts = opts || {};
  const cls = meta.status === 'on-hold' ? 'hold' : colorClass(opts.color || 'structural');
  const summary = Array.isArray(meta.summary) ? meta.summary : (meta.summary ? [meta.summary] : []);
  const bullets = summary.slice(0, 4).map((b) => `<li>${inline(b, opts.ctx || {})}</li>`).join('');
  const kicker = opts.kicker || 'Domain';
  const open = href === '#' ? 'On hold' : (opts.openLabel || 'Open ───▶');
  const idAttr = opts.id ? ` id="${escAttr(opts.id)}"` : '';
  return `<a class="dcard ${cls}"${idAttr} href="${escAttr(href)}" aria-label="${escAttr(meta.title)}">` +
    `<div class="top"></div><div class="body">` +
    `<div class="crow"><span class="k">${esc(kicker)}</span>${statusChip(meta.status)}</div>` +
    `<h4>${esc(meta.title)}</h4>` +
    (opts.purpose ? `<p class="purpose">${inline(opts.purpose, opts.ctx || {})}</p>` : '') +
    (bullets ? `<ul>${bullets}</ul>` : '') +
    `<span class="open">${esc(open)}</span></div></a>`;
}

function buildHub(cfg, hubPage, pageIndex, linkResolver, ctx) {
  const template = loadTemplate();
  const hash = hashBody(hubPage.body);

  // hero from frontmatter summary or first Summary section
  const summary = Array.isArray(hubPage.fm.summary) ? hubPage.fm.summary : [];
  const heroTitle = hubPage.fm.title || cfg.brand.name || 'Project Atlas';
  const lede = summary[0] ? inline(summary[0], ctx) : esc(hubPage.fm.tagline || '');

  // render the hub.md sections (the diagram etc.) but we control the layout:
  // we want: hero + system map (from a Diagram section) + domain grid + envs.
  const sectionsHtml = renderSections(hubPage, ctx);

  // domain grid: one card per top-level domain (config order; grouped by axis when >1 axis)
  const grid = renderDomainGrid(cfg, ctx);

  // assemble content: hero, then the rendered diagram sections, then grid
  let content = '';
  content += `<header class="hero tophero"><div class="eyebrow"><span>${esc(cfg.brand.name || 'Project Atlas')} · Hub</span></div>` +
    `<h2>${esc(heroTitle)}</h2>` +
    (lede ? `<p class="lede">${lede}</p>` : '') +
    `<div class="readline"><span class="lab">How to read</span><p>Start at the <b>system map</b> to see how a request moves through the parts, then open a <b>domain card</b> below. Each page has an <b>agent-markdown twin</b> kept in sync — humans read the rendered page; agents read the markdown.</p></div></header>`;

  content += sectionsHtml.content;

  content += `<section id="domains"><div class="wrap reveal">` +
    `<div class="sec-head"><span class="num">${String(sectionsHtml.toc.length + 1).padStart(2, '0')}</span><h3>Domains</h3></div>` +
    `<p class="sub">Every domain links to its landing page. Cards are generated from each domain's frontmatter — status, summary, and link.</p>` +
    grid + `</div></section>`;

  const toc = sectionsHtml.toc.concat([{ id: 'domains', label: 'Domains', n: String(sectionsHtml.toc.length + 1).padStart(2, '0') }]);
  const sidebar = renderTocNav(toc);

  const footer = `<footer><p>${esc(cfg.brand.name || 'Project Atlas')} — Project Atlas Hub · generated by project-atlas</p>` +
    `<p>Content hash <code>${esc(hash)}</code> · edit the markdown, run build-atlas.mjs, commit both.</p></footer>`;

  const html = buildHtml(template, {
    lang: cfg.brand.lang || 'en',
    title: `${heroTitle} — Project Atlas`,
    contentHash: hash,
    fontsLink: fontsLink(cfg.brand),
    brandCss: brandCss(cfg.brand),
    brandName: cfg.brand.name || 'Project Atlas',
    pageTitle: 'Project Atlas — Hub',
    ribbon: cfg.brand.ribbon || '',
    tagline: hubPage.fm.tagline || (summary[0] || ''),
    atlasNav: renderAtlasNav(cfg, ctx, hubPage, true),
    search: renderSearch(cfg, hubPage),
    sidebar, content, footer, breadcrumb: ''
  });
  const searchRecord = {
    page: 'index.html',
    title: heroTitle,
    tagline: hubPage.fm.tagline || (summary[0] || ''),
    summary: summary,
    domain: 'Hub',
    units: sectionsHtml.units,
  };
  return { html, hash, outPath: path.join(cfg._buildDir, 'index.html'), searchRecord };
}

function isSingleFileDomain(page) {
  // domains/<x>.md (no index, no subfolder) — a small single-page domain
  const rel = htmlRelFor(page);
  const parts = rel.split('/');
  return parts.length === 1 && rel !== 'index.html';
}

/* ============================================================================
 *  Two-axis support — layer (technical domains) vs feature (vertical slices)
 *  A domain's axis comes from config (axis:"feature") or page frontmatter, else
 *  "layer". When >1 axis is present the hub grid and the persistent atlas-map nav
 *  split into labeled groups ("By Layer" / "By Feature"); with a single axis the
 *  output matches the original flat list — fully backward compatible.
 * ========================================================================== */

const AXIS_LABELS = { layer: 'By Layer', feature: 'By Feature' };
function axisLabel(cfg, axis) {
  const navCfg = (cfg.nav && cfg.nav[axis]) || {};
  if (navCfg.label) return navCfg.label;
  if (AXIS_LABELS[axis]) return AXIS_LABELS[axis];
  return 'By ' + axis.charAt(0).toUpperCase() + axis.slice(1);
}

/* enumerate top-level domains (folder landings + single-file domains), ordered by
 * config, each tagged with its resolved axis and config entry. Shared by the hub
 * grid and the atlas-map nav so the two never disagree. */
function collectDomainEntries(cfg, ctx) {
  const entries = [];
  const seen = new Set();
  for (const p of ctx.allPages) {
    const rel = htmlRelFor(p);
    const parts = rel.split('/');
    let key = null;
    if (parts.length === 2 && parts[1] === 'index.html') key = parts[0];
    else if (parts.length === 1 && rel !== 'index.html') key = rel.replace(/\.html$/, '');
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const cfgDomain = (cfg.domains || []).find((d) => (d.id || d.domain) === key) || {};
    const axis = cfgDomain.axis || p.fm.axis || 'layer';
    entries.push({ key, page: p, href: rel, cfgDomain, axis });
  }
  const order = (cfg.domains || []).map((d) => d.id || d.domain || d);
  entries.sort((a, b) => {
    const ia = order.indexOf(a.key), ib = order.indexOf(b.key);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
  return entries;
}

/* group entries by axis, preserving first-appearance (config) order of the axes */
function groupByAxis(entries) {
  const groups = [];
  const byAxis = new Map();
  for (const e of entries) {
    if (!byAxis.has(e.axis)) { const g = { axis: e.axis, entries: [] }; byAxis.set(e.axis, g); groups.push(g); }
    byAxis.get(e.axis).entries.push(e);
  }
  return groups;
}

function dotColorClass(color) {
  // whitelist the frozen palette; anything unknown (incl. 'structural' or an
  // injection payload from config/frontmatter) collapses to teal — never raw.
  const ok = { blue: 1, green: 1, teal: 1, amber: 1, red: 1 };
  return 'ad-' + (ok[color] ? color : 'teal');
}

/* persistent left-rail "Atlas map": every domain as a page link, grouped by axis,
 * with the current domain marked active. Links are page-relative (not in-page
 * anchors) and use nav.atlas (not nav.toc) so the section scroll-spy ignores them.
 * Wrapped in <details> so it collapses to a hamburger on mobile; CSS forces it
 * open on desktop. */
function renderAtlasNav(cfg, ctx, currentPage, isHub) {
  const entries = collectDomainEntries(cfg, ctx);
  if (!entries.length) return '';
  const curRel = htmlRelFor(currentPage);
  // the hub writes to index.html but htmlRelFor(hubPage) is 'hub.html'; trust the flag
  const curKey = isHub ? null
    : (curRel.includes('/') ? curRel.split('/')[0] : curRel.replace(/\.html$/, ''));
  const hubHref = relPathBetween(currentPage, 'index.html');
  const groups = groupByAxis(entries);
  const showLabels = groups.length > 1;

  const linkFor = (e) => {
    const meta = e.page.fm;
    // on-hold pages are still generated, so always link them — '#' would orphan
    // the page from the site-wide nav and leave its own "you are here" link dead.
    const href = relPathBetween(currentPage, e.href);
    const active = e.key === curKey ? ' active' : '';
    const hold = meta.status === 'on-hold' ? ' amap-hold' : '';
    const dot = `<span class="ad ${dotColorClass(e.cfgDomain.color || meta.color)}"></span>`;
    return `<a class="amap-link${active}${hold}" href="${escAttr(href)}">${dot}<span>${esc(meta.title || e.key)}</span></a>`;
  };

  let nav = `<nav class="atlas" aria-label="Atlas map">`;
  nav += `<a class="amap-link amap-hub${isHub ? ' active' : ''}" href="${escAttr(hubHref)}">` +
    `<span class="ad ad-teal"></span><span>Hub</span></a>`;
  for (const g of groups) {
    if (showLabels) nav += `<div class="amap-group">${esc(axisLabel(cfg, g.axis))}</div>`;
    nav += g.entries.map(linkFor).join('');
  }
  nav += `</nav>`;

  // open by default so the a11y disclosure state matches the visible (desktop) state;
  // template JS collapses it to a hamburger on mobile (<=880px).
  return `<details class="amap-wrap" open>` +
    `<summary class="amap-toggle"><span class="amap-burger" aria-hidden="true">☰</span> Atlas map</summary>` +
    `<div class="amap-deskhead" aria-hidden="true">Atlas map</div>` +
    nav + `</details>`;
}

function renderDomainGrid(cfg, ctx) {
  const entries = collectDomainEntries(cfg, ctx);
  const cardFor = (e) => {
    const meta = e.page.fm;
    const color = e.cfgDomain.color || meta.color || 'structural';
    const href = meta.status === 'on-hold' ? '#' : e.href;
    return domainCard(meta, href, {
      color,
      id: e.key + '-d',
      kicker: e.cfgDomain.kicker || (e.axis === 'feature' ? 'Feature' : 'Domain'),
      purpose: meta.purpose || (Array.isArray(meta.summary) ? '' : meta.summary),
      openLabel: 'Open ───▶',
      ctx
    });
  };
  const groups = groupByAxis(entries);
  if (groups.length <= 1) {
    return `<div class="grid">${entries.map(cardFor).join('')}</div>`;
  }
  return groups.map((g) =>
    `<div class="axis-block"><div class="axis-h">${esc(axisLabel(cfg, g.axis))}</div>` +
    `<div class="grid">${g.entries.map(cardFor).join('')}</div></div>`
  ).join('');
}

function buildDomainLanding(cfg, page, ctx) {
  const template = loadTemplate();
  const hash = hashBody(page.body);
  const meta = page.fm;
  const domainKey = htmlRelFor(page).split('/')[0];

  const sectionsHtml = renderSections(page, ctx);

  // sub-page index grid: pages under domains/<domainKey>/*.md except index.md
  const subPages = ctx.allPages.filter((p) => {
    const rel = htmlRelFor(p);
    const parts = rel.split('/');
    return parts.length === 2 && parts[0] === domainKey && parts[1] !== 'index.html';
  });
  let gridSection = '';
  if (subPages.length) {
    const cards = subPages.map((sp) => {
      const m = sp.fm;
      const href = m.status === 'on-hold' ? '#' : htmlRelFor(sp).split('/').slice(1).join('/');
      return domainCard(m, href, {
        color: m.color || 'process',
        kicker: 'Sub-page',
        purpose: m.purpose || (Array.isArray(m.summary) ? '' : m.summary),
        openLabel: 'Open ───▶',
        ctx
      });
    }).join('');
    const n = String(sectionsHtml.toc.length + 1).padStart(2, '0');
    gridSection = `<section id="subpages"><div class="wrap reveal">` +
      `<div class="sec-head"><span class="num">${n}</span><h3>Sub-pages</h3></div>` +
      `<p class="sub">Deeper level-3 pages in this domain — each its own focused detail and graphics.</p>` +
      `<div class="grid">${cards}</div></div></section>`;
    sectionsHtml.toc.push({ id: 'subpages', label: 'Sub-pages', n });
  }

  const heroTitle = meta.title || domainKey;
  const summary = Array.isArray(meta.summary) ? meta.summary : [];
  let content = '';
  content += `<header class="hero"><div class="eyebrow"><span>Domain landing</span></div>` +
    `<h2>${esc(heroTitle)}</h2>` +
    (summary[0] ? `<p class="lede">${inline(summary[0], ctx)}</p>` : '') +
    `<div class="readline"><span class="lab">How to read</span><p>This is a mini-atlas for one domain: an overview and diagram, then the index of its sub-pages.</p></div></header>`;
  content += sectionsHtml.content + gridSection;

  const trail = [
    { label: 'Atlas', href: relUp(page, 'index.html') },
    { label: heroTitle, href: '' }
  ];
  const breadcrumb = renderBreadcrumb(trail, 2, cfg.options.maxDepth);
  const sidebar = renderTocNav(sectionsHtml.toc);

  const footer = `<footer><span class="lvlnote">Level 2 of ${cfg.options.maxDepth} — domain landing</span>` +
    `<p>${esc(cfg.brand.name || '')} — ${esc(heroTitle)} · generated by project-atlas</p>` +
    `<p>Content hash <code>${esc(hash)}</code></p></footer>`;

  const html = buildHtml(template, {
    lang: cfg.brand.lang || 'en',
    title: `${heroTitle} — Domain — ${cfg.brand.name || 'Project Atlas'}`,
    contentHash: hash,
    fontsLink: fontsLink(cfg.brand),
    brandCss: brandCss(cfg.brand),
    brandName: cfg.brand.name || 'Project Atlas',
    pageTitle: heroTitle,
    ribbon: 'Domain Landing',
    tagline: meta.tagline || (summary[0] || ''),
    uplink: { href: relUp(page, 'index.html'), label: 'Atlas Hub' },
    atlasNav: renderAtlasNav(cfg, ctx, page),
    search: renderSearch(cfg, page),
    sidebar, content, footer, breadcrumb
  });
  const searchRecord = {
    page: htmlRelFor(page),
    title: heroTitle,
    tagline: meta.tagline || (summary[0] || ''),
    summary: summary,
    domain: heroTitle,
    units: sectionsHtml.units,
  };
  return { html, hash, outPath: outPathFor(page, cfg), searchRecord };
}

function buildSubPage(cfg, page, ctx) {
  const template = loadTemplate();
  const hash = hashBody(page.body);
  const meta = page.fm;
  const rel = htmlRelFor(page);
  const parts = rel.split('/');
  const single = parts.length === 1;
  const domainKey = single ? null : parts[0];

  const sectionsHtml = renderSections(page, ctx);
  const heroTitle = meta.title || rel.replace(/\.html$/, '');
  const summary = Array.isArray(meta.summary) ? meta.summary : [];

  let content = '';
  content += `<header class="hero"><div class="eyebrow"><span>${single ? 'Domain' : 'Sub-page'}</span></div>` +
    `<h2>${esc(heroTitle)}</h2>` +
    (summary[0] ? `<p class="lede">${inline(summary[0], ctx)}</p>` : '') + `</header>`;
  content += sectionsHtml.content;

  // breadcrumb trail
  let trail, level;
  if (single) {
    trail = [{ label: 'Atlas', href: 'index.html' }, { label: heroTitle, href: '' }];
    level = 2;
  } else {
    const domainPage = ctx.allPages.find((p) => htmlRelFor(p) === `${domainKey}/index.html`);
    const domainTitle = domainPage ? domainPage.fm.title : domainKey;
    trail = [
      { label: 'Atlas', href: '../index.html' },
      { label: domainTitle, href: 'index.html' },
      { label: heroTitle, href: '' }
    ];
    level = 3;
  }
  const breadcrumb = renderBreadcrumb(trail, level, cfg.options.maxDepth);
  const sidebar = renderTocNav(sectionsHtml.toc);
  const upHref = single ? 'index.html' : '../index.html';

  const footer = `<footer><span class="lvlnote">Level ${level} of ${cfg.options.maxDepth}</span>` +
    `<p>${esc(cfg.brand.name || '')} — ${esc(heroTitle)} · generated by project-atlas</p>` +
    `<p>Content hash <code>${esc(hash)}</code></p></footer>`;

  const html = buildHtml(template, {
    lang: cfg.brand.lang || 'en',
    title: `${heroTitle} — ${cfg.brand.name || 'Project Atlas'}`,
    contentHash: hash,
    fontsLink: fontsLink(cfg.brand),
    brandCss: brandCss(cfg.brand),
    brandName: cfg.brand.name || 'Project Atlas',
    pageTitle: heroTitle,
    ribbon: single ? 'Domain' : 'Sub-page',
    tagline: meta.tagline || (summary[0] || ''),
    uplink: { href: upHref, label: 'Atlas Hub' },
    atlasNav: renderAtlasNav(cfg, ctx, page),
    search: renderSearch(cfg, page),
    sidebar, content, footer, breadcrumb
  });
  let domainLabel = heroTitle;
  if (!single) {
    const dp = ctx.allPages.find((p) => htmlRelFor(p) === `${domainKey}/index.html`);
    domainLabel = dp && dp.fm.title ? dp.fm.title : domainKey;
  }
  const searchRecord = {
    page: htmlRelFor(page),
    title: heroTitle,
    tagline: meta.tagline || (summary[0] || ''),
    summary: summary,
    domain: domainLabel,
    units: sectionsHtml.units,
  };
  return { html, hash, outPath: outPathFor(page, cfg), searchRecord };
}

/* compute a relative href from a page's output location up to a build-root file */
function relUp(page, target) {
  const rel = htmlRelFor(page);
  const depth = rel.split('/').length - 1;
  return '../'.repeat(depth) + target;
}

/* per-page search widget: the bar markup + the shared index <script>. The bar's
 * data-atlas-base is the page's relative path to build root so the client can
 * resolve both the index src and result links from any depth. */
function renderSearch(cfg, page) {
  if (cfg.options.search === false) return '';
  const base = relUp(page, ''); // '' at root, '../' one level deep, etc.
  return `<div class="atlas-search" data-atlas-base="${escAttr(base)}">` +
    `<input type="search" class="as-input" placeholder="Search the atlas…" ` +
    `aria-label="Search the atlas" autocomplete="off" spellcheck="false">` +
    `<kbd class="as-kbd" aria-hidden="true">⌘K</kbd>` +
    `<div class="as-results" role="listbox" hidden></div></div>` +
    `<script src="${escAttr(base)}search-index.js" defer></script>`;
}

/* flatten page search records into the index entry list */
function buildSearchEntries(records) {
  const entries = [];
  for (const r of records) {
    const summary = Array.isArray(r.summary) ? r.summary : (r.summary ? [r.summary] : []);
    const hi = [r.title, r.tagline].concat(summary).filter(Boolean).join(' ');
    entries.push({ page: r.page, anchor: '', title: r.title, heading: '', domain: r.domain, hi: hi, body: '' });
    for (const u of (r.units || [])) {
      entries.push({ page: r.page, anchor: u.id, title: r.title, heading: u.heading, domain: r.domain, hi: u.heading, body: u.text });
    }
  }
  return entries;
}

/* ============================================================================
 * 11. Link resolver + page index
 * ========================================================================== */

function buildPageIndex(cfg, allPages, hubPage) {
  const index = {};
  // hub
  if (hubPage.fm.id) index[hubPage.fm.id] = { title: hubPage.fm.title, status: hubPage.fm.status, htmlRel: 'index.html', page: hubPage };
  index['hub'] = index['hub'] || { title: hubPage.fm.title || 'Hub', status: hubPage.fm.status, htmlRel: 'index.html', page: hubPage };
  for (const p of allPages) {
    const id = p.fm.id || htmlRelFor(p).replace(/\.html$/, '').replace(/\//g, '-');
    index[id] = { title: p.fm.title || id, status: p.fm.status, htmlRel: htmlRelFor(p), page: p };
  }
  return index;
}

/* resolver returns a relative href from `fromPage` to the target id's html, or null */
function makeLinkResolver(pageIndex, fromPage) {
  return (id) => {
    const target = pageIndex[String(id).trim()];
    if (!target) return null;
    return relPathBetween(fromPage, target.htmlRel);
  };
}
function relPathBetween(fromPage, targetHtmlRel) {
  const fromRel = fromPage ? htmlRelFor(fromPage) : 'index.html';
  const fromDir = fromRel.includes('/') ? fromRel.split('/').slice(0, -1).join('/') : '';
  const fromDepth = fromDir ? fromDir.split('/').length : 0;
  const up = '../'.repeat(fromDepth);
  return up + targetHtmlRel;
}

/* ============================================================================
 * 12. agent-index.md
 * ========================================================================== */

function buildAgentIndex(cfg, allPages, hubPage) {
  let md = `# Agent Index — ${cfg.brand.name || 'Project Atlas'}\n\n`;
  md += `> Generated by project-atlas. A lean roll-up of every page for fast agent onboarding.\n`;
  md += `> Read a page's full canonical markdown for detail; this index is the map.\n\n`;
  const all = [hubPage].concat(allPages);
  for (const p of all) {
    const m = p.fm;
    const id = m.id || htmlRelFor(p).replace(/\.html$/, '').replace(/\//g, '-');
    md += `## ${m.title || id}\n`;
    md += `- id: ${id}\n`;
    md += `- status: ${m.status || 'draft'}\n`;
    md += `- source: ${p.relPath}\n`;
    if (m.summary) {
      const s = Array.isArray(m.summary) ? m.summary : [m.summary];
      md += `- summary:\n`;
      s.forEach((b) => { md += `  - ${b}\n`; });
    }
    if (m.invariants && m.invariants.length) {
      md += `- invariants:\n`;
      (Array.isArray(m.invariants) ? m.invariants : [m.invariants]).forEach((iv) => { md += `  - ${iv}\n`; });
    }
    if (m.anchors && Object.keys(m.anchors).length) {
      md += `- anchors:\n`;
      Object.entries(m.anchors).forEach(([k, v]) => { md += `  - ${k}: ${v}\n`; });
    }
    if (m.links && m.links.length) {
      md += `- links: ${(Array.isArray(m.links) ? m.links : [m.links]).join(', ')}\n`;
    }
    md += `\n`;
  }
  return md;
}

/* ============================================================================
 * 13. Main
 * ========================================================================== */

function ensureDir(p) { fs.mkdirSync(path.dirname(p), { recursive: true }); }

function main() {
  const cfg = loadConfig();
  console.log(`[project-atlas] root: ${cfg._root}`);

  if (!fs.existsSync(cfg._hubMd)) fail(`hub.md not found at ${cfg._hubMd}`);
  const hubPage = readPage(cfg._hubMd, 'hub.md');
  const allPages = walkDomains(cfg);

  // reset glossary collection
  for (const k of Object.keys(GLOSSARY)) delete GLOSSARY[k];

  const pageIndex = buildPageIndex(cfg, allPages, hubPage);

  // stamp hashes into the .md files (hub + domains)
  stampHash(hubPage.absPath, hubPage.raw, hashBody(hubPage.body));
  for (const p of allPages) stampHash(p.absPath, p.raw, hashBody(p.body));

  // clean & ensure build dir
  fs.mkdirSync(cfg._buildDir, { recursive: true });

  const written = [];

  // shared ctx factory
  function ctxFor(page) {
    return {
      page,
      pageTitle: page.fm.title,
      pageIndex,
      allPages,
      linkResolver: makeLinkResolver(pageIndex, page),
    };
  }

  const searchRecords = [];
  // HUB
  {
    const ctx = ctxFor(hubPage);
    ctx.allPages = allPages;
    const { html, outPath, searchRecord } = buildHub(cfg, hubPage, pageIndex, ctx.linkResolver, ctx);
    ensureDir(outPath);
    fs.writeFileSync(outPath, html);
    written.push(outPath);
    if (searchRecord) searchRecords.push(searchRecord);
  }

  // DOMAIN + SUB pages
  for (const p of allPages) {
    const lvl = levelOf(p);
    const ctx = ctxFor(p);
    let result;
    if (lvl === 2) result = buildDomainLanding(cfg, p, ctx);
    else result = buildSubPage(cfg, p, ctx);
    ensureDir(result.outPath);
    fs.writeFileSync(result.outPath, result.html);
    written.push(result.outPath);
    if (result.searchRecord) searchRecords.push(result.searchRecord);
  }

  // search-index.js (shared, classic-script global so it loads over file:// too)
  if (cfg.options.search !== false) {
    const entries = buildSearchEntries(searchRecords);
    const idxPath = path.join(cfg._buildDir, 'search-index.js');
    fs.writeFileSync(idxPath, 'window.ATLAS_SEARCH_INDEX = ' + JSON.stringify({ entries }) + ';\n');
    written.push(idxPath);
  }

  // agent-index.md
  if (cfg.options.agentIndex) {
    const md = buildAgentIndex(cfg, allPages, hubPage);
    const aiPath = path.join(cfg._root, 'agent-index.md');
    fs.writeFileSync(aiPath, md);
    written.push(aiPath);
  }

  console.log(`[project-atlas] wrote ${written.length} files:`);
  written.forEach((w) => console.log('  ' + path.relative(cfg._root, w)));
  console.log('[project-atlas] OK');
}

main();
