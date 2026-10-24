import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { cfg, parseDate, parseMatches, cleanLabel, fetchPage, linksOf, pagesWithPrefix, resolveTitles, isRedirectBody, RateLimited } from './liquipedia.mjs';

const fixture = name => fs.readFile(new URL('./fixtures/' + name, import.meta.url), 'utf8');
const DATES = await fixture('dates.wiki'), WF = await fixture('wf2025-excerpt.wiki');
const quiet = fn => { const w = console.warn, out = []; console.warn = (...a) => out.push(a); try { return [fn(), out]; } finally { console.warn = w; } };

test('parseDate: abbreviated, dotted and full month names, ISO dates', () => {
  assert.equal(parseDate('Nov 26, 2025 - 16:05 {{Abbr/CET}}'), '2025-11-26T16:05:00+01:00');
  assert.equal(parseDate('Sept. 5, 2026 - 17:00 {{Abbr/KST}}'), '2026-09-05T17:00:00+09:00');
  assert.equal(parseDate('Sep 5, 2026'), '2026-09-05T00:00:00+00:00');
  assert.equal(parseDate('September 5th, 2026 - 9:30 {{Abbr/KST}}'), '2026-09-05T09:30:00+09:00');
  assert.equal(parseDate('Feb. 1 2026'), '2026-02-01T00:00:00+00:00');
  assert.equal(parseDate('2026-10-02 - 17:15 {{Abbr/KST}}'), '2026-10-02T17:15:00+09:00');
  assert.equal(parseDate('Smarch 7, 2026'), null);
  assert.equal(parseDate('Ma 7, 2026'), null);
  assert.equal(parseDate(''), null);
  assert.equal(parseDate(undefined), null);
});

test('parseDate: lower-case {{abbr/..}}, 12 h times, unknown zones reported', () => {
  assert.equal(parseDate('Oct 25, 2026 - 18:00 {{abbr/KST}}'), '2026-10-25T18:00:00+09:00');
  assert.equal(parseDate('Oct 25, 2026 - 6:00 PM {{Abbr/KST}}'), '2026-10-25T18:00:00+09:00');
  assert.equal(parseDate('Oct 25, 2026 - 12:30 a.m. {{Abbr/KST}}'), '2026-10-25T00:30:00+09:00');
  assert.equal(parseDate('Oct 25, 2026 - 12:05pm {{Abbr/KST}}'), '2026-10-25T12:05:00+09:00');
  assert.equal(parseDate('Feb 3, 2027 - 19:00 {{Abbr/AEDT}}'), '2027-02-03T19:00:00+11:00');
  const info = {};
  assert.equal(parseDate('Feb 3, 2027 - 19:00 {{Abbr/XYZT}}', info), '2027-02-03T19:00:00+00:00');
  assert.equal(info.zone, 'XYZT');
  const known = {}; parseDate('Feb 3, 2027 - 19:00 {{Abbr/KST}}', known); assert.equal(known.zone, undefined);
  const [, warns] = quiet(() => parseMatches('{{Match|date=Feb 3, 2027 - 19:00 {{Abbr/XYZT}}|opponent1=A|opponent2=B}}', 'X'));
  assert.deepEqual(warns.map(w => w[0]), ['TZ?']);
});

test('parseMatches: every written date parses or is counted as dateless with a DATE? warning', async () => {
  const stats = {};
  const [ms, warns] = quiet(() => parseMatches('', 'x', stats));
  assert.equal(ms.length, 0); assert.equal(stats.dateless, 0); assert.equal(warns.length, 0);
  const [m2, w2] = quiet(() => parseMatches(DATES, 'Fixture', stats));
  assert.deepEqual(m2.map(m => m.date), ['2025-11-26T16:05:00+01:00', '2026-09-05T17:00:00+09:00', '2026-09-06T18:30:00+09:00', null, null]);
  assert.equal(stats.dateless, 1);   // 'Smarch 7' is written but unknown; the empty |date= is not counted
  assert.equal(w2.length, 1);
  assert.deepEqual(w2[0].slice(0, 3), ['DATE?', 'Fixture', 3]);
  assert.equal(m2[0].played, true); assert.equal(m2[0].winner, 1); assert.equal(m2[0].potm, 'Becky');
  assert.equal(m2[0].section, 'Playoffs'); assert.equal(m2[0].round, 'Grand Final');
});

