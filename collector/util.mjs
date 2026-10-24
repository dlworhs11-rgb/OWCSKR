// Small helpers shared by the collector scripts (kept dependency-free and side-effect-free so tests can import them).
import fs from 'node:fs/promises';
import path from 'node:path';

// null when the file is missing or not JSON (a truncated file counts as no previous copy)
export const readJson = f => fs.readFile(f, 'utf8').then(JSON.parse).catch(() => null);

// Windows refuses to rename over a file another process has open (EPERM; a Python reader is enough) or that a
// scanner holds (EBUSY / EACCES): those are tried again for ~1.5 s
const BUSY = new Set(['EPERM', 'EACCES', 'EBUSY']);
export async function renameRetry(from, to, { tries = 6, rename = fs.rename } = {}) {
  for (let i = 0; ; i++) {
    try { return await rename(from, to); }
    catch (e) { if (i >= tries - 1 || !BUSY.has(e.code)) throw e; await new Promise(r => setTimeout(r, 50 * 2 ** i)); }
  }
}

// tmp + rename: a run killed mid-write (timeout, OOM) leaves the old file, not half a file
export async function writeAtomic(f, text) {
  await fs.mkdir(path.dirname(f), { recursive: true });
  await fs.writeFile(f + '.tmp', text);
  try { await renameRetry(f + '.tmp', f); }
  catch (e) { await fs.rm(f + '.tmp', { force: true }); throw e; }
}
export const writeJson = (f, data, indent = 1) => writeAtomic(f, JSON.stringify(data, null, indent));

export const kstDay = d => new Date(new Date(d).getTime() + 9 * 3600e3).toISOString().slice(0, 10);

// broadcast rows the name reader did not know: old '?3' names and the new { name: null, unknownId: '?3' } shape
export const knownPlayer = r => {
  const n = typeof r?.name === 'string' ? r.name.trim() : '';
  return n !== '' && !/^\?\d+$/.test(n);
};
