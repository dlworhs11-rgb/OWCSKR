// Community replay-code sheet -> data/manual/replays.json  (one entry per series, codes ordered by game #)
import fs from 'node:fs';

const SHEET = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRy-b0Vo5LecKRY21-pBfw40TRlqukyjyMqSOTmlo0oe4hWlFDTmnmnuuRecgAWODfPUiM5o3FJ92Xf/pub?output=csv';

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

const PHASE_ORDER = p => /playoff/i.test(p) ? 3 : /lcq|seeding|sd/i.test(p) ? 2 : 1;

export async function readReplays(refresh = false) {
  const f = 'data/sheets/replay.csv';
  if (refresh || !fs.existsSync(f)) { fs.mkdirSync('data/sheets', { recursive: true }); fs.writeFileSync(f, Buffer.from(await (await fetch(SHEET)).arrayBuffer())); }
  const rows = csv(fs.readFileSync(f, 'utf8')).slice(9)
    .filter(r => r[1] === 'KR' && /^\d{4}$/.test(r[2]) && /^[A-Z0-9]{5,8}$/.test((r[9] || '').trim()));
  const series = new Map();
  for (const r of rows) {
    const [stage, , year, phase, day, matchNo, game, teamA, teamB, code] = r.map(x => (x || '').trim());
    const key = [year, stage, phase, day, matchNo, teamA, teamB].join('|');
    const s = series.get(key) ?? { year: +year, stage, phase, order: PHASE_ORDER(phase), day: +day || 0, matchNo: +matchNo || 0, teamA, teamB, codes: [] };
    s.codes[(+game || s.codes.length + 1) - 1] = code;
    series.set(key, s);
  }
  return [...series.values()];
}

if (process.argv[1].endsWith('replays.mjs')) {
  const out = await readReplays(process.argv.includes('--refresh'));
  fs.mkdirSync('data/manual', { recursive: true });
  fs.writeFileSync('data/manual/replays.json', JSON.stringify(out));
  console.log('replay series', out.length, 'codes', out.reduce((a, s) => a + s.codes.filter(Boolean).length, 0));
}
