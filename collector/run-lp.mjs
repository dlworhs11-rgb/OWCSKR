// Liquipedia pages in data/competitions.json -> data/lp/<slug>.json (2.2 s between requests, data/lp-cache 6 h).
//   node collector/run-lp.mjs                every page (core + the World Cup pages already in data/lp or active)
//   node collector/run-lp.mjs --active-only  only the pages matching data/active.json (and pages with no data/lp file yet)
//   node collector/run-lp.mjs --discover     find new stage / event pages, update data/competitions.json (core) and
//                                            data/active.json, print them, fetch no matches. Run it before --active-only.
// --discover reads the newest Korea stage page (tabs, |next=) and the list of pages named
// 'Overwatch Champions Series/<year>/...' for this year and next; keeps titles of the shapes in SHAPES that exist.
// Prints 'ADDED <title>' per new page, 'ACTIVE+ <title>' / 'ACTIVE- <title>' per change of active.json, then
// 'DISCOVER <today> added <n> active <n>'. Never removes pages from competitions.json. active.json = pages with a match
// dated within today (KST) +-30 days, plus pages of this year or later with no dated match yet or undated matches still
// to play (just announced). Same input -> same output (files are rewritten only when they change).
// Exit code: 0 ok, 2 some page failed (ERR / SHRINK / 429 / missing page that had matches) or a --discover request
// failed, 3 Node without fetch, 1 crash. A failed page keeps its old data/lp file. 429 stops the run (Retry-After logged).
// data/lp/_status.json: { updatedAt, failures, rateLimit, pages: { [title]: { ok, matches, played, dateless, redirect,
// shrinkFrom, error, lastOk } } }, merged with the previous file (pages not fetched this run keep their entry).
// SHRINK: a new parse with fewer than half the matches of the old file is not written (template change, page emptied).
// Delete the data/lp file by hand if the page really shrank.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchPage, pagesWithPrefix, resolveTitles, parseMatches, RateLimited } from './liquipedia.mjs';
import { readJson, writeJson, kstDay } from './util.mjs';

const OCS = 'Overwatch Champions Series/';
const MAX_AGE = 6 * 3600e3;
export const fileOf = title => { const slug = title.replace(/^Overwatch (Champions Series|World Cup)\//, '').replace(/[^a-z0-9]+/gi, '-').toLowerCase(); return `data/lp/${title.includes('World Cup') ? 'owwc-' : 'owcs-'}${slug}.json`; };
const exists = f => fs.access(f).then(() => true, () => false);
// substring match, same as owcs-kr cloud_live.active_titles (old entries are short: '2026/Asia/Stage 3')
export const isActive = (title, active) => active.some(a => title.includes(a));

// core + World Cup pages that are active or already collected. The World Cup list also has qualifiers we never fetch:
// a World Cup page counts as active only by its exact title ('Overwatch World Cup/2026' would substring-match them all)
export async function titlesOf(comps, active, has = t => exists(fileOf(t))) {
  const wc = [];
  for (const t of comps.world_cup || []) if (active.includes(t) || await has(t)) wc.push(t);
  return [...comps.core, ...wc];
}

const EMPTY = { ok: false, matches: null, played: null, dateless: null, redirect: null, shrinkFrom: null, error: null };

// One page -> status entry (without lastOk). deps: page(title) -> fetchPage result, prev(file) -> old json, write(file, json)
export async function collectPage(title, { page, prev, write }) {
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
    console.log('SHRINK', title, before, '->', matches.length, '(old file kept)');
    return { ...st, shrinkFrom: before, error: `shrink ${before} -> ${matches.length}` };
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

async function runFetch(activeOnly) {
  const comps = await readComps();
  const active = (await readJson('data/active.json')) || [];
  const titles = await titlesOf(comps, active);
  // --active-only: everything else is kept from data/lp/*.json
  const skip = async t => activeOnly && !isActive(t, active) && await exists(fileOf(t));
  const { results, failures, rateLimit } = await collectAll(titles, skip);
  const now = new Date().toISOString();
  await writeJson('data/lp/_status.json', mergeStatus(await readJson('data/lp/_status.json'), results, { now, titles, failures, rateLimit }));
  if (!activeOnly) await writeJson('data/lp/_summary.json', Object.entries(results).map(([title, r]) => r.missing ? { title, missing: true } : r.ok ? { title, matches: r.matches, played: r.played } : { title, error: r.error }));
  console.log('DONE', Object.keys(results).length, 'pages', failures, 'failed');
  process.exitCode = failures ? 2 : 0;
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
// undated matches still to play: announced, schedule not out. pages: title -> matches of its data/lp file or null.
export function computeActive({ titles, pages, today, days = 30 }) {
  const shift = n => new Date(Date.parse(today) + n * 864e5).toISOString().slice(0, 10);
  const lo = shift(-days), hi = shift(days), year = +today.slice(0, 4);
  return titles.filter(t => {
    const ms = pages[t] || [];
    if (ms.some(m => m.date && kstDay(m.date) >= lo && kstDay(m.date) <= hi)) return true;
    if (yearOf(t) < year) return false;
    return !ms.some(m => m.date) || ms.some(m => !m.date && !m.played);
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

const diff = (a, b) => a.filter(x => !b.includes(x));

async function discover() {
  const today = kstDay(Date.now()), year = +today.slice(0, 4), years = [year, year + 1];
  const comps = await readComps();
  const cands = await discoverCandidates(comps.core, years);
  const resolved = cands.length ? await resolveTitles(cands) : {};
  const added = [...new Set(Object.values(resolved).filter(r => r.exists).map(r => normTitle(r.title)))]
    .filter(t => acceptTitle(t, years) && !comps.core.includes(t)).sort();
  for (const t of added) console.log('ADDED', t);
  const next = { ...comps, core: [...comps.core, ...added] };
  if (added.length) await writeJson('data/competitions.json', next);
  const prevActive = (await readJson('data/active.json')) || [];
  const titles = await titlesOf(next, prevActive);
  const pages = {};
  for (const t of titles) pages[t] = (await readJson(fileOf(t)))?.matches ?? null;
  const active = computeActive({ titles, pages, today });
  for (const t of diff(active, prevActive)) console.log('ACTIVE+', t);
  for (const t of diff(prevActive, active)) console.log('ACTIVE-', t);
  if (JSON.stringify(active) !== JSON.stringify(prevActive)) await writeJson('data/active.json', active);
  console.log('DISCOVER', today, 'added', added.length, 'active', active.length);
}

async function main() {
  if (typeof fetch !== 'function') { console.error(`run-lp: this Node (${process.version}) has no global fetch; Node 20+ is required`); process.exit(3); }
  const argv = process.argv.slice(2);
  try { await (argv.includes('--discover') ? discover() : runFetch(argv.includes('--active-only'))); }
  catch (e) {
    // a --discover request failed (network, 429, API error): nothing was written
    if (!(e instanceof RateLimited) && !/^(network|liquipedia|redirect)/.test(e.message)) throw e;
    console.log('ERR', e.message); process.exitCode = 2;
  }
}

if (process.argv[1] && path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1])) await main();
