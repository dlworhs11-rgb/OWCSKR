import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { knownPlayer, kstDay, readJson, writeJson } from './util.mjs';

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
