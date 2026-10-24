import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { knownPlayer, kstDay, readJson, writeJson, renameRetry, addPlayerRow, isActiveTitle } from './util.mjs';

test('knownPlayer skips unknown broadcast names in both published shapes', () => {
  assert.equal(knownPlayer({ name: 'HeeSang' }), true);
  assert.equal(knownPlayer({ name: '?3' }), false);
  assert.equal(knownPlayer({ name: ' ?12 ' }), false);
  assert.equal(knownPlayer({ name: null, unknownId: '?3' }), false);
  assert.equal(knownPlayer({ name: '' }), false);
  assert.equal(knownPlayer({}), false);
  assert.equal(knownPlayer({ name: '?Mark' }), true);   // a real handle may start with '?': only '?<digits>' is a placeholder
});

test('kstDay', () => {
  assert.equal(kstDay('2026-10-24T15:00:00+00:00'), '2026-10-25');
  assert.equal(kstDay('2026-10-24T14:59:00+00:00'), '2026-10-24');
});

test('writeJson replaces the file through a tmp file; readJson gives null for missing / broken files', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'util-test-'));
  try {
    const f = path.join(dir, 'a', 'x.json');
    await writeJson(f, { a: 1 });
    assert.deepEqual(await readJson(f), { a: 1 });
    assert.deepEqual(await fs.readdir(path.dirname(f)), ['x.json']);
    assert.equal(await readJson(path.join(dir, 'none.json')), null);
    await fs.writeFile(path.join(dir, 'bad.json'), '{');
    assert.equal(await readJson(path.join(dir, 'bad.json')), null);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test('renameRetry: busy target (Windows EPERM / EBUSY) is tried again, other errors and the last try are thrown', async () => {
  const err = code => Object.assign(new Error(code), { code });
  const fake = fails => { let n = 0; const fn = async () => { n++; if (fails.length) throw err(fails.shift()); }; fn.count = () => n; return fn; };
  const ok = fake(['EPERM', 'EBUSY', 'EACCES']);
  await renameRetry('a', 'b', { rename: ok }); assert.equal(ok.count(), 4);
  const other = fake(['ENOENT']);
  await assert.rejects(renameRetry('a', 'b', { rename: other }), /ENOENT/); assert.equal(other.count(), 1);
  const stuck = fake(['EPERM', 'EPERM', 'EPERM']);
  await assert.rejects(renameRetry('a', 'b', { rename: stuck, tries: 3 }), /EPERM/); assert.equal(stuck.count(), 3);
});

test('addPlayerRow: a null assist count is left out (not added as 0), aMaps counts the maps that had one', () => {
  const acc = { maps: 0, secs: 0, e: 0, a: 0, aMaps: 0, d: 0, dmg: 0, heal: 0, mit: 0 };
  addPlayerRow(acc, { e: 10, a: 4, d: 2, dmg: 9000, heal: 0, mit: 100 }, 600);
  addPlayerRow(acc, { e: 5, a: null, d: 3, dmg: 4000, heal: 0, mit: 50 }, null);
  assert.deepEqual(acc, { maps: 2, secs: 600, e: 15, a: 4, aMaps: 1, d: 5, dmg: 13000, heal: 0, mit: 150 });
  addPlayerRow(acc, { e: 1, a: 0, d: 0, dmg: 0, heal: 0, mit: 0 }, 60);
  assert.equal(acc.a, 4); assert.equal(acc.aMaps, 2);   // a real 0 counts
});

test('isActiveTitle: full titles match exactly, short legacy entries by substring', () => {
  const K = 'Overwatch Champions Series/2026/Asia/Stage 3/Korea';
  assert.equal(isActiveTitle(K, [K]), true);
  assert.equal(isActiveTitle(K + '/Open Qualifier', [K]), false);   // RC-12: the finished qualifier is not pulled in
  assert.equal(isActiveTitle(K + '/Regular Season', [K]), false);
  assert.equal(isActiveTitle(K + '/Regular Season', [K, K + '/Regular Season']), true);
  assert.equal(isActiveTitle(K + '/Open Qualifier', ['2026/Asia/Stage 3']), true);   // short form: substring, as before
  assert.equal(isActiveTitle('Overwatch Champions Series/2027/Asia/Stage 1/Korea', ['2027/Asia/Stage 1/Korea']), true);
  assert.equal(isActiveTitle('Overwatch World Cup/2026/Asia Online Qualifier', ['Overwatch World Cup/2026']), false);
  assert.equal(isActiveTitle(K, []), false);
  assert.equal(isActiveTitle(K, null), false);
  assert.equal(isActiveTitle(K, ['', null, 3]), false);   // a blank entry would substring-match every page
});
