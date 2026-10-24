import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { RateLimited } from './liquipedia.mjs';
import { fileOf, titlesOf, tabLinksOf, collectPage, collectAll, mergeStatus, acceptTitle, nextOf, koreaRootOf, newestKorea, computeActive, discoverCandidates } from './run-lp.mjs';

const fixture = name => fs.readFile(new URL('./fixtures/' + name, import.meta.url), 'utf8');
const DATES = await fixture('dates.wiki');
const comps = JSON.parse(await fs.readFile(new URL('../data/competitions.json', import.meta.url), 'utf8'));
const OCS = 'Overwatch Champions Series/';
const quiet = async fn => { const l = console.log, w = console.warn, out = []; console.log = console.warn = (...a) => out.push(a.join(' ')); try { return [await fn(), out]; } finally { console.log = l; console.warn = w; } };

// in-memory data/lp
const store = (files = {}) => ({ files, prev: async f => files[f] ?? null, write: async (f, d) => { files[f] = d; } });
const oldMatches = n => ({ title: 'T', matches: Array.from({ length: n }, (_, idx) => ({ idx })) });

test('fileOf keeps the existing data/lp names', () => {
  assert.equal(fileOf(OCS + '2025/Midseason Championship/LCQ/Group Stage'), 'data/lp/owcs-2025-midseason-championship-lcq-group-stage.json');
  assert.equal(fileOf('Overwatch World Cup/2026'), 'data/lp/owwc-2026.json');
});

test('collectPage writes the parse and reports matches / played / dateless / redirect', async () => {
  const s = store(), t = OCS + '2025/World Finals';
  const [st, log] = await quiet(() => collectPage(t, { ...s, page: async () => ({ text: DATES, redirect: OCS + '2025/WF', missing: false }) }));
  assert.deepEqual(st, { ok: true, matches: 5, played: 1, dateless: 1, redirect: OCS + '2025/WF', shrinkFrom: null, error: null });
  assert.equal(s.files[fileOf(t)].matches.length, 5);
  assert.ok(log.some(l => l.startsWith('MOVED ' + t)));
  assert.ok(log.some(l => l.startsWith('DATE? ' + t)));
});

test('SHRINK: fewer than half the old matches -> old file kept, failure', async () => {
  const t = OCS + '2026/Asia/Stage 3/Korea', s = store({ [fileOf(t)]: oldMatches(12) });
  const [st, log] = await quiet(() => collectPage(t, { ...s, page: async () => ({ text: DATES, redirect: null }) }));
  assert.equal(st.ok, false); assert.equal(st.shrinkFrom, 12); assert.equal(st.matches, 5); assert.match(st.error, /shrink 12 -> 5/);
  assert.equal(s.files[fileOf(t)].matches.length, 12);
  assert.ok(log.some(l => l.startsWith('SHRINK')));
  const [zero] = await quiet(() => collectPage(t, { ...s, page: async () => ({ text: 'no matches here', redirect: null }) }));
  assert.equal(zero.ok, false); assert.equal(s.files[fileOf(t)].matches.length, 12);
  // half or more is a normal update
  const [half] = await quiet(() => collectPage(t, { ...store({ [fileOf(t)]: oldMatches(10) }), page: async () => ({ text: DATES }) }));
  assert.equal(half.ok, true);
});

test('collectPage: fetch errors and missing pages that had matches fail, a never-seen missing page does not', async () => {
  const t = OCS + '2026/Asia/Stage 3', s = store();
  const [err] = await quiet(() => collectPage(t, { ...s, page: async () => { throw new Error('redirect not followed: #REDIRECT [[X]]'); } }));
  assert.equal(err.ok, false); assert.match(err.error, /redirect not followed/);
  const [miss] = await quiet(() => collectPage(t, { ...s, page: async () => ({ text: null, missing: true }) }));
  assert.equal(miss.ok, true); assert.equal(miss.missing, true); assert.equal(s.files[fileOf(t)], undefined);
  const [gone] = await quiet(() => collectPage(t, { ...store({ [fileOf(t)]: oldMatches(4) }), page: async () => ({ text: null, missing: true }) }));
  assert.equal(gone.ok, false); assert.match(gone.error, /missing \(kept 4 matches\)/);
  await assert.rejects(collectPage(t, { ...s, page: async () => { throw new RateLimited('60'); } }), RateLimited);
});

