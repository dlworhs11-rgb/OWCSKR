// build.mjs end to end in a temp dir: mapstats matchKey links (RA-17) and per-player rows of non-latin handles (RC-18)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const BUILD = fileURLToPath(new URL('./build.mjs', import.meta.url));
const RS = 'Overwatch Champions Series/2026/Asia/Stage 3/Korea/Regular Season', K = 'Overwatch Champions Series/2026/Asia/Stage 3/Korea';
const match = (idx, date, team1, team2) => ({ competition: 'x', idx, date, bestof: 5, team1, team2, score1: 3, score2: 1, winner: 1, played: true, maps: [] });
const row = (name, e) => ({ name, e, a: 1, d: 2, dmg: 1000, heal: 0, mit: 0 });
const mapEntry = (game, teams, extra = {}) => ({ match: 'T1 vs O2 Blast', game, map: 'Busan', mapTime: '10:00', teams, reading: 'ocr', ...extra });

async function build(files) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'build-test-'));
  for (const [f, d] of Object.entries(files)) {
    await fs.mkdir(path.dirname(path.join(dir, f)), { recursive: true });
    await fs.writeFile(path.join(dir, f), JSON.stringify(d));
  }
  const r = spawnSync(process.execPath, [BUILD], { cwd: dir, encoding: 'utf8', timeout: 60e3 });
  const read = async n => JSON.parse(await fs.readFile(path.join(dir, 'data/site', n + '.json'), 'utf8'));
  return { code: r.status, out: r.stdout + r.stderr, read, done: () => fs.rm(dir, { recursive: true, force: true }) };
}

test('build: mapstats matchKey picks the same-day rematch, no key -> first match that day, dropped copy key -> kept copy', async () => {
  const first = match(0, '2026-10-25T15:00:00+09:00', 'T1', 'O2 Blast'), rematch = match(1, '2026-10-25T20:00:00+09:00', 'O2 Blast', 'T1');
  const korean = { T1: [row('희상', 10), row('준혁', 4)], 'O2 Blast': [row('Lip', 7)] };
  const r = await build({
    'data/aliases.json': {},
    'data/lp/owcs-rs.json': { title: RS, matches: [first, rematch] },
    // the stage page lists the first match too: the dedupe keeps the Regular Season copy
    'data/lp/owcs-k.json': { title: K, matches: [match(0, first.date, 'T1', 'O2 Blast')] },
    'data/manual/mapstats/2026-10-25.json': {
      date: '2026-10-25',
      maps: [
        mapEntry(1, korean, { matchKey: RS + '#1' }),
        mapEntry(1, { T1: [row('희상', 1)], 'O2 Blast': [row('Lip', 1)] }),
        mapEntry(2, { T1: [row('희상', 1)], 'O2 Blast': [row('Lip', 1)] }, { matchKey: K + '#0' }),
      ],
      matches: [{ match: 'T1 vs O2 Blast', matchKey: RS + '#1', potm: { name: 'Lip' }, mapWins: { T1: 3 } }],
    },
  });
  try {
    assert.equal(r.code, 0, r.out);
    assert.match(r.out, /mapstats: maps 3 linked 3 \(by matchKey 2\)/);
    const ms = await r.read('matches');
    const at = d => ms.find(m => m.date === d);
    assert.deepEqual(at(rematch.date).mapStats.map(s => s.game), [1]);
    assert.deepEqual(at(rematch.date).potmLive, { name: 'Lip' });
    assert.deepEqual(at(first.date).mapStats.map(s => s.game), [1, 2]);
    assert.equal(at(first.date).potmLive, undefined);
    assert.equal(at(first.date).competitionTitle, RS);
    // RC-18: two Hangul handles of one team are two rows, not one row keyed ''
    const ps = await r.read('player-stats');
    const t1 = ps.filter(p => p.team === 'T1').map(p => [p.handle, p.maps, p.e]).sort();
    assert.deepEqual(t1, [['준혁', 1, 4], ['희상', 3, 12]]);
  } finally { await r.done(); }
});

test('build: a matchKey this build does not know is logged and falls back to date + teams', async () => {
  const r = await build({
    'data/aliases.json': {},
    'data/lp/owcs-rs.json': { title: RS, matches: [match(0, '2026-10-25T15:00:00+09:00', 'T1', 'O2 Blast')] },
    'data/manual/mapstats/2026-10-25.json': { date: '2026-10-25', maps: [mapEntry(1, { T1: [row('A', 1)], 'O2 Blast': [row('B', 1)] }, { matchKey: RS + '#9' })] },
  });
  try {
    assert.equal(r.code, 0, r.out);
    assert.match(r.out, /mapstats: unknown matchKey ".*#9" -> matched by date \+ teams/);
    assert.equal((await r.read('matches'))[0].mapStats.length, 1);
  } finally { await r.done(); }
});
