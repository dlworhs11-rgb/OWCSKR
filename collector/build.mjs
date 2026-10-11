import fs from 'node:fs';
const aliases = JSON.parse(fs.readFileSync('data/aliases.json', 'utf8'));
const canon = raw => {
  const n = (raw || '').replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s+/g, ' ').trim();
  if (!n) return null;
  return aliases[n.toLowerCase()] || n;
};
const compName = t => t.replace('Overwatch Champions Series/', 'OWCS ').replace('Overwatch World Cup/', 'OWWC ');

// ---- matches (dedupe by date + teams) ----
const files = fs.readdirSync('data/lp').filter(f => f.endsWith('.json') && !f.startsWith('_'));
const seen = new Map();
const koreanTeams = new Set();
const players = fs.existsSync('data/manual/players.json') ? JSON.parse(fs.readFileSync('data/manual/players.json', 'utf8')) : [];
for (const p of players.filter(p => p.region === 'KR')) koreanTeams.add(canon(p.team));
const handleAlias = fs.existsSync('data/manual/handle-aliases.json') ? JSON.parse(fs.readFileSync('data/manual/handle-aliases.json', 'utf8')) : {};
for (const f of files) {
  const { title, matches } = JSON.parse(fs.readFileSync('data/lp/' + f, 'utf8'));
  const krLeague = /\/Korea\/(Regular Season|Group Stage|Relegation)$/.test(title);
  for (const m of matches) {
    const t1 = canon(m.team1), t2 = canon(m.team2);
    if (!t1 || !t2) continue;
    if (krLeague) { koreanTeams.add(t1); koreanTeams.add(t2); }
    if (!m.date) continue;
    const key = `${m.date}|${[t1, t2].sort().join('|')}`;
    const rec = { ...m, team1: t1, team2: t2, competition: compName(title), competitionTitle: title };
    const old = seen.get(key);
    if (!old || (rec.played && !old.played) || (rec.played === old.played && title.length > old.competitionTitle.length)) seen.set(key, rec);
  }
}
const isKR = t => koreanTeams.has(t) || /^south korea$/i.test(t);
const matches = [...seen.values()].sort((a, b) => a.date.localeCompare(b.date));
const krMatches = matches.filter(m => isKR(m.team1) || isKR(m.team2));

// ---- team stats ----
const teams = {};
const T = n => teams[n] ??= { name: n, matches: 0, wins: 0, losses: 0, mapWins: 0, mapLosses: 0, potmWon: 0 };
for (const m of krMatches.filter(x => x.played && x.winner)) {
  for (const [me, mine, theirs, side] of [[m.team1, m.score1, m.score2, 1], [m.team2, m.score2, m.score1, 2]]) {
    if (!isKR(me) || /^south korea$/i.test(me)) continue;
    const s = T(me); s.matches++; s.mapWins += mine; s.mapLosses += theirs;
    if (m.winner === side) { s.wins++; if (m.potm) s.potmWon++; } else s.losses++;
  }
}
const pct = (a, b) => (a + b ? +(a / (a + b) * 100).toFixed(1) : null);
for (const s of Object.values(teams)) { s.winRate = pct(s.wins, s.losses); s.mapWinRate = pct(s.mapWins, s.mapLosses); }

// ---- standings per league page (regular season / group stage) ----
const standings = {};
for (const m of krMatches.filter(x => x.played && /\/Korea\/(Regular Season|Group Stage)$/.test(x.competitionTitle) && x.winner)) {
  const st = standings[m.competition] ??= {};
  for (const [me, mine, theirs, side] of [[m.team1, m.score1, m.score2, 1], [m.team2, m.score2, m.score1, 2]]) {
    const s = st[me] ??= { team: me, w: 0, l: 0, mw: 0, ml: 0 };
    s.mw += mine; s.ml += theirs; m.winner === side ? s.w++ : s.l++;
  }
}
const standingsOut = Object.fromEntries(Object.entries(standings).map(([k, v]) => [k, Object.values(v).sort((a, b) => b.w - a.w || (b.mw - b.ml) - (a.mw - a.ml)).map((s, i) => ({ rank: i + 1, ...s, diff: s.mw - s.ml }))]));

// ---- players: link sheet rows to POTM counts by latin handle ----
const norm = s => { const k = (s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); return handleAlias[k] || k; };
const handleOf = nm => (nm.match(/[A-Za-z0-9][A-Za-z0-9 .]*$/) || [nm])[0].trim();
const byHandle = new Map();
const playerOut = players.map(p => {
  const o = { region: p.region, handle: handleOf(p.name), nameKo: p.name.replace(handleOf(p.name), '').trim() || null, team: p.team === 'FA' ? null : canon(p.team), role: p.role, soop: p.soop, chzzk: p.chzzk, discord: p.discord, youtube: p.youtube, potm: 0 };
  byHandle.set(norm(o.handle), o);
  return o;
});
const unmatched = {};
for (const m of krMatches.filter(x => x.potm)) {
  const k = norm(m.potm);
  const o = byHandle.get(k);
  if (o) o.potm++;
  else unmatched[m.potm] = (unmatched[m.potm] || 0) + 1;
}
playerOut.sort((a, b) => b.potm - a.potm);
const potmAll = {};
for (const m of krMatches.filter(x => x.potm)) {
  const k = norm(m.potm); const team = m.winner === 1 ? m.team1 : m.winner === 2 ? m.team2 : null;
  const p = potmAll[k] ??= { handle: m.potm, count: 0, teams: {}, last: m.date };
  p.count++; if (team) { p.teams[team] = (p.teams[team] || 0) + 1; if (!p.lastTeamAt || m.date >= p.lastTeamAt) { p.lastTeam = team; p.lastTeamAt = m.date; } } if (m.date > p.last) p.last = m.date;
}
const potmOut = Object.entries(potmAll).map(([k, p]) => ({ key: k, handle: byHandle.get(k)?.handle || p.handle, count: p.count, teams: p.teams, lastTeam: byHandle.get(k)?.team || p.lastTeam || null, last: p.last, current: !!byHandle.get(k) && byHandle.get(k).team != null })).sort((a, b) => b.count - a.count);

fs.mkdirSync('data/site', { recursive: true });
const w = (n, d) => fs.writeFileSync(`data/site/${n}.json`, JSON.stringify(d));
w('matches', krMatches);
w('team-stats', Object.values(teams).sort((a, b) => b.wins - a.wins));
w('standings', standingsOut);
w('players', playerOut);
w('potm', potmOut);
w('potm-unmatched', Object.entries(unmatched).sort((a, b) => b[1] - a[1]).map(([handle, count]) => ({ handle, count })));
console.log('matches', matches.length, 'KR', krMatches.length, '| KR teams', koreanTeams.size, '| players', playerOut.length, '| standings tables', Object.keys(standingsOut).length);
console.log('top teams', Object.values(teams).sort((a, b) => b.wins - a.wins).slice(0, 8).map(t => `${t.name} ${t.wins}-${t.losses}`).join(' | '));
console.log('potm linked', playerOut.reduce((a, p) => a + p.potm, 0), 'unmatched', Object.values(unmatched).reduce((a, b) => a + b, 0));
console.log('unmatched top', Object.entries(unmatched).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([h, c]) => h + ':' + c).join(' '));