test('parseMatches: a CRLF copy of a page parses the same as LF', () => {
  const lf = quiet(() => parseMatches(DATES, 'x'))[0], crlf = quiet(() => parseMatches(DATES.replace(/\r?\n/g, '\r\n'), 'x'))[0];
  assert.equal(lf.length, 5);
  assert.deepEqual(crlf, lf);
});

test('isRedirectBody', async () => {
  assert.equal(isRedirectBody(await fixture('redirect.wiki')), true);
  assert.equal(isRedirectBody(DATES), false);
});

// ---- network layer with a fake fetch ----
let calls, replies, dir;
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });
const pageReply = (title, text, extra = {}) => json({ query: { ...extra, pages: { 1: { pageid: 1, ns: 0, title, revisions: [{ slots: { main: { '*': text } } }] } } } });
const saved = { ...cfg };
beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'lp-test-'));
  calls = []; replies = [];
  Object.assign(cfg, { delay: 0, cache: dir, fetch: async (url, opts) => { calls.push({ url: new URL(url), opts }); const r = replies.shift(); if (r instanceof Error) throw r; return typeof r === 'function' ? r() : r; } });
});
afterEach(async () => { Object.assign(cfg, saved); await fs.rm(dir, { recursive: true, force: true }); });

test('fetchPage asks with redirects=1 and maxlag=5, reports the move, and remembers it for cached reads', async () => {
  const to = 'Overwatch Champions Series/2025/Midseason Championship/LCQ';
  replies.push(pageReply(to, '{{Match|date=Jul 19, 2025}}', { redirects: [{ from: 'Old', to }] }));
  const r = await fetchPage('Old');
  assert.equal(r.redirect, to); assert.equal(r.cached, false);
  const q = calls[0].url.searchParams;
  assert.equal(q.get('redirects'), '1'); assert.equal(q.get('maxlag'), '5'); assert.equal(q.get('titles'), 'Old');
  assert.ok(calls[0].opts.signal instanceof AbortSignal);
  const again = await fetchPage('Old');
  assert.equal(again.cached, true); assert.equal(again.redirect, to); assert.equal(calls.length, 1);
});

test('fetchPage: a #REDIRECT body is an error and is not cached', async () => {
  replies.push(pageReply('Old', await fixture('redirect.wiki')), pageReply('Old', await fixture('redirect.wiki')));
  await assert.rejects(fetchPage('Old'), /redirect not followed/);
  await assert.rejects(fetchPage('Old'), /redirect not followed/);
  assert.equal(calls.length, 2);
});

test('fetchPage: a missing page is not asked again for 6 h (collector file, epoch seconds)', async () => {
  replies.push(json({ query: { pages: { '-1': { ns: 0, title: 'Nope', missing: '' } } } }));
  assert.equal((await fetchPage('Nope')).missing, true);
  const again = await fetchPage('Nope');
  assert.equal(again.missing, true); assert.equal(again.cached, true); assert.equal(calls.length, 1);
  const m = JSON.parse(await fs.readFile(path.join(dir, '_missing_collector.json'), 'utf8'));
  assert.equal(typeof m.Nope, 'number'); assert.ok(m.Nope * 1000 <= Date.now() && m.Nope * 1000 > Date.now() - 60e3);
  await assert.rejects(fs.access(path.join(dir, '_missing.json')));   // the site's file is not created
});

test('fetchPage: own entries in seconds or ISO honoured; the site _missing.json is not read, only cleared of old ISO strings', async () => {
  const now = Date.now();
  await fs.writeFile(path.join(dir, '_missing_collector.json'), JSON.stringify({ Sec: now / 1000 - 60, Iso: new Date(now - 60e3).toISOString(), Old: now / 1000 - 7 * 3600, Bad: 'x' }));
  await fs.writeFile(path.join(dir, '_missing.json'), JSON.stringify({ Site: now / 1000 - 60, Stale: new Date(now).toISOString() }));
  assert.equal((await fetchPage('Sec')).cached, true);
  assert.equal((await fetchPage('Iso')).cached, true);
  assert.equal(calls.length, 0);
  replies.push(pageReply('Old', 'back'), pageReply('Bad', 'here'), pageReply('Site', 'own copy'));
  assert.equal((await fetchPage('Old')).text, 'back');
  assert.equal((await fetchPage('Bad')).text, 'here');
  assert.equal((await fetchPage('Site')).text, 'own copy');   // the site's note does not stop the collector
  assert.deepEqual(Object.keys(JSON.parse(await fs.readFile(path.join(dir, '_missing_collector.json'), 'utf8'))).sort(), ['Iso', 'Sec']);
  assert.deepEqual(JSON.parse(await fs.readFile(path.join(dir, '_missing.json'), 'utf8')), { Site: now / 1000 - 60 });
});

