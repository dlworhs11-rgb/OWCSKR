import fs from 'node:fs/promises';
import path from 'node:path';
import { findTemplates, parseTemplate } from './wikitext.mjs';

const API = 'https://liquipedia.net/overwatch/api.php';
const UA = 'OWCSKR-fansite/0.1 (+https://github.com/dlworhs11-rgb/OWCSKR)';
const CACHE = path.resolve('data/lp-cache');
const DELAY = 2200; // terms: <= 1 request / 2s (action=parse: 1 / 30s -> never used)
let last = 0;

async function api(params) {
  const wait = last + DELAY - Date.now();
  if (wait > 0) await new Promise(r => setTimeout(r, wait));
  last = Date.now();
  const res = await fetch(API + '?' + new URLSearchParams({ format: 'json', ...params }), { headers: { 'user-agent': UA, 'accept-encoding': 'gzip' } });
  if (!res.ok) throw new Error(`liquipedia ${res.status}`);
  return res.json();
}

export async function wikitext(title, { maxAgeMs = 3600e3 } = {}) {
  const file = path.join(CACHE, title.replace(/[^a-z0-9]+/gi, '_') + '.wiki');
  try { if (Date.now() - (await fs.stat(file)).mtimeMs < maxAgeMs) return fs.readFile(file, 'utf8'); } catch {}
  const r = await api({ action: 'query', prop: 'revisions', rvprop: 'content', rvslots: 'main', titles: title });
  const page = Object.values(r.query.pages)[0];
  const text = page.revisions?.[0]?.slots?.main?.['*'];
  if (text == null) return null; // missing page
  await fs.mkdir(CACHE, { recursive: true });
  await fs.writeFile(file, text);
  return text;
}

export async function linksOf(title) {
  const r = await api({ action: 'query', prop: 'links', pllimit: '500', titles: title });
  return (Object.values(r.query.pages)[0].links || []).map(l => l.title);
}

const stripLinks = s => s.replace(/\[\[(?:[^|\]]*\|)?([^\]]*)\]\]/g, '$1').trim();
const num = v => (v === undefined || v === '' ? null : Number(v));

const MONTHS = { january: 1, february: 2, march: 3, april: 4, may: 5, june: 6, july: 7, august: 8, september: 9, october: 10, november: 11, december: 12 };
// Liquipedia writes "{{Abbr/KST}}" style zone markers; map the ones that show up in OWCS pages.
const TZ = { KST: '+09:00', JST: '+09:00', CST: '+08:00', CET: '+01:00', CEST: '+02:00', BST: '+01:00', PDT: '-07:00', PST: '-08:00', EDT: '-04:00', EST: '-05:00', CDT: '-05:00', UTC: '+00:00', GMT: '+00:00' };

function parseDate(s) {
  if (!s) return null;
  const zone = (/Abbr\/(\w+)/.exec(s) || [])[1];
  const tz = TZ[zone] || '+00:00';
  let y, mo, d, m;
  if ((m = /(\d{4})-(\d{2})-(\d{2})/.exec(s))) { y = +m[1]; mo = +m[2]; d = +m[3]; }
  else if ((m = /([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})/.exec(s)) && MONTHS[m[1].toLowerCase()]) { mo = MONTHS[m[1].toLowerCase()]; d = +m[2]; y = +m[3]; }
  else return null;
  const t = /(\d{1,2}):(\d{2})/.exec(s.replace(/\d{4}-\d{2}-\d{2}/, ''));
  const p = n => String(n).padStart(2, '0');
  return `${y}-${p(mo)}-${p(d)}T${t ? p(t[1]) + ':' + t[2] : '00:00'}:00${tz}`;
}

// Parse every {{Match}} in a Liquipedia tournament page.
export function parseMatches(text, competition) {
  return findTemplates(text, 'Match').map((raw, idx) => {
    const { args } = parseTemplate(raw);
    const team = k => { const t = args[k] && findTemplates(args[k], 'TeamOpponent')[0]; return t ? parseTemplate(t).pos[0] : stripLinks(args[k] || ''); };
    const maps = Object.keys(args).filter(k => /^map\d+$/.test(k)).sort((a, b) => a.slice(3) - b.slice(3)).map((k, i) => {
      const t = findTemplates(args[k], 'Map')[0]; if (!t) return null;
      const a = parseTemplate(t).args;
      return { n: i + 1, map: a.map || null, mode: a.mode || null, score1: num(a.score1), score2: num(a.score2), winner: num(a.winner), bans: { t1: a.t1b1 || null, t2: a.t2b1 || null }, banstart: num(a.banstart) };
    }).filter(Boolean);
    const w1 = maps.filter(m => m.winner === 1).length, w2 = maps.filter(m => m.winner === 2).length;
    const broadcast = Object.fromEntries(['afreeca', 'soop', 'chzzk', 'twitch', 'youtube'].filter(k => args[k]).map(k => [k, args[k]]));
    return {
      competition, idx,
      date: parseDate(args.date),
      bestof: num(args.bestof),
      team1: team('opponent1'), team2: team('opponent2'),
      score1: w1, score2: w2,
      winner: num(args.winner) ?? (w1 + w2 === 0 ? null : w1 > w2 ? 1 : w2 > w1 ? 2 : 0),
      played: maps.some(m => m.winner),
      maps, potm: args.mvp || null, broadcast, vod: args.vod || null,
      casters: Object.entries(args).filter(([k]) => /^caster\d/.test(k)).map(([, v]) => v),
    };
  });
}
