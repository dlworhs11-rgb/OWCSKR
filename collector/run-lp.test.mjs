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

test('titlesOf: World Cup pages only when collected already or active', async () => {
  const c = { core: ['K'], world_cup: ['Overwatch World Cup/2023', 'Overwatch World Cup/2027', 'Overwatch World Cup/2027/Asia Qualifier'] };
  assert.deepEqual(await titlesOf(c, [], async t => t === 'Overwatch World Cup/2023'), ['K', 'Overwatch World Cup/2023']);
  assert.deepEqual(await titlesOf(c, ['Overwatch World Cup/2027'], async () => false), ['K', 'Overwatch World Cup/2027', 'Overwatch World Cup/2027/Asia Qualifier']);
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

test('computeActive: dated within +-30 days (KST), or this year and nothing dated / undated matches left', () => {
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
    [OCS + '2027/Champions Clash']: null,
    // 23:30 UTC on 11-22 is 11-23 in KST: still inside the window, 11-24 KST is not
    [OCS + '2026/Edge In']: [m('2026-11-22T23:30:00+00:00')],
    [OCS + '2025/Edge Out']: [m('2026-11-23T15:30:00+00:00')],
  };
  const titles = Object.keys(pages);
  const active = computeActive({ titles, pages, today: '2026-10-24' });
  assert.deepEqual(active, [OCS + '2026/Asia/Stage 3/Korea/Regular Season', OCS + '2026/Asia/Stage 3/Korea', OCS + '2026/World Finals', OCS + '2026/Asia/Stage 3',
    OCS + '2026/Asia/Stage 3/Championship/Korea', OCS + '2027/Champions Clash', OCS + '2026/Edge In']);
  assert.deepEqual(computeActive({ titles, pages, today: '2026-10-24' }), active);   // pure: same input, same list
  assert.ok(computeActive({ titles, pages, today: '2027-01-20' }).every(t => /\/2027\//.test(t)));
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
