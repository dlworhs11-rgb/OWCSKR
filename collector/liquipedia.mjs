import fs from 'node:fs/promises';
import path from 'node:path';
import { findTemplates, parseTemplate } from './wikitext.mjs';
import { readJson, writeJson } from './util.mjs';

const API = 'https://liquipedia.net/overwatch/api.php';
const UA = 'OWCSKR-fansite/0.1 (+https://github.com/dlworhs11-rgb/OWCSKR)';
// delay: terms say <= 1 request / 2s (action=parse: 1 / 30s -> never used). Tests swap fetch / cache / delay.
export const cfg = { delay: 2200, timeout: 20000, cache: path.resolve('data/lp-cache'), missingTtl: 6 * 3600e3, fetch: (u, o) => globalThis.fetch(u, o) };
let last = 0;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// HTTP 429: the caller stops the whole run (more requests only lengthen the block); Retry-After is kept for the log
export class RateLimited extends Error {
  constructor(retryAfter) { super(`liquipedia 429 (retry-after ${retryAfter ?? '?'})`); this.retryAfter = retryAfter; }
}

async function once(url) {
  const wait = last + cfg.delay - Date.now();
  if (wait > 0) await sleep(wait);
  last = Date.now();
  const res = await cfg.fetch(url, { headers: { 'user-agent': UA, 'accept-encoding': 'gzip' }, signal: AbortSignal.timeout(cfg.timeout) });
  const body = await res.json().catch(() => null);
  return { res, body };
}

// one retry for network errors / timeouts, 5xx and maxlag (replica lag: the API answers an error JSON, usually with 503)
async function api(params) {
  const url = API + '?' + new URLSearchParams({ format: 'json', maxlag: '5', ...params });
  for (let attempt = 0; ; attempt++) {
    const retry = attempt === 0;
    let r;
    try { r = await once(url); }
    catch (e) { if (retry) continue; throw new Error(`network: ${e.name === 'TimeoutError' ? `timeout ${cfg.timeout / 1000}s` : e.message}`); }
    const { res, body } = r;
    if (res.status === 429) throw new RateLimited(res.headers.get('retry-after'));
    if (body?.error?.code === 'maxlag') {
      if (retry) { const h = res.headers.get('retry-after'); await sleep(Math.min(10, h == null ? 5 : Number(h) || 0) * 1000); continue; }
      throw new Error('liquipedia maxlag: ' + body.error.info);
    }
    if (res.status >= 500 && retry) continue;
    if (!res.ok) throw new Error(`liquipedia ${res.status}`);
    if (!body) throw new Error('liquipedia: response is not JSON');
    if (body.error || !body.query) throw new Error(`liquipedia api error: ${body.error ? `${body.error.code} ${body.error.info}` : 'no query in response'}`);
    return body;
  }
}

const cacheFile = (title, ext) => path.join(cfg.cache, title.replace(/[^a-z0-9]+/gi, '_') + ext);
const fresh = async (file, maxAgeMs) => { try { return Date.now() - (await fs.stat(file)).mtimeMs < maxAgeMs; } catch { return false; } };
// title -> ISO time it was found missing / title -> redirect target (a cached copy keeps where it came from)
const sideFile = name => path.join(cfg.cache, name);
async function sideSet(name, key, value) {
  const m = (await readJson(sideFile(name))) || {};
  if (value === undefined) { if (!(key in m)) return; delete m[key]; } else m[key] = value;
  await writeJson(sideFile(name), m);
}
export const isRedirectBody = text => /^\s*#REDIRECT/i.test(text);
const pageOf = r => Object.values(r.query.pages || {})[0] || {};

