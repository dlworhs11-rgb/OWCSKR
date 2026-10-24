// npm test: node --test with the collector/*.test.mjs files listed here. Node 20 does not expand the glob itself and
// Windows cmd does not either, so 'node --test collector/*.test.mjs' found no file there. Extra arguments are passed on.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));

export const testFiles = (d = dir) => fs.readdirSync(d).filter(f => f.endsWith('.test.mjs')).sort().map(f => path.join(d, f));

function main() {
  const files = testFiles();
  if (!files.length) { console.error('run-tests: no *.test.mjs file in', dir); process.exit(1); }
  const r = spawnSync(process.execPath, ['--test', ...process.argv.slice(2), ...files], { stdio: 'inherit' });
  if (r.error) { console.error('run-tests: could not start node --test:', r.error.message); process.exit(1); }
  process.exit(r.status ?? 1);
}

if (process.argv[1] && path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1])) main();
