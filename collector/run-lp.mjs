// Liquipedia pages in data/competitions.json -> data/lp/<slug>.json (2.2 s between requests, data/lp-cache 6 h).
//   node collector/run-lp.mjs                every page (core + the World Cup pages already in data/lp or active, and
//                                            the main 'Overwatch World Cup/<year>' pages of this year or later)
//   node collector/run-lp.mjs --active-only  only the pages matching data/active.json (and pages with no data/lp file yet);
//                                            a full title there matches only itself, a short one ('2026/Asia/Stage 3')
//                                            every title containing it (util.isActiveTitle, same as owcs-kr cloud_live)
//   node collector/run-lp.mjs --discover     find new stage / event pages, update data/competitions.json (core,
//                                            world_cup) and data/active.json, print them, fetch no matches. Run it
//                                            before --active-only.
// --discover reads the newest Korea stage page (tabs, |next=) and the list of pages named
// 'Overwatch Champions Series/<year>/...' for this year and next; keeps titles of the shapes in SHAPES that exist.
// It also asks whether 'Overwatch World Cup/<year>' exists for this year and next (in the same title lookup, no extra
// request) and adds it to world_cup, so a new World Cup year starts without hand edits; its qualifier pages are never
// added (only the main page has the Korea team's matches). A main World Cup page of this year or later is collected
// like a core page, so the first run after it is added fetches it.
// Prints 'ADDED <title>' per new page, 'ACTIVE+ <title>' / 'ACTIVE- <title>' per change of active.json, then
// 'DISCOVER <today> added <n> active <n>'. Never removes pages from competitions.json. active.json = pages with a match
// dated within today (KST) +-30 days, plus pages of this year or later with no dated match yet, or with undated matches
// still to play while their last dated match is at most 30 days old (unused TBD slots of a finished bracket drop out). Pages without a data/lp file (missing on Liquipedia, just added) are left out: --active-only
// fetches them anyway. Same input -> same output (files are rewritten only when they change).
// Exit code: 0 ok, 3 Node without fetch, 1 crash or a bad --accept-shrink. A page that failed (ERR / SHRINK / 429 /
// missing page that had matches) is logged ('ERR', 'SHRINK', 'STOP') and recorded in _status.json; a --discover request
// that failed is logged 'ERR' and writes nothing. Both still exit 0 unless --strict is given, then 2 (owcs-kr
// cloud_live runs without --strict and reads the failures from _status.json; tools/run_daily.sh passes --strict). A failed page keeps its old data/lp file. 429 stops the run (Retry-After logged).
// data/lp/_status.json: { updatedAt, failures, rateLimit, pages: { [title]: { ok, matches, played, dateless, redirect,
// shrinkFrom, error, lastOk } } }, merged with the previous file (pages not fetched this run keep their entry).
// SHRINK: a new parse with fewer than half the matches of the old file is not written (template change, page emptied).
// If the page really shrank (rebuilt, 1 -> 0), rerun with --accept-shrink '<title>' (repeatable, also --accept-shrink=<title>):
// that page is fetched (even with --active-only), written, logged 'SHRINK accepted' and counts as ok (shrinkFrom kept).
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchPage, pagesWithPrefix, resolveTitles, parseMatches, RateLimited } from './liquipedia.mjs';
import { readJson, writeJson, kstDay, isActiveTitle } from './util.mjs';

