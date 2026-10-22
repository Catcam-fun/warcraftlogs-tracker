// Copies handler.js into breaker.yaml's inline Lambda code (Code.ZipFile), so
// the CloudFormation template is one file to upload and handler.js stays the
// tested source.
//   node infra/breaker/build.mjs           rewrite breaker.yaml
//   node infra/breaker/build.mjs --check   exit 1 if breaker.yaml is out of date
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const TEMPLATE = join(here, 'breaker.yaml');
export const HANDLER = join(here, 'handler.js');
const INLINE_LIMIT = 4096; // CloudFormation's ZipFile maximum

// The template with its ZipFile block replaced by `code`.
export function render(template, code) {
  const lines = template.replace(/\r\n/g, '\n').split('\n');
  const at = lines.findIndex((l) => /^\s*ZipFile: \|\s*$/.test(l));
  if (at < 0) throw new Error('breaker.yaml has no "ZipFile: |" block');
  const pad = ' '.repeat(lines[at].search(/\S/) + 2);
  let end = at + 1;
  while (end < lines.length && (lines[end].trim() === '' || lines[end].startsWith(pad))) end += 1;
  while (end > at + 1 && lines[end - 1].trim() === '') end -= 1; // keep the blank line after the block
  const body = ['// generated from infra/breaker/handler.js', ...code.replace(/\r\n/g, '\n').trimEnd().split('\n')]
    .map((l) => (l ? pad + l : ''));
  if (body.join('\n').length > INLINE_LIMIT) throw new Error('handler.js is over the 4 KB inline limit');
  return [...lines.slice(0, at + 1), ...body, ...lines.slice(end)].join('\n');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const current = readFileSync(TEMPLATE, 'utf8');
  const next = render(current, readFileSync(HANDLER, 'utf8'));
  if (process.argv.includes('--check')) {
    if (next !== current.replace(/\r\n/g, '\n')) {
      console.error('breaker.yaml is out of date: run node infra/breaker/build.mjs');
      process.exit(1);
    }
    console.log('breaker.yaml is up to date');
  } else {
    writeFileSync(TEMPLATE, next);
    console.log('breaker.yaml updated from handler.js');
  }
}