test('collectAll: a page that cannot be parsed or written fails alone, the next pages are still collected', async () => {
  const s = store();
  const write = async (f, d) => { if (f === fileOf('W')) throw Object.assign(new Error('EPERM: operation not permitted, rename'), { code: 'EPERM' }); s.files[f] = d; };
  const page = async t => ({ text: t === 'P' ? null : DATES });
  const [r, log] = await quiet(() => collectAll(['P', 'W', 'OK'], undefined, { prev: s.prev, write, page }));
  assert.equal(r.failures, 2);
  assert.equal(r.results.P.ok, false); assert.match(r.results.P.error, /^parse: /);
  assert.equal(r.results.W.ok, false); assert.match(r.results.W.error, /^write: EPERM/); assert.equal(r.results.W.matches, 5);
  assert.equal(r.results.OK.ok, true); assert.equal(s.files[fileOf('OK')].matches.length, 5);
  assert.ok(log.some(l => l.startsWith('ERR W write:')));
});

test('collectAll: a 429 stops the run, counts as a failure and leaves later pages alone', async () => {
  const s = store(); const asked = [];
  const page = async t => { asked.push(t); if (t === 'B') throw new RateLimited('30'); return { text: DATES }; };
  const [r] = await quiet(() => collectAll(['A', 'B', 'C', 'D'], async t => t === 'X', { ...s, page }));
  assert.deepEqual(asked, ['A', 'B']);
  assert.equal(r.failures, 1); assert.equal(r.rateLimit.retryAfter, '30'); assert.equal(r.rateLimit.skipped, 2);
  assert.equal(r.results.B.ok, false); assert.equal(r.results.C, undefined);
});

test('mergeStatus keeps lastOk of failed and unfetched pages, drops titles no longer collected', () => {
  const prev = { updatedAt: '2026-10-01T00:00:00.000Z', pages: {
    A: { ok: true, matches: 3, lastOk: '2026-10-01T00:00:00.000Z' },
    B: { ok: true, matches: 9, lastOk: '2026-10-01T00:00:00.000Z' },
    C: { ok: true, matches: 1, lastOk: '2026-09-01T00:00:00.000Z' },
    Gone: { ok: true, lastOk: '2026-01-01T00:00:00.000Z' } } };
  const now = '2026-10-24T00:00:00.000Z';
  const st = mergeStatus(prev, { A: { ok: true, matches: 4, error: null }, B: { ok: false, matches: 2, shrinkFrom: 9, error: 'shrink 9 -> 2' } }, { now, titles: ['A', 'B', 'C', 'New'], failures: 1 });
  assert.equal(st.updatedAt, now); assert.equal(st.failures, 1); assert.equal(st.rateLimit, null);
  assert.equal(st.pages.A.lastOk, now); assert.equal(st.pages.A.matches, 4);
  assert.equal(st.pages.B.lastOk, '2026-10-01T00:00:00.000Z'); assert.equal(st.pages.B.ok, false);
  assert.deepEqual(st.pages.C, prev.pages.C);
  assert.deepEqual(Object.keys(st.pages), ['A', 'B', 'C']);
  assert.equal(mergeStatus(null, { X: { ok: false } }, { now, titles: ['X'], failures: 1 }).pages.X.lastOk, null);
});

test('titlesOf: World Cup pages only when collected already or active by their exact title (not the qualifiers below)', async () => {
  const c = { core: ['K'], world_cup: ['Overwatch World Cup/2023', 'Overwatch World Cup/2027', 'Overwatch World Cup/2027/Asia Qualifier'] };
  assert.deepEqual(await titlesOf(c, [], async t => t === 'Overwatch World Cup/2023'), ['K', 'Overwatch World Cup/2023']);
  assert.deepEqual(await titlesOf(c, ['Overwatch World Cup/2027'], async () => false), ['K', 'Overwatch World Cup/2027']);
  assert.deepEqual(await titlesOf(c, ['Overwatch World Cup/2027/Asia Qualifier'], async () => false), ['K', 'Overwatch World Cup/2027/Asia Qualifier']);
  // the committed lists: only the two main World Cup pages, as before the date-based active.json
  assert.deepEqual((await titlesOf(comps, comps.world_cup.filter(t => /20(23|26)$/.test(t)), async () => false)).filter(t => t.includes('World Cup')),
    ['Overwatch World Cup/2023', 'Overwatch World Cup/2026']);
});

