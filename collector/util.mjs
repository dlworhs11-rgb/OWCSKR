// Small helpers shared by the collector scripts (kept dependency-free and side-effect-free so tests can import them).
import fs from 'node:fs/promises';
import path from 'node:path';

// null when the file is missing or not JSON (a truncated file counts as no previous copy)
export const readJson = f => fs.readFile(f, 'utf8').then(JSON.parse).catch(() => null);

// tmp + rename: a run killed mid-write (timeout, OOM) leaves the old file, not half a file
export async function writeJson(f, data, indent = 1) {
  await fs.mkdir(path.dirname(f), { recursive: true });
  await fs.writeFile(f + '.tmp', JSON.stringify(data, null, indent));
  await fs.rename(f + '.tmp', f);
}

export const kstDay = d => new Date(new Date(d).getTime() + 9 * 3600e3).toISOString().slice(0, 10);

// broadcast rows the name reader did not know: old '?3' names and the new { name: null, unknownId: '?3' } shape
export const knownPlayer = r => {
  const n = typeof r?.name === 'string' ? r.name.trim() : '';
  return n !== '' && !/^\?\d+$/.test(n);
};
