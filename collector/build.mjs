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

// ---- replay codes: attach to Korean league series by (year, stage, team pair, order) ----
const replaySheet = fs.existsSync('data/manual/replays.json') ? JSON.parse(fs.readFileSync('data/manual/replays.json', 'utf8')) : [];
const rTeams = fs.existsSync('data/manual/replay-teams.json') ? JSON.parse(fs.readFileSync('data/manual/replay-teams.json', 'utf8')) : {};
const sheetTeam = n => { const k = (n || '').toLowerCase().replace(/[^a-z0-9]/g, ''); return rTeams[k] || canon(n); };
const stageOf = title => { const m = /\/(20\d\d)\/Asia\/Stage (\d)\/(?:Championship\/)?Korea(?:\/(?:Regular Season|Group Stage|Relegation))?$/.exec(title); return m ? m[1] + '|Stage ' + m[2] : null; };
const pairKey = (a, b) => [a, b].sort().join('~');
const ours = new Map();
for (const m of krMatches) { const st = stageOf(m.competitionTitle); if (!st) continue; const k = st + '|' + pairKey(m.team1, m.team2); (ours.get(k) ?? ours.set(k, []).get(k)).push(m); }
const theirs = new Map();
for (const s of replaySheet) { const k = s.year + '|' + s.stage + '|' + pairKey(sheetTeam(s.teamA), sheetTeam(s.teamB)); (theirs.get(k) ?? theirs.set(k, []).get(k)).push(s); }
let linked = 0, countMismatch = 0; const orphanKeys = [];
for (const [k, list] of theirs) {
  const mine = ours.get(k);
  if (!mine) { orphanKeys.push(k); continue; }
  list.sort((a, b) => a.order - b.order || a.day - b.day || a.matchNo - b.matchNo);
  mine.sort((a, b) => a.date.localeCompare(b.date));
  list.forEach((s, i) => { const m = mine[i]; if (!m) return; m.replays = s.codes.map(c => c || null); linked++; if (m.maps.length && s.codes.filter(Boolean).length !== m.maps.length) countMismatch++; });
}
console.log('replays: sheet series', replaySheet.length, 'linked', linked, 'game-count mismatches', countMismatch, 'unlinked keys', orphanKeys.length, orphanKeys.slice(0, 6).join(' ; '));

// ---- per-player map stats read from the broadcast GAME DATA screens (data/manual/mapstats/*.json) ----
const mapstatDir = 'data/manual/mapstats';
const normMap = s => (s || '').toLowerCase().normalize('NFD').replace(/[^a-z0-9]/g, '');
const secs = t => { const m = /^(\d+):(\d\d)$/.exec(t || ''); return m ? +m[1] * 60 + +m[2] : null; };
const pAgg = {};
let msLinked = 0, msTotal = 0;
if (fs.existsSync(mapstatDir)) for (const file of fs.readdirSync(mapstatDir).filter(x => x.endsWith('.json'))) {
  const ms = JSON.parse(fs.readFileSync(mapstatDir + '/' + file, 'utf8'));
  for (const r of ms.matches || []) {          // match-level results read from the broadcast (POTM, map wins)
    const [ta, tb] = (r.match || '').split(' vs ');
    const m = krMatches.find(x => x.date.startsWith(ms.date) && pairKey2(x.team1, x.team2) === pairKey2(ta, tb));
    if (m) { m.potmLive = r.potm ?? null; m.mapWinsLive = r.mapWins ?? null; }
  }
  for (const sm of ms.maps) {
    msTotal++;
    const [ta, tb] = Object.keys(sm.teams);
    const m = krMatches.find(x => x.date.startsWith(ms.date) && pairKey2(x.team1, x.team2) === pairKey2(ta, tb));
    if (!m) { console.log('mapstats: no match for', ms.date, ta, tb); continue; }
    const lp = m.maps[sm.game - 1];
    if (lp && lp.map && normMap(lp.map) !== normMap(sm.map)) console.log('mapstats: map name mismatch', ms.date, ta, tb, 'G' + sm.game, lp.map, 'vs', sm.map);
    (m.mapStats ??= []).push({ game: sm.game, map: sm.map, mapTime: sm.mapTime, teams: sm.teams, reading: sm.reading, verified: sm.totalsVerified ?? null, bans: sm.bans ?? null, winner: sm.winner ?? null, seriesBefore: sm.seriesBefore ?? null });
    msLinked++;
    const dur = secs(sm.mapTime);
    for (const [team, rows] of Object.entries(sm.teams)) for (const r of rows) {
      const k = normPlayer(r.name) + '|' + team;
      const a = pAgg[k] ??= { handle: r.name, team, maps: 0, secs: 0, e: 0, a: 0, d: 0, dmg: 0, heal: 0, mit: 0 };
      a.maps++; a.secs += dur || 0; a.e += r.e; a.a += r.a; a.d += r.d; a.dmg += r.dmg; a.heal += r.heal; a.mit += r.mit;
    }
  }
}
function pairKey2(a, b) { return [a, b].sort().join('~'); }
function normPlayer(n) { return (n || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }
const playerStats = Object.values(pAgg).map(a => {
  const per10 = v => (a.secs ? +(v / a.secs * 600).toFixed(0) : null);
  return { ...a, minutes: +(a.secs / 60).toFixed(1), ed: a.d ? +(a.e / a.d).toFixed(2) : null, dmg10: per10(a.dmg), heal10: per10(a.heal), mit10: per10(a.mit), e10: a.secs ? +(a.e / a.secs * 600).toFixed(1) : null, d10: a.secs ? +(a.d / a.secs * 600).toFixed(1) : null };
}).sort((x, y) => (y.ed ?? 0) - (x.ed ?? 0));
console.log('mapstats: maps', msTotal, 'linked', msLinked, 'players', playerStats.length);

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
w('player-stats', playerStats);
w('team-stats', Object.values(teams).sort((a, b) => b.wins - a.wins));
w('standings', standingsOut);
w('players', playerOut);
w('potm', potmOut);
w('potm-unmatched', Object.entries(unmatched).sort((a, b) => b[1] - a[1]).map(([handle, count]) => ({ handle, count })));
console.log('matches', matches.length, 'KR', krMatches.length, '| KR teams', koreanTeams.size, '| players', playerOut.length, '| standings tables', Object.keys(standingsOut).length);
console.log('top teams', Object.values(teams).sort((a, b) => b.wins - a.wins).slice(0, 8).map(t => `${t.name} ${t.wins}-${t.losses}`).join(' | '));
console.log('potm linked', playerOut.reduce((a, p) => a + p.potm, 0), 'unmatched', Object.values(unmatched).reduce((a, b) => a + b, 0));
console.log('unmatched top', Object.entries(unmatched).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([h, c]) => h + ':' + c).join(' '));