test('api: 429 throws RateLimited with Retry-After, no retry', async () => {
  replies.push(json({}, 429, { 'retry-after': '120' }));
  const e = await fetchPage('A').catch(e => e);
  assert.ok(e instanceof RateLimited); assert.equal(e.retryAfter, '120'); assert.equal(calls.length, 1);
});

test('api: one retry on 5xx and on network errors, then gives up', async () => {
  replies.push(json({}, 502), pageReply('A', 'ok'));
  assert.equal((await fetchPage('A')).text, 'ok');
  replies.push(new TypeError('fetch failed'), pageReply('B', 'ok'));
  assert.equal((await fetchPage('B')).text, 'ok');
  replies.push(json({}, 503), json({}, 503));
  await assert.rejects(fetchPage('C'), /liquipedia 503/);
  replies.push(Object.assign(new Error('t'), { name: 'TimeoutError' }), Object.assign(new Error('t'), { name: 'TimeoutError' }));
  await assert.rejects(fetchPage('D'), /network: timeout 20s/);
  assert.equal(calls.length, 8);
});

test('api: a timeout while reading the body is a network error and is retried', async () => {
  const slow = () => Object.assign(new Response('{}', { status: 200 }), { json: async () => { throw Object.assign(new Error('aborted'), { name: 'TimeoutError' }); } });
  replies.push(slow, pageReply('A', 'ok'));
  assert.equal((await fetchPage('A')).text, 'ok');
  replies.push(slow, slow);
  await assert.rejects(fetchPage('B'), /network: timeout 20s/);
  assert.equal(calls.length, 4);
});

test('api: maxlag is retried once; other API errors and replies without query are failures', async () => {
  replies.push(json({ error: { code: 'maxlag', info: 'lagged' } }, 503, { 'retry-after': '0' }), pageReply('A', 'ok'));
  assert.equal((await fetchPage('A')).text, 'ok');
  replies.push(json({ error: { code: 'maxlag', info: 'lagged' } }, 503, { 'retry-after': '0' }), json({ error: { code: 'maxlag', info: 'lagged' } }, 503, { 'retry-after': '0' }));
  await assert.rejects(fetchPage('B'), /maxlag/);
  replies.push(json({ error: { code: 'badvalue', info: 'nope' } }));
  await assert.rejects(fetchPage('C'), /api error: badvalue/);
  replies.push(json({ batchcomplete: '' }));
  await assert.rejects(fetchPage('D'), /no query/);
  replies.push(new Response('<html>busy</html>', { status: 200 }));
  await assert.rejects(fetchPage('E'), /not JSON/);
});

test('linksOf / pagesWithPrefix follow continue and cache; resolveTitles follows redirects and flags missing pages', async () => {
  replies.push(json({ continue: { plcontinue: 'x' }, query: { pages: { 1: { title: 'P', links: [{ title: 'A' }] } } } }), json({ query: { pages: { 1: { title: 'P', links: [{ title: 'B' }] } } } }));
  assert.deepEqual(await linksOf('P'), ['A', 'B']);
  assert.deepEqual(await linksOf('P'), ['A', 'B']);
  assert.equal(calls.length, 2); assert.equal(calls[1].url.searchParams.get('plcontinue'), 'x');
  replies.push(json({ continue: { apcontinue: 'n' }, query: { allpages: [{ title: 'P/1' }] } }), json({ query: { allpages: [{ title: 'P/2' }] } }));
  assert.deepEqual(await pagesWithPrefix('P/'), ['P/1', 'P/2']);
  assert.deepEqual(await pagesWithPrefix('P/'), ['P/1', 'P/2']);
  assert.equal(calls.length, 4); assert.equal(calls[2].url.searchParams.get('apprefix'), 'P/'); assert.equal(calls[3].url.searchParams.get('apcontinue'), 'n');
  assert.equal(calls[2].url.searchParams.get('apfilterredir'), 'nonredirects');
  replies.push(json({ query: { normalized: [{ from: 'a_b', to: 'A b' }], redirects: [{ from: 'A b', to: 'C' }], pages: { 1: { title: 'C' }, '-1': { title: 'D', missing: '' } } } }));
  assert.deepEqual(await resolveTitles(['a_b', 'D']), { a_b: { exists: true, title: 'C' }, D: { exists: false, title: 'D' } });
});