test('acceptTitle takes every page shape already in competitions.json and nothing else', () => {
  for (const t of comps.core) assert.ok(acceptTitle(t, [+t.split('/')[1]]), t);
  const y = [2027];
  for (const t of ['2027/Asia/Stage 1', '2027/Asia/Stage 1/Korea', '2027/Asia/Stage 1/Korea/Regular Season', '2027/Asia/Stage 2/Korea/Open Qualifier',
    '2027/Asia/Stage 2/Korea/Relegation', '2027/Asia/Stage 3/Championship/Korea', '2027/Champions Clash', '2027/Midseason Championship/LCQ/Group Stage',
    '2027/World Finals', '2027/World Finals/Group Stage']) assert.ok(acceptTitle(OCS + t, y), t);
  for (const t of ['2027/EMEA/Stage 1', '2027/Asia/Stage 1/Japan', '2027/Asia/Stage 1/Korea/Playoffs/Extra', '2027/Midseason Championship/Last Chance Qualifier',
    '2026/World Finals', '2027', '2027/Asia/Stage 1/Korea/Regular Season/Week 1']) assert.ok(!acceptTitle(OCS + t, y), t);
  assert.ok(!acceptTitle('Overwatch Contenders/2027/Korea', y));
});

test('nextOf / koreaRootOf / newestKorea', () => {
  assert.equal(nextOf(DATES), OCS + '2027/Asia/Stage 1/Korea');
  assert.equal(nextOf('|next=[[Overwatch_Champions_Series/2027/Asia/Stage_1/Korea|Stage 1]]'), OCS + '2027/Asia/Stage 1/Korea');
  assert.equal(nextOf('| next = Overwatch Champions Series/2027/Asia/Stage 1{{!}}Stage 1'), OCS + '2027/Asia/Stage 1');
  assert.equal(nextOf('|next=\n|prev=x'), null);
  assert.equal(nextOf('|next=Overwatch Contenders/2027'), null);
  assert.equal(koreaRootOf(OCS + '2027/Asia/Stage 1/Korea/Regular Season'), OCS + '2027/Asia/Stage 1/Korea');
  assert.equal(koreaRootOf(OCS + '2027/Asia/Stage 1'), OCS + '2027/Asia/Stage 1/Korea');
  assert.equal(koreaRootOf(OCS + '2027/World Finals'), null);
  assert.equal(newestKorea(comps.core), OCS + '2026/Asia/Stage 3/Korea');
});

test('computeActive: dated within +-30 days (KST), or this year and nothing dated / undated matches left; no file -> not listed', () => {
  const m = (date, played = true) => ({ date, played });
  const pages = {
    [OCS + '2026/Asia/Stage 3/Korea/Regular Season']: [m('2026-10-02T17:15:00+09:00'), m('2026-10-25T18:00:00+09:00', false)],
    [OCS + '2026/Asia/Stage 3/Korea']: [m('2026-10-30T00:00:00+09:00', false)],
    [OCS + '2026/Asia/Stage 2/Korea']: [m('2026-07-12T17:20:00+09:00')],
    [OCS + '2026/World Finals']: [],
    [OCS + '2026/Asia/Stage 3']: null,
    [OCS + '2025/World Finals']: [m('2025-11-30T15:20:00+01:00')],
    [OCS + '2025/Asia/Stage 3/Korea']: null,
    [OCS + '2026/Asia/Stage 3/Championship/Korea']: [m('2026-08-01T00:00:00+09:00'), m(null, false)],
    [OCS + '2026/Asia/Stage 1/Korea']: [m('2026-04-24T17:35:00+09:00'), m(null, true)],
    'Overwatch World Cup/2026': [m('2026-09-13T15:50:00-07:00')],
    [OCS + '2027/Champions Clash']: [],
    [OCS + '2027/Asia/Stage 1/Korea']: null,
    // 23:30 UTC on 11-22 is 11-23 in KST: still inside the window, 11-24 KST is not
    [OCS + '2026/Edge In']: [m('2026-11-22T23:30:00+00:00')],
    [OCS + '2025/Edge Out']: [m('2026-11-23T15:30:00+00:00')],
  };
  const titles = Object.keys(pages);
  const active = computeActive({ titles, pages, today: '2026-10-24' });
  assert.deepEqual(active, [OCS + '2026/Asia/Stage 3/Korea/Regular Season', OCS + '2026/Asia/Stage 3/Korea', OCS + '2026/World Finals',
    OCS + '2026/Asia/Stage 3/Championship/Korea', OCS + '2027/Champions Clash', OCS + '2026/Edge In']);
  // the missing '2026/Asia/Stage 3' overview would substring-match (cloud_live, --active-only) every page of the stage
  assert.ok(!active.includes(OCS + '2026/Asia/Stage 3') && !active.includes(OCS + '2027/Asia/Stage 1/Korea'));
  assert.deepEqual(computeActive({ titles, pages, today: '2026-10-24' }), active);   // pure: same input, same list
  // only full titles are written to active.json (they match exactly; a short one would substring-match)
  assert.ok(active.every(t => t.startsWith('Overwatch ')));
  assert.deepEqual(computeActive({ titles: ['2026/Asia/Stage 3/Korea'], pages: { '2026/Asia/Stage 3/Korea': [] }, today: '2026-10-24' }), []);
  // new year: last year's pages with nothing dated or undated matches left drop out
  assert.deepEqual(computeActive({ titles, pages, today: '2027-01-20' }), [OCS + '2027/Champions Clash']);
});