const OCS = 'Overwatch Champions Series/', WC = 'Overwatch World Cup/';
export const isWorldCupMain = t => /^Overwatch World Cup\/\d{4}$/.test(t);
const thisYear = () => +kstDay(Date.now()).slice(0, 4);
const MAX_AGE = 6 * 3600e3;
export const fileOf = title => { const slug = title.replace(/^Overwatch (Champions Series|World Cup)\//, '').replace(/[^a-z0-9]+/gi, '-').toLowerCase(); return `data/lp/${title.includes('World Cup') ? 'owwc-' : 'owcs-'}${slug}.json`; };
const exists = f => fs.access(f).then(() => true, () => false);
// full titles match exactly, old short entries ('2026/Asia/Stage 3') by substring: same as owcs-kr cloud_live.active_titles
export const isActive = isActiveTitle;

// core + World Cup pages that are active, already collected, or the main page of this year or later (just discovered).
// The World Cup list also has qualifiers we never fetch: a World Cup page counts as active only by its exact title
// ('Overwatch World Cup/2026' would substring-match them all, so a short entry does not pull World Cup pages in)
export async function titlesOf(comps, active, has = t => exists(fileOf(t)), { year = thisYear() } = {}) {
  const wc = [];
  for (const t of comps.world_cup || []) {
    if (active.includes(t) || (isWorldCupMain(t) && +t.slice(WC.length) >= year) || await has(t)) wc.push(t);
  }
  return [...comps.core, ...wc];
}

const EMPTY = { ok: false, matches: null, played: null, dateless: null, redirect: null, shrinkFrom: null, error: null };

// One page -> status entry (without lastOk). deps: page(title) -> fetchPage result, prev(file) -> old json, write(file, json),
// acceptShrink: titles whose shrink is written anyway
export async function collectPage(title, { page, prev, write, acceptShrink = new Set() }) {
  const file = fileOf(title);
  const before = (await prev(file))?.matches?.length ?? 0;
  let p;
  try { p = await page(title); }
  catch (e) { if (e instanceof RateLimited) throw e; console.log('ERR', title, e.message); return { ...EMPTY, error: e.message }; }
  const st = { ...EMPTY, redirect: p.redirect ?? null };
  if (p.redirect) console.log('MOVED', title, '->', p.redirect, '(fix data/competitions.json)');
  if (p.missing) {
    console.log('MISSING', title);
    if (before) return { ...st, error: `missing (kept ${before} matches)` };
    return { ...st, ok: true, matches: 0, played: 0, dateless: 0, missing: true };
  }
  const stats = {};
  let matches;
  // a page the parser chokes on, or a file that cannot be replaced (Windows: open elsewhere), fails this page, not the run
  try { matches = parseMatches(p.text, title, stats); }
  catch (e) { console.log('ERR', title, 'parse:', e.message); return { ...st, error: 'parse: ' + e.message }; }
  const played = matches.filter(m => m.played).length;
  Object.assign(st, { matches: matches.length, played, dateless: stats.dateless });
  if (before && matches.length < before * 0.5) {
    st.shrinkFrom = before;
    if (!acceptShrink.has(title)) {
      console.log('SHRINK', title, before, '->', matches.length, '(old file kept; --accept-shrink to write it)');
      return { ...st, error: `shrink ${before} -> ${matches.length}` };
    }
    console.log('SHRINK accepted', title, before, '->', matches.length);
  }
  try { await write(file, { title, matches }); }
  catch (e) { console.log('ERR', title, 'write:', e.message); return { ...st, error: 'write: ' + e.message }; }
  console.log(String(matches.length).padStart(4), 'matches', String(played).padStart(4), 'played', title, stats.dateless ? `(${stats.dateless} dateless)` : '');
  return { ...st, ok: true };
}

// previous _status.json + this run's entries; titles no longer collected are dropped
export function mergeStatus(prev, results, { now, titles, failures, rateLimit = null }) {
  const pages = {};
  for (const t of titles) {
    const old = prev?.pages?.[t], r = results[t];
    if (r) pages[t] = { ...r, lastOk: r.ok ? now : old?.lastOk ?? null };
    else if (old) pages[t] = old;
  }
  return { updatedAt: now, failures, rateLimit, pages };
}

const liveDeps = { page: t => fetchPage(t, { maxAgeMs: MAX_AGE }), prev: readJson, write: (f, d) => writeJson(f, d) };

export async function collectAll(titles, skip = async () => false, deps = liveDeps) {
  const results = {}; let failures = 0, rateLimit = null;
  for (const [i, title] of titles.entries()) {
    if (await skip(title)) continue;
    try { results[title] = await collectPage(title, deps); }
    catch (e) {
      if (!(e instanceof RateLimited)) throw e;
      results[title] = { ...EMPTY, error: e.message };
      rateLimit = { retryAfter: e.retryAfter ?? null, at: new Date().toISOString(), skipped: titles.length - i - 1 };
      console.log('STOP', e.message, '-', rateLimit.skipped, 'pages left as they were');
    }
    if (!results[title].ok) failures++;
    if (rateLimit) break;
  }
  return { results, failures, rateLimit };
}

async function readComps() {
  const comps = await readJson('data/competitions.json');
  if (!Array.isArray(comps?.core)) throw new Error('data/competitions.json missing or without "core"');
  return comps;
}

async function runFetch(activeOnly, strict, acceptShrink = new Set()) {
  const comps = await readComps();
  const active = (await readJson('data/active.json')) || [];
  const titles = await titlesOf(comps, active);
  for (const t of acceptShrink) if (!titles.includes(t)) console.log('WARN --accept-shrink', JSON.stringify(t), 'is not a collected page title');
  // --active-only: everything else is kept from data/lp/*.json
  const skip = async t => activeOnly && !acceptShrink.has(t) && !isActive(t, active) && await exists(fileOf(t));
  const { results, failures, rateLimit } = await collectAll(titles, skip, { ...liveDeps, acceptShrink });
  const now = new Date().toISOString();
  await writeJson('data/lp/_status.json', mergeStatus(await readJson('data/lp/_status.json'), results, { now, titles, failures, rateLimit }));
  if (!activeOnly) await writeJson('data/lp/_summary.json', Object.entries(results).map(([title, r]) => r.missing ? { title, missing: true } : r.ok ? { title, matches: r.matches, played: r.played } : { title, error: r.error }));
  console.log('DONE', Object.keys(results).length, 'pages', failures, 'failed', failures && !strict ? '(exit 0: pass --strict to exit 2)' : '');
  process.exitCode = failures && strict ? 2 : 0;
}

// ---- --discover ----
// shapes of the pages already in competitions.json (core), below 'Overwatch Champions Series/<year>/'
export const SHAPES = [
  /^Asia\/Stage \d+$/,
  /^Asia\/Stage \d+\/Korea(\/(Regular Season|Open Qualifier|Relegation|Group Stage))?$/,
  /^Asia\/Stage \d+\/(Main Event|Wild Card)$/,
  /^Asia\/Stage \d+\/Championship\/[^/]+$/,
  /^(Champions Clash|World Finals)(\/Group Stage)?$/,
  /^Midseason Championship(\/Group Stage|\/LCQ(\/Group Stage)?)?$/,
];
export function acceptTitle(title, years) {
  const m = /^Overwatch Champions Series\/(\d{4})\/(.+)$/.exec(title);
  return !!m && years.includes(+m[1]) && SHAPES.some(re => re.test(m[2]));
}
export const normTitle = t => t.replace(/_/g, ' ').replace(/#.*$/, '').replace(/\s+/g, ' ').trim();
const yearOf = t => +(/^Overwatch (?:Champions Series|World Cup)\/(\d{4})(?:\/|$)/.exec(t) || [])[1] || 0;
export const koreaRootOf = t => { const m = /^(Overwatch Champions Series\/\d{4}\/Asia\/Stage \d+)(\/|$)/.exec(t); return m ? m[1] + '/Korea' : null; };
export function newestKorea(core) {
  const key = t => { const m = /^Overwatch Champions Series\/(\d{4})\/Asia\/Stage (\d+)\/Korea$/.exec(t); return m ? +m[1] * 100 + +m[2] : 0; };
  return core.filter(key).sort((a, b) => key(a) - key(b)).at(-1) ?? null;
}
// infobox '|next=Overwatch Champions Series/2027/Asia/Stage 1/Korea' (maybe '[[...|label]]' or '...{{!}}label')
export function nextOf(text) {
  const m = /^\|\s*next\s*=\s*([^\n]*)/m.exec(text || '');
  const v = m && normTitle(m[1].replace(/^\[\[/, '').split(/\{\{!\}\}|\||\]\]/)[0]);
  return v && v.startsWith(OCS) ? v : null;
}

// '{{Tabs static|link2=.../Korea/Regular Season|...}}' at the top of a stage page
export const tabLinksOf = text => [...(text || '').matchAll(/\|\s*link\d+\s*=\s*([^|\n}]+)/g)].map(m => normTitle(m[1]));

// pages to keep re-reading: a match dated within today +-days (KST), or (page of this year or later) nothing dated yet /
// undated matches still to play while its last dated match is at most 'days' old: announced, schedule not out. pages: title -> matches of its data/lp file or null.
// null (no file: missing on Liquipedia, or not fetched yet) is not listed: --active-only fetches such a page anyway, and
// a missing overview page ('2026/Asia/Stage 3') listed for the whole year substring-matches every page of its stage
export function computeActive({ titles, pages, today, days = 30 }) {
  const shift = n => new Date(Date.parse(today) + n * 864e5).toISOString().slice(0, 10);
  const lo = shift(-days), hi = shift(days), year = +today.slice(0, 4);
  return titles.filter(t => {
    const ms = pages[t];
    if (!ms || !t.startsWith('Overwatch ')) return false;   // only full titles: they match exactly (isActiveTitle)
    if (ms.some(m => m.date && kstDay(m.date) >= lo && kstDay(m.date) <= hi)) return true;
    if (yearOf(t) < year) return false;
    const last = ms.filter(m => m.date).map(m => kstDay(m.date)).sort().at(-1);
    if (!last) return true;   // announced, nothing scheduled yet: Liquipedia dates the matches once the schedule is out
    // undated matches still to play keep the page only while its schedule runs (last dated match not over 'days' ago):
    // after that they are bracket slots nobody will play (RC-17), not matches to wait for until the end of the year
    return last >= lo && ms.some(m => !m.date && !m.played);
  });
}

// Liquipedia has no 'Overwatch Champions Series/<year>' overview page, so the season's pages come from the page list
// (allpages, prefix '<year>/'), plus the newest Korea page's tabs and its |next= (may point to a page not created yet)
export async function discoverCandidates(core, years, { page = t => fetchPage(t, { maxAgeMs: MAX_AGE }), list = pagesWithPrefix } = {}) {
  const out = new Set();
  const newest = newestKorea(core);
  if (newest) {
    const { text } = await page(newest);
    for (const t of tabLinksOf(text)) out.add(t);
    const nxt = nextOf(text);
    if (nxt) { out.add(nxt); if (koreaRootOf(nxt)) out.add(koreaRootOf(nxt)); }
  }
  for (const y of years) for (const t of await list(`${OCS}${y}/`)) out.add(normTitle(t));
  return [...out].filter(t => acceptTitle(t, years) && !core.includes(t)).sort();
}

// 'Overwatch World Cup/<year>' for the years given, unless listed already (looked up with the stage candidates)
export const worldCupCandidates = (worldCup, years) => years.map(y => WC + y).filter(t => !worldCup.includes(t));

// resolveTitles result -> competitions.json with the pages that exist added (core: SHAPES, world_cup: main pages)
export function addDiscovered(comps, resolved, years) {
  const found = [...new Set(Object.values(resolved).filter(r => r.exists).map(r => normTitle(r.title)))];
  const wcList = comps.world_cup || [];
  const core = found.filter(t => acceptTitle(t, years) && !comps.core.includes(t)).sort();
  const wc = found.filter(t => isWorldCupMain(t) && years.includes(+t.slice(WC.length)) && !wcList.includes(t)).sort();
  const next = { ...comps, core: [...comps.core, ...core] };
  if (wc.length) next.world_cup = [...wcList, ...wc];
  return { next, added: [...core, ...wc] };
}

const diff = (a, b) => a.filter(x => !b.includes(x));

async function discover() {
  const today = kstDay(Date.now()), year = +today.slice(0, 4), years = [year, year + 1];
  const comps = await readComps();
  const cands = [...await discoverCandidates(comps.core, years), ...worldCupCandidates(comps.world_cup || [], years)];
  const resolved = cands.length ? await resolveTitles(cands) : {};
  const { next, added } = addDiscovered(comps, resolved, years);
  for (const t of added) console.log('ADDED', t);
  if (added.length) await writeJson('data/competitions.json', next);
  const prevActive = (await readJson('data/active.json')) || [];
  const titles = await titlesOf(next, prevActive, undefined, { year });
  const pages = {};
  for (const t of titles) pages[t] = (await readJson(fileOf(t)))?.matches ?? null;
  const active = computeActive({ titles, pages, today });
  for (const t of diff(active, prevActive)) console.log('ACTIVE+', t);
  for (const t of diff(prevActive, active)) console.log('ACTIVE-', t);
  if (JSON.stringify(active) !== JSON.stringify(prevActive)) await writeJson('data/active.json', active);
  console.log('DISCOVER', today, 'added', added.length, 'active', active.length);
}

// every value of a repeatable '--name value' / '--name=value' option (titles normalized like competitions.json)
export function optionValues(argv, name) {
  const out = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith(name + '=')) out.push(argv[i].slice(name.length + 1));
    else if (argv[i] === name) {
      if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) throw new Error(`${name} needs a page title`);
      out.push(argv[++i]);
    }
  }
  return out.map(normTitle).filter(Boolean);
}

async function main() {
  if (typeof fetch !== 'function') { console.error(`run-lp: this Node (${process.version}) has no global fetch; Node 20+ is required`); process.exit(3); }
  const argv = process.argv.slice(2), strict = argv.includes('--strict');
  let acceptShrink;
  try { acceptShrink = new Set(optionValues(argv, '--accept-shrink')); }
  catch (e) { console.error('run-lp:', e.message); process.exit(1); }
  try { await (argv.includes('--discover') ? discover() : runFetch(argv.includes('--active-only'), strict, acceptShrink)); }
  catch (e) {
    // a --discover request failed (network, 429, API error): nothing was written
    if (!(e instanceof RateLimited) && !/^(network|liquipedia|redirect)/.test(e.message)) throw e;
    console.log('ERR', 'discover failed, nothing written:', e.message, strict ? '' : '(exit 0: pass --strict to exit 2)');
    process.exitCode = strict ? 2 : 0;
  }
}

if (process.argv[1] && path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1])) await main();