test('real 2025 World Finals excerpt: abbreviated month dates with CET', async () => {
  const stats = {};
  const [ms, warns] = quiet(() => parseMatches(WF, 'Overwatch Champions Series/2025/World Finals', stats));
  assert.deepEqual(ms.map(m => m.date), ['2025-11-26T16:05:00+01:00', '2025-11-26T15:00:00+01:00']);
  assert.equal(stats.dateless, 0); assert.equal(warns.length, 0);
  assert.deepEqual([ms[0].team1, ms[0].team2, ms[0].score1, ms[0].score2, ms[0].round], ['Spacestation Gaming', 'Team Peps', 2, 1, 'Upper Bracket Round 1']);
});

test('parseMatches: commented-out matches are skipped and section / round stay aligned (RC-14)', () => {
  const page = [
    '==Results==', '===Group A===', '<!-- Opening Matches -->',
    '{{Match|opponent1=A|opponent2=B}}',
    '<!--', '{{Match|opponent1=X|opponent2=Y}}', '-->',
    '<!-- {{Match|opponent1=X2|opponent2=Y2}} -->',
    '{{ match |opponent1=C|opponent2=D|map1={{Map|map=Busan|winner=1}} <!-- note -->}}',
    '===={{HiddenSort|Day 2}}====', '<!-- [[Bracket|Upper Final]] -->',
    '{{Match|opponent1=E|opponent2=F|date=Oct 25, 2026 <!-- tbc --> - 18:00 {{Abbr/KST}}}}',
    '{{Match|opponent1=G|opponent2=H',   // never closed: not a match, does not shift the ones before
  ].join('\n');
  const ms = quiet(() => parseMatches(page, 'X'))[0];
  assert.deepEqual(ms.map(m => [m.team1, m.team2, m.section, m.round]), [
    ['A', 'B', 'Group A', 'Opening Matches'],
    ['C', 'D', 'Group A', 'Opening Matches'],   // the comment inside C-D is no round label
    ['E', 'F', 'Day 2', 'Upper Final'],
  ]);
  assert.deepEqual(ms.map(m => m.idx), [0, 1, 2]);
  assert.equal(ms[2].date, '2026-10-25T18:00:00+09:00');
  // a heading inside a comment does not count
  const hid = quiet(() => parseMatches('==Results==\n===Group A===\n<!--\n===Group B===\n-->\n{{Match|opponent1=A|opponent2=B}}', 'X'))[0];
  assert.equal(hid[0].section, 'Group A');
  // an unclosed comment hides everything after it, as on the wiki
  assert.equal(quiet(() => parseMatches('{{Match|opponent1=A|opponent2=B}}\n<!-- {{Match|opponent1=C|opponent2=D}}', 'X'))[0].length, 1);
});

test('cleanLabel unwraps display-only markup', () => {
  assert.equal(cleanLabel('{{HiddenSort|Day 1}}'), 'Day 1');
  assert.equal(cleanLabel('{{hiddensort|Group A}}'), 'Group A');
  assert.equal(cleanLabel('{{Stage|Playoffs}}'), 'Playoffs');
  assert.equal(cleanLabel('{{nowrap|{{HiddenSort|Week 2}}}}'), 'Week 2');
  assert.equal(cleanLabel("'''Grand''' [[Final (x)|Final]] <!-- x -->"), 'Grand Final');
  assert.equal(cleanLabel('Upper Bracket Quarterfinals'), 'Upper Bracket Quarterfinals');
  assert.equal(cleanLabel(undefined), '');
});