test('discoverCandidates: |next= of the newest Korea page and the page list of this year and next', async () => {
  const core = [OCS + '2026/Asia/Stage 2/Korea', OCS + '2026/Asia/Stage 3/Korea', OCS + '2026/World Finals'];
  const asked = { page: [], list: [] };
  const lists = {
    [OCS + '2026/']: [OCS + '2026/World Finals', OCS + '2026/Asia/Stage 3/Korea/Relegation', OCS + '2026/NA/Stage 3', OCS + '2026/Stage 1/Pre-Season Bootcamp', OCS + '2026/Asia/Stage 3/Korea/Regular_Season'],
    [OCS + '2027/']: [OCS + '2027/Champions Clash', OCS + '2027/Asia/Stage 1/Korea/Open Qualifier', OCS + '2027/EMEA/Stage 1'],
  };
  const deps = { page: async t => { asked.page.push(t); return { text: DATES }; }, list: async p => { asked.list.push(p); return lists[p] || []; } };
  const got = await discoverCandidates(core, [2026, 2027], deps);
  assert.deepEqual(asked.page, [OCS + '2026/Asia/Stage 3/Korea']);
  assert.deepEqual(asked.list, [OCS + '2026/', OCS + '2027/']);
  assert.deepEqual(got, [OCS + '2026/Asia/Stage 3/Korea/Regular Season', OCS + '2026/Asia/Stage 3/Korea/Relegation', OCS + '2027/Asia/Stage 1/Korea',
    OCS + '2027/Asia/Stage 1/Korea/Open Qualifier', OCS + '2027/Champions Clash']);
  // everything known already: nothing new (idempotent)
  assert.deepEqual(await discoverCandidates([...core, ...got], [2026, 2027], deps), []);
});

test('real Korea stage page header: tab links, empty |next=', async () => {
  const k = await fixture('korea-2026-s3-infobox.wiki');
  assert.deepEqual(tabLinksOf(k), [OCS + '2026/Asia/Stage 3/Korea', OCS + '2026/Asia/Stage 3/Korea/Regular Season', OCS + '2026/Asia/Stage 3/Korea/Open Qualifier']);
  assert.equal(nextOf(k), null);
  const got = await discoverCandidates([OCS + '2026/Asia/Stage 3/Korea'], [2026, 2027], { page: async () => ({ text: k }), list: async () => [] });
  assert.deepEqual(got, [OCS + '2026/Asia/Stage 3/Korea/Open Qualifier', OCS + '2026/Asia/Stage 3/Korea/Regular Season']);
});

// ---- the CLI end to end: exit codes and files, with fetch swapped by a preload (no request leaves the machine) ----
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const RUN_LP = fileURLToPath(new URL('./run-lp.mjs', import.meta.url));
const PRELOAD = `import { cfg } from ${JSON.stringify(new URL('./liquipedia.mjs', import.meta.url).href)};
cfg.delay = 0;
const mode = process.env.LP_FAKE, text = process.env.LP_TEXT;
if (mode === 'nofetch') delete globalThis.fetch;
cfg.fetch = async () => {
  if (mode === 'down') throw new TypeError('fetch failed');
  if (mode === '429') return new Response('{}', { status: 429, headers: { 'retry-after': '90' } });
  return new Response(JSON.stringify({ query: { pages: { 1: { title: 'X', revisions: [{ slots: { main: { '*': text } } }] } } } }), { status: 200 });
};`;
async function cli(args, mode, { core = [OCS + '2026/A', OCS + '2026/B'], lp = {}, active = [] } = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'run-lp-cli-'));
  await fs.mkdir(path.join(dir, 'data/lp'), { recursive: true });
  await fs.writeFile(path.join(dir, 'data/competitions.json'), JSON.stringify({ core }));
  await fs.writeFile(path.join(dir, 'data/active.json'), JSON.stringify(active));
  for (const [f, d] of Object.entries(lp)) await fs.writeFile(path.join(dir, f), JSON.stringify(d));
  await fs.writeFile(path.join(dir, 'preload.mjs'), PRELOAD);
  const r = spawnSync(process.execPath, ['--import', pathToFileURL(path.join(dir, 'preload.mjs')).href, RUN_LP, ...args],
    { cwd: dir, encoding: 'utf8', env: { ...process.env, LP_FAKE: mode, LP_TEXT: DATES }, timeout: 60e3 });
  const read = async f => JSON.parse(await fs.readFile(path.join(dir, f), 'utf8'));
  return { code: r.status, out: r.stdout + r.stderr, read, done: () => fs.rm(dir, { recursive: true, force: true }) };
}