// -> { text, redirect, missing, cached }. Follows redirects; a '#REDIRECT' body (not followed: section / broken target)
// is an error, so the caller does not replace the old matches with an empty list. Missing pages are not asked again for 6 h.
export async function fetchPage(title, { maxAgeMs = 3600e3 } = {}) {
  const file = cacheFile(title, '.wiki');
  const missingAt = ((await readJson(sideFile('_missing.json'))) || {})[title];
  if (missingAt && Date.now() - Date.parse(missingAt) < cfg.missingTtl) return { text: null, redirect: null, missing: true, cached: true };
  if (await fresh(file, maxAgeMs)) {
    const text = await fs.readFile(file, 'utf8');
    if (isRedirectBody(text)) throw new Error('redirect not followed: ' + text.trim().slice(0, 120));
    return { text, redirect: ((await readJson(sideFile('_redirects.json'))) || {})[title] ?? null, missing: false, cached: true };
  }
  const r = await api({ action: 'query', prop: 'revisions', rvprop: 'content', rvslots: 'main', redirects: '1', titles: title });
  const page = pageOf(r), redirect = r.query.redirects?.length ? page.title ?? null : null;
  const text = page.revisions?.[0]?.slots?.main?.['*'];
  if (text == null) { await sideSet('_missing.json', title, new Date().toISOString()); return { text: null, redirect, missing: true, cached: false }; }
  await sideSet('_missing.json', title, undefined);
  if (isRedirectBody(text)) throw new Error('redirect not followed: ' + text.trim().slice(0, 120));
  await fs.mkdir(cfg.cache, { recursive: true });
  await fs.writeFile(file, text);
  await sideSet('_redirects.json', title, redirect ?? undefined);
  return { text, redirect, missing: false, cached: false };
}

export async function wikitext(title, opts) { return (await fetchPage(title, opts)).text; }

// main-namespace links of a page (redirect followed), cached like the wikitext
export async function linksOf(title, { maxAgeMs = 6 * 3600e3 } = {}) {
  const file = cacheFile(title, '.links.json');
  if (await fresh(file, maxAgeMs)) return readJson(file);
  const out = []; let cont = {};
  for (let i = 0; i < 10 && cont; i++) {
    const r = await api({ action: 'query', prop: 'links', plnamespace: '0', pllimit: 'max', redirects: '1', titles: title, ...cont });
    out.push(...(pageOf(r).links || []).map(l => l.title));
    cont = r.continue?.plcontinue ? { plcontinue: r.continue.plcontinue } : null;
  }
  await writeJson(file, out);
  return out;
}

// existing main-namespace pages whose title starts with prefix (redirects left out), cached like the wikitext
export async function pagesWithPrefix(prefix, { maxAgeMs = 6 * 3600e3 } = {}) {
  const file = cacheFile(prefix, '.pages.json');
  if (await fresh(file, maxAgeMs)) return readJson(file);
  const out = []; let cont = {};
  for (let i = 0; i < 10 && cont; i++) {
    const r = await api({ action: 'query', list: 'allpages', apnamespace: '0', apfilterredir: 'nonredirects', aplimit: 'max', apprefix: prefix, ...cont });
    out.push(...(r.query.allpages || []).map(p => p.title));
    cont = r.continue?.apcontinue ? { apcontinue: r.continue.apcontinue } : null;
  }
  await writeJson(file, out);
  return out;
}

// title -> { exists, title (after redirects) }, 50 titles per request (the API limit)
export async function resolveTitles(titles) {
  const out = {};
  for (let i = 0; i < titles.length; i += 50) {
    const chunk = titles.slice(i, i + 50);
    const r = await api({ action: 'query', redirects: '1', titles: chunk.join('|') });
    const pages = Object.values(r.query.pages || {});
    for (const t of chunk) {
      let target = r.query.normalized?.find(n => n.from === t)?.to ?? t;
      for (let hop = 0, x; hop < 5 && (x = (r.query.redirects || []).find(y => y.from === target)); hop++) target = x.to;
      const p = pages.find(x => x.title === target);
      out[t] = { exists: !!p && p.missing === undefined && p.invalid === undefined, title: target };
    }
  }
  return out;
}
const stripLinks = s => s.replace(/\[\[(?:[^|\]]*\|)?([^\]]*)\]\]/g, '$1').trim();
const num = v => (v === undefined || v === '' ? null : Number(v));

const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
// 'Nov', 'Sept.', 'November': any 3+ letter start of a month name (2025 World Finals writes 'Nov 26, 2025 - 16:05')
const monthOf = w => { const k = w.toLowerCase(); return k.length < 3 ? 0 : MONTHS.findIndex(n => n.startsWith(k)) + 1; };
// Liquipedia writes "{{Abbr/KST}}" style zone markers; map the ones that show up in OWCS pages.
const TZ = { KST: '+09:00', JST: '+09:00', CST: '+08:00', CET: '+01:00', CEST: '+02:00', BST: '+01:00', PDT: '-07:00', PST: '-08:00', EDT: '-04:00', EST: '-05:00', CDT: '-05:00', UTC: '+00:00', GMT: '+00:00' };

