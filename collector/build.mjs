import fs from 'node:fs';
const aliases = JSON.parse(fs.readFileSync('data/aliases.json', 'utf8'));
const canon = raw => {
  const n = (raw || '').replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s+/g, ' ').trim();
  if (!n) return null;
  const k = n.toLowerCase();
  return aliases[k] || aliases[raw.toLowerCase()] || n;
};
const files = fs.readdirSync('data/lp').filter(f => f.endsWith('.json') && !f.startsWith('_'));
const seen = new Map(); const koreanTeams = new Set();
const compName = t => t.replace('Overwatch Champions Series/', 'OWCS ').replace('Overwatch World Cup/', 'OWWC ');
for (const f of files) {
  const { title, matches } = JSON.parse(fs.readFileSync('data/lp/' + f, 'utf8'));
  for (const m of matches) {
    const t1 = canon(m.team1), t2 = canon(m.team2);
    if (!t1 || !t2) continue;
    if (/\/Korea/.test(title)) { koreanTeams.add(t1); koreanTeams.add(t2); }
    const key = `${m.date}|${[t1, t2].sort().join('|')}`;
    const rec = { ...m, team1: t1, team2: t2, competition: compName(title), competitionTitle: title };
    const old = seen.get(key);
    // keep the record from the most specific (longest) page title; played beats unplayed
    if (!old || (rec.played && !old.played) || (rec.played === old.played && title.length > old.competitionTitle.length)) seen.set(key, rec);
  }
}
const matches = [...seen.values()].filter(m => m.date).sort((a, b) => a.date.localeCompare(b.date));
const isKR = t => koreanTeams.has(t) || /^south korea$/i.test(t);

// Team stats (Korean teams only)
const teams = {};
const T = n => teams[n] ??= { name: n, matches: 0, wins: 0, losses: 0, mapWins: 0, mapLosses: 0, potmTeam: 0 };
for (const m of matches.filter(x => x.played && x.winner)) {
  for (const [me, opp, mine, theirs, side] of [[m.team1, m.team2, m.score1, m.score2, 1], [m.team2, m.team1, m.score2, m.score1, 2]]) {
    if (!isKR(me)) continue;
    const s = T(me); s.matches++; s.mapWins += mine; s.mapLosses += theirs;
    if (m.winner === side) { s.wins++; if (m.potm) s.potmTeam++; } else s.losses++;
  }
}
for (const s of Object.values(teams)) { s.winRate = s.matches ? +(s.wins / s.matches * 100).toFixed(1) : null; s.mapWinRate = s.mapWins + s.mapLosses ? +(s.mapWins / (s.mapWins + s.mapLosses) * 100).toFixed(1) : null; }

// POTM leaderboard (handle string from Liquipedia "mvp")
const potm = {};
for (const m of matches.filter(x => x.potm)) {
  const h = m.potm.trim(); const k = h.toLowerCase();
  const team = m.winner === 1 ? m.team1 : m.winner === 2 ? m.team2 : null;
  const p = potm[k] ??= { handle: h, count: 0, teams: {} };
  p.count++; if (team) p.teams[team] = (p.teams[team] || 0) + 1;
}
fs.mkdirSync('data/site', { recursive: true });
const krMatches = matches.filter(m => isKR(m.team1) || isKR(m.team2));
fs.writeFileSync('data/site/matches.json', JSON.stringify(krMatches));
fs.writeFileSync('data/site/team-stats.json', JSON.stringify(Object.values(teams).sort((a, b) => b.wins - a.wins)));
fs.writeFileSync('data/site/potm.json', JSON.stringify(Object.values(potm).sort((a, b) => b.count - a.count)));
console.log('matches total', matches.length, 'with KR team', krMatches.length, 'KR teams', koreanTeams.size);
console.log('top teams', Object.values(teams).sort((a, b) => b.wins - a.wins).slice(0, 6).map(t => `${t.name} ${t.wins}-${t.losses} (${t.winRate}%)`).join(' | '));
console.log('top potm', Object.values(potm).sort((a, b) => b.count - a.count).slice(0, 8).map(p => `${p.handle} ${p.count}`).join(' | '));