test('CLI: network down -> exit 2 with --strict, 0 without; per-page errors in _status.json, old data/lp file kept', async () => {
  const soft = await cli([], 'down');
  try {
    assert.equal(soft.code, 0, soft.out); assert.match(soft.out, /2 failed \(exit 0: pass --strict to exit 2\)/);
    assert.equal((await soft.read('data/lp/_status.json')).failures, 2);
  } finally { await soft.done(); }
  const r = await cli(['--strict'], 'down', { lp: { [fileOf(OCS + '2026/A')]: oldMatches(3) } });
  try {
    assert.equal(r.code, 2, r.out);
    const st = await r.read('data/lp/_status.json');
    assert.equal(st.failures, 2);
    assert.match(st.pages[OCS + '2026/A'].error, /^network: fetch failed/); assert.equal(st.pages[OCS + '2026/A'].lastOk, null);
    assert.equal((await r.read(fileOf(OCS + '2026/A'))).matches.length, 3);
  } finally { await r.done(); }
});

test('CLI: every page read -> exit 0; 429 -> exit 2 with rateLimit (--strict); no fetch -> exit 3; --discover offline -> 2 / 0', async () => {
  const ok = await cli(['--active-only', '--strict'], 'ok');
  try {
    assert.equal(ok.code, 0, ok.out);
    const st = await ok.read('data/lp/_status.json');
    assert.equal(st.failures, 0); assert.equal(st.pages[OCS + '2026/B'].matches, 5);
  } finally { await ok.done(); }
  const rl = await cli(['--strict'], '429');
  try {
    assert.equal(rl.code, 2, rl.out);
    const st = await rl.read('data/lp/_status.json');
    assert.equal(st.rateLimit.retryAfter, '90'); assert.equal(st.rateLimit.skipped, 1); assert.equal(st.pages[OCS + '2026/B'], undefined);
  } finally { await rl.done(); }
  const old = await cli([], 'nofetch');
  try { assert.equal(old.code, 3, old.out); assert.match(old.out, /Node 20\+ is required/); } finally { await old.done(); }
  const core = [OCS + '2026/Asia/Stage 3/Korea'];
  const disc = await cli(['--discover', '--strict'], 'down', { core });
  try { assert.equal(disc.code, 2, disc.out); assert.deepEqual((await disc.read('data/competitions.json')).core, core); } finally { await disc.done(); }
  const soft = await cli(['--discover'], 'down', { core });
  try { assert.equal(soft.code, 0, soft.out); assert.match(soft.out, /ERR discover failed, nothing written: network/); } finally { await soft.done(); }
});

test('CLI --active-only: an active full title re-reads only that page, not the collected pages below it (RC-12)', async () => {
  const K = OCS + '2026/Asia/Stage 3/Korea', OQ = K + '/Open Qualifier';
  const r = await cli(['--active-only'], 'ok', { core: [K, OQ], active: [K], lp: { [fileOf(K)]: oldMatches(5), [fileOf(OQ)]: oldMatches(5) } });
  try {
    assert.equal(r.code, 0, r.out);
    assert.deepEqual(Object.keys((await r.read('data/lp/_status.json')).pages), [K]);
  } finally { await r.done(); }
  const legacy = await cli(['--active-only'], 'ok', { core: [K, OQ], active: ['2026/Asia/Stage 3/Korea'], lp: { [fileOf(K)]: oldMatches(5), [fileOf(OQ)]: oldMatches(5) } });
  try { assert.deepEqual(Object.keys((await legacy.read('data/lp/_status.json')).pages), [K, OQ]); } finally { await legacy.done(); }
});