export function parseDate(s) {
  if (!s) return null;
  const zone = (/Abbr\/(\w+)/.exec(s) || [])[1];
  const tz = TZ[zone] || '+00:00';
  let y, mo, d, m;
  if ((m = /(\d{4})-(\d{2})-(\d{2})/.exec(s))) { y = +m[1]; mo = +m[2]; d = +m[3]; }
  else if ((m = [...s.matchAll(/([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})/g)].find(x => monthOf(x[1])))) { mo = monthOf(m[1]); d = +m[2]; y = +m[3]; }
  else return null;
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const t = /(\d{1,2}):(\d{2})/.exec(s.replace(/\d{4}-\d{2}-\d{2}/, ''));
  const p = n => String(n).padStart(2, '0');
  return `${y}-${p(mo)}-${p(d)}T${t ? p(t[1]) + ':' + t[2] : '00:00'}:00${tz}`;
}

// Where each {{Match}} sits on the page, in page order: the deepest heading under ==Results== ('Group A', 'Playoffs')
// and the <!-- comment --> above it ('Upper Bracket Quarterfinals'). Kept with the match so the site build needs no wiki
// copy (the cloud only has the active pages' wiki cached). Same rule as owcs_build.py intl_layout().
function matchPlaces(text) {
  const out = []; let sec = '', rnd = '', on = false, t;
  const re = /^(==+)\s*(.*?)\s*\1\s*$|<!--\s*(.*?)\s*-->|\{\{\s*Match\s*(?=[|}\n])/gm;
  while ((t = re.exec(text))) {
    if (t[1]) {
      const h = t[2].replace(/\{\{Stage\|([^}]*)\}\}/g, '$1');
      if (t[1].length === 2) on = h.toLowerCase() === 'results';
      if (on && t[1].length > 2) { sec = h; rnd = ''; }
    } else if (t[3] !== undefined) rnd = t[3];
    else out.push({ section: on ? sec : '', round: rnd });
  }
  return out;
}

// Parse every {{Match}} in a Liquipedia tournament page. stats.dateless counts matches whose date is written but not
// understood (they drop out of site/matches.json, so each one is logged as DATE?)
export function parseMatches(text, competition, stats = {}) {
  text = text.replace(/\r\n?/g, '\n');   // a CRLF copy (git autocrlf on Windows) otherwise parses to 0 matches
  const places = matchPlaces(text);
  stats.dateless = 0;
  return findTemplates(text, 'Match').map((raw, idx) => {
    const { args } = parseTemplate(raw);
    const date = parseDate(args.date);
    if (!date && args.date) { stats.dateless++; console.warn('DATE?', competition, idx, JSON.stringify(args.date)); }
    const team = k => { const t = args[k] && findTemplates(args[k], 'TeamOpponent')[0]; return t ? parseTemplate(t).pos[0] : stripLinks(args[k] || ''); };
    const maps = Object.keys(args).filter(k => /^map\d+$/.test(k)).sort((a, b) => a.slice(3) - b.slice(3)).map((k, i) => {
      const t = findTemplates(args[k], 'Map')[0]; if (!t) return null;
      const a = parseTemplate(t).args;
      return { n: i + 1, map: a.map || null, mode: a.mode || null, score1: num(a.score1), score2: num(a.score2), winner: num(a.winner), bans: { t1: a.t1b1 || null, t2: a.t2b1 || null }, banstart: num(a.banstart) };
    }).filter(Boolean);
    const w1 = maps.filter(m => m.winner === 1).length, w2 = maps.filter(m => m.winner === 2).length;
    // over = a side has the maps to win: BO5 3, BO7 4 (10-23: 'any map won' called CB-O2 over at 1-0, mid-match).
    // Liquipedia's own winner / finished still end a match early (forfeit)
    const need = Math.floor((num(args.bestof) || 5) / 2) + 1;
    const over = Math.max(w1, w2) >= need || num(args.winner) != null || args.finished === 'true';
    const broadcast = Object.fromEntries(['afreeca', 'soop', 'chzzk', 'twitch', 'youtube'].filter(k => args[k]).map(k => [k, args[k]]));
    return {
      competition, idx,
      date,
      bestof: num(args.bestof),
      team1: team('opponent1'), team2: team('opponent2'),
      score1: w1, score2: w2,
      winner: num(args.winner) ?? (!over ? null : w1 > w2 ? 1 : w2 > w1 ? 2 : 0),
      played: over,
      maps, potm: args.mvp || null, broadcast, vod: args.vod || null,
      casters: Object.entries(args).filter(([k]) => /^caster\d/.test(k)).map(([, v]) => v),
      section: (places[idx] || {}).section || '', round: (places[idx] || {}).round || '',
    };
  });
}
