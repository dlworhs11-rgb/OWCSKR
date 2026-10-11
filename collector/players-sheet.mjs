// Community sheet (KR / ...) -> data/manual/players.json
// Layout per team: header row (team name in col B), then per 2 players: name row, Soop row, 치지직 row, Discord row.
import fs from 'node:fs';

const SHEET = 'https://docs.google.com/spreadsheets/d/10ynVC7EVRDmvlKOAKbasm5ivnnOJ045JVosU5EIzE10/export?format=csv';

function csv(text) {
  const rows = []; let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n') { row.push(cur.replace(/\r$/, '')); rows.push(row); row = []; cur = ''; }
    else cur += c;
  }
  row.push(cur); rows.push(row);
  return rows;
}

const ROLE = /\((TANK|DPS|SUP|SUPPORT)\)?/i;
const url = s => { s = (s || '').trim(); if (!s) return null; if (!/^https?:/i.test(s)) s = 'https://' + s.replace(/^\/+/, ''); return s.replace('://m.chzzk.naver.com', '://chzzk.naver.com'); };

export async function readSheet(useCache = true) {
  const f = 'data/sheets/players.csv';
  if (!(useCache && fs.existsSync(f))) { fs.mkdirSync('data/sheets', { recursive: true }); fs.writeFileSync(f, Buffer.from(await (await fetch(SHEET)).arrayBuffer())); }
  return csv(fs.readFileSync(f, 'utf8'));
}

export function parse(rows) {
  const out = [], yt = []; let region = null, team = null;
  const REG = new Set(['KR', 'CN', 'EMEA', 'NA', 'JP', 'LFT']);
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i].map(x => (x || '').trim());
    if (REG.has(r[0]) && !r[1]) { region = r[0]; team = r[0] === 'KR' ? null : r[0] === 'LFT' ? 'FA' : r[0]; continue; }
    // team header: col A empty, col B text w/o role, next non-empty row has roles
    if (!r[0] && r[1] && !ROLE.test(r[1]) && !/^https?:/i.test(r[1]) && !r[1].startsWith('*') && ROLE.test(rows[i + 1]?.[1] || '')) { team = r[1]; continue; }
    if (!team || !region) continue;
    if (/youtube.com|youtu.be/i.test(r[5] || '') && r[4]) yt.push({ region, team, label: r[4], url: url(r[5]) });
    // player name row
    if (!/^(soop|치지직|discord)$/i.test(r[0]) && (ROLE.test(r[1]) || ROLE.test(r[3]))) {
      const next = rows.slice(i + 1, i + 4).map(x => x.map(y => (y || '').trim()));
      for (const col of [1, 3]) {
        const raw = r[col]; if (!raw || !ROLE.test(raw)) continue;
        const role = ROLE.exec(raw)[1].toUpperCase().replace('SUPPORT', 'SUP');
        const nm = raw.replace(ROLE, '').replace(/\)$/, '').trim();
        const get = label => { const rr = next.find(n => n[col - 1].toLowerCase() === label); return url(rr?.[col]); };
        out.push({ region, team, name: nm, role, soop: get('soop'), chzzk: get('치지직'), discord: get('discord'), youtube: null });
      }
    }
  }
  for (const y of yt) { const p = out.find(p => p.region === y.region && p.team === y.team && (p.name.includes(y.label) || p.name.toLowerCase().includes(y.label.toLowerCase()))); if (p && !p.youtube) p.youtube = y.url; }
  return out;
}

if (process.argv[1].endsWith('players-sheet.mjs')) {
  const players = parse(await readSheet(!process.argv.includes('--refresh')));
  fs.mkdirSync('data/manual', { recursive: true });
  fs.writeFileSync('data/manual/players.json', JSON.stringify(players, null, 1));
  const byTeam = {}; for (const p of players) (byTeam[`${p.region}/${p.team}`] ??= []).push(p);
  for (const [t, ps] of Object.entries(byTeam)) console.log(t.padEnd(28), ps.length, 'players', ps.filter(p => p.chzzk).length, 'chzzk', ps.filter(p => p.soop).length, 'soop', ps.filter(p => p.discord).length, 'discord');
}
