// Community replay-code sheet, Asia tab, Korean rows (region KR) -> data/manual/replays.json
// one entry per series, codes ordered by game #. Columns: stage / region / year / phase / day / match # / game # /
// team A / team B / code. The sheet has no week: rows are in play order and the day # restarts (3 -> 1) each week,
// so the week is counted from that. build.mjs matches a series to a Liquipedia match by teams + week/day/match # + game count.
import fs from 'node:fs';

const SHEET = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRy-b0Vo5LecKRY21-pBfw40TRlqukyjyMqSOTmlo0oe4hWlFDTmnmnuuRecgAWODfPUiM5o3FJ92Xf/pub?gid=1098723955&single=true&output=csv';
const CODE = /^[A-Z0-9]{5,8}$/;

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
  if (refresh || !fs.existsSync(f)) {
    const r = await fetch(SHEET);
    if (!r.ok) throw new Error('replay sheet HTTP ' + r.status);
    fs.mkdirSync('data/sheets', { recursive: true });
    fs.writeFileSync(f, Buffer.from(await r.arrayBuffer()));
  }
  const out = []; let cur = null;
  const week = {}, lastDay = {};   // per year + stage: week counter, day # of the previous series
  csv(fs.readFileSync(f, 'utf8')).forEach((r, i) => {
    const [stage, region, year, phase, day, matchNo, game, teamA, teamB, code] = r.map(x => (x || '').trim());
    if (region !== 'KR' || !/^\d{4}$/.test(year) || !CODE.test(code)) return;
    const g = +game || 0;
    // a game typed a few rows away from its series or with another day # (2024: game 4 written as PO DAY1) joins it
    const same = s => s.stage === stage && s.year === +year && s.matchNo === (+matchNo || 0) && s.teamA === teamA && s.teamB === teamB;
    const back = g > 1 && out.slice(-4).reverse().find(s => same(s) && !s.codes[g - 1]);
    if (back) { back.codes[g - 1] = code; return; }
    // consecutive rows of the same series: same stage, day, match # and teams, game # not seen yet
    if (!cur || cur.stage !== stage || cur.year !== +year || cur.day !== (+day || 0) || cur.matchNo !== (+matchNo || 0)
        || cur.teamA !== teamA || cur.teamB !== teamB || (g && cur.codes[g - 1])) {
      const k = year + '|' + stage;
      if (!(k in week) || (+day || 0) < lastDay[k]) week[k] = (week[k] || 0) + 1;
      lastDay[k] = +day || 0;
      cur = { year: +year, stage, phase, order: PHASE_ORDER(phase), week: week[k], day: +day || 0, matchNo: +matchNo || 0, teamA, teamB, seq: out.length, row: i + 1, codes: [] };
      out.push(cur);
    }
    cur.codes[(g || cur.codes.length + 1) - 1] = code;
  });
  for (const s of out) s.codes = Array.from(s.codes, x => x || null);
  return out;
}

if (process.argv[1].endsWith('replays.mjs')) {
  const out = await readReplays(process.argv.includes('--refresh'));
  fs.mkdirSync('data/manual', { recursive: true });
  fs.writeFileSync('data/manual/replays.json', JSON.stringify(out));
  console.log('replay series', out.length, 'codes', out.reduce((a, s) => a + s.codes.filter(Boolean).length, 0));
}
