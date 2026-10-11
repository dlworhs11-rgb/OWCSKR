// OWCSKR single-page app (no build step). Data: ./data/*.json produced by collector/build.mjs
const $app = document.getElementById('app');
const D = {};
const LOAD = ['matches', 'team-stats', 'standings', 'players', 'potm', 'live'];

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeUrl = u => (/^https?:\/\//i.test(u || '') ? esc(u) : '');
const fmtDate = iso => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }); };
const year = iso => (iso || '').slice(0, 4);
const prettyComp = c => c.replace(/^OWCS /, 'OWCS ').replace(/\/Asia\//, ' ').replace(/\//g, ' · ');
const teamLink = n => `<a href="#/team/${encodeURIComponent(n)}">${esc(n)}</a>`;
const cmpDesc = (a, b) => b - a;

async function load() {
  await Promise.all(LOAD.map(async n => {
    try { D[n] = await (await fetch(`data/${n}.json`)).json(); } catch { D[n] = n === 'live' ? { live: [], soopTargets: [] } : []; }
  }));
  const u = D.live?.updatedAt;
  document.getElementById('updated').textContent = u ? fmtDate(u) + ' (KST)' : '-';
}

// ---------- pieces ----------
function matchRow(m) {
  const w1 = m.winner === 1, w2 = m.winner === 2;
  const sc = m.played ? `${m.score1} : ${m.score2}` : 'vs';
  return `<div class="card"><div class="row muted"><span>${esc(fmtDate(m.date))}</span><span>${esc(prettyComp(m.competition))}${m.potm ? ` · POTM <b>${esc(m.potm)}</b>` : ''}</span></div>
  <div class="match"><span class="${w1 ? 'win' : w2 ? 'lose' : ''}">${teamLink(m.team1)}</span><span class="score">${sc}</span><span class="t2 ${w2 ? 'win' : w1 ? 'lose' : ''}">${teamLink(m.team2)}</span></div></div>`;
}

function links(p) {
  const l = [];
  if (p.chzzk) l.push(`<a href="${safeUrl(p.chzzk)}" rel="noopener" target="_blank">치지직</a>`);
  if (p.soop) l.push(`<a href="${safeUrl(p.soop)}" rel="noopener" target="_blank">SOOP</a>`);
  if (p.youtube) l.push(`<a href="${safeUrl(p.youtube)}" rel="noopener" target="_blank">YouTube</a>`);
  if (p.discord) l.push(`<a href="${safeUrl(p.discord)}" rel="noopener" target="_blank">디스코드</a>`);
  return l.join('') ? `<span class="links">${l.join('')}</span>` : '<span class="muted">-</span>';
}

function standingsTable(rows) {
  return `<div class="scroll"><table><thead><tr><th class="n">#</th><th>팀</th><th class="n">승</th><th class="n">패</th><th class="n">세트 득실</th></tr></thead><tbody>${rows.map(r => `<tr><td class="n">${r.rank}</td><td>${teamLink(r.team)}</td><td class="n">${r.w}</td><td class="n">${r.l}</td><td class="n">${r.diff > 0 ? '+' : ''}${r.diff}</td></tr>`).join('')}</tbody></table></div>`;
}

// live: chzzk from live.json, soop from visitor's browser
async function liveBox() {
  const live = [];
  for (const e of D.live.live || []) for (const [k, v] of Object.entries(e.platforms)) if (v.live) live.push({ handle: e.handle, team: e.team, platform: k === 'chzzk' ? '치지직' : 'SOOP', title: v.title, viewers: v.viewers, url: v.url });
  const box = document.createElement('div');
  const draw = () => {
    box.innerHTML = live.length
      ? `<div class="grid">${live.map(l => `<a class="card" href="${safeUrl(l.url)}" target="_blank" rel="noopener"><span class="badge live">LIVE</span> <b>${esc(l.handle)}</b> <span class="muted">${esc(l.team || '')}</span><div>${esc(l.title || '')}</div><div class="muted">${esc(l.platform)}${l.viewers ? ` · ${l.viewers.toLocaleString()}명` : ''}</div></a>`).join('')}</div>`
      : '<p class="muted">지금 방송 중인 선수가 없습니다.</p>';
  };
  draw();
  if (window.SoopLive && D.live.soopTargets?.length) {
    SoopLive.check(D.live.soopTargets).then(res => {
      for (const t of D.live.soopTargets) { const v = res[t.id]; if (v?.live) live.push({ handle: t.handle, team: t.team, platform: 'SOOP', title: v.title, viewers: v.viewers, url: `https://play.sooplive.com/${t.id}` }); }
      draw();
    });
  }
  return box;
}

// ---------- pages ----------
async function home() {
  const played = D.matches.filter(m => m.played).slice(-8).reverse();
  const upcoming = D.matches.filter(m => !m.played && m.date > new Date().toISOString()).slice(0, 5);
  const latestComp = Object.keys(D.standings).filter(k => /Korea/.test(k)).sort().pop();
  $app.innerHTML = `<h1>한국 OWCS 허브</h1><h2>지금 라이브</h2><div id="live"></div>
  <h2>다가오는 경기</h2>${upcoming.map(matchRow).join('') || '<p class="muted">예정된 경기가 없습니다.</p>'}
  <h2>최근 결과</h2>${played.map(matchRow).join('')}
  ${latestComp ? `<h2>순위 · ${esc(prettyComp(latestComp))}</h2>${standingsTable(D.standings[latestComp])}` : ''}`;
  document.getElementById('live').replaceWith(await liveBox());
}

function teams() {
  const rows = D['team-stats'].filter(t => t.matches >= 5);
  $app.innerHTML = `<h1>팀</h1><input class="search" placeholder="팀 검색" id="q"><div class="scroll"><table><thead><tr><th>팀</th><th class="n">경기</th><th class="n">승</th><th class="n">패</th><th class="n">승률</th><th class="n">세트 승률</th></tr></thead><tbody id="tb"></tbody></table></div><p class="muted">2024~2026 전체 (한국 대회 + 국제대회), 5경기 이상 팀</p>`;
  const draw = q => { document.getElementById('tb').innerHTML = rows.filter(t => t.name.toLowerCase().includes(q)).map(t => `<tr><td>${teamLink(t.name)}</td><td class="n">${t.matches}</td><td class="n">${t.wins}</td><td class="n">${t.losses}</td><td class="n">${t.winRate ?? '-'}%</td><td class="n">${t.mapWinRate ?? '-'}%</td></tr>`).join(''); };
  draw('');
  document.getElementById('q').oninput = e => draw(e.target.value.toLowerCase());
}

function team(name) {
  const t = D['team-stats'].find(x => x.name === name);
  const roster = D.players.filter(p => p.team === name && p.region === 'KR');
  const ms = D.matches.filter(m => m.team1 === name || m.team2 === name).slice().reverse();
  $app.innerHTML = `<h1>${esc(name)}</h1>
  ${t ? `<div class="card row"><span>경기 ${t.matches}</span><span>${t.wins}승 ${t.losses}패 (${t.winRate}%)</span><span>세트 승률 ${t.mapWinRate}%</span></div>` : ''}
  ${roster.length ? `<h2>로스터</h2><div class="scroll"><table><thead><tr><th>선수</th><th>역할</th><th class="n">POTM</th><th>링크</th></tr></thead><tbody>${roster.map(p => `<tr><td>${esc(p.handle)} <span class="muted">${esc(p.nameKo || '')}</span></td><td>${esc(p.role)}</td><td class="n">${p.potm}</td><td>${links(p)}</td></tr>`).join('')}</tbody></table></div>` : ''}
  <h2>최근 경기</h2>${ms.slice(0, 15).map(matchRow).join('') || '<p class="muted">경기 없음</p>'}`;
}

function players() {
  const rows = D.players.filter(p => p.region === 'KR').sort((a, b) => b.potm - a.potm);
  $app.innerHTML = `<h1>선수</h1><input class="search" placeholder="선수·팀 검색" id="q"><div class="scroll"><table><thead><tr><th>선수</th><th>팀</th><th>역할</th><th class="n">POTM</th><th>링크</th></tr></thead><tbody id="tb"></tbody></table></div>`;
  const draw = q => { document.getElementById('tb').innerHTML = rows.filter(p => (p.handle + (p.nameKo || '') + (p.team || '')).toLowerCase().includes(q)).map(p => `<tr><td>${esc(p.handle)} <span class="muted">${esc(p.nameKo || '')}</span></td><td>${p.team ? teamLink(p.team) : '-'}</td><td>${esc(p.role)}</td><td class="n">${p.potm}</td><td>${links(p)}</td></tr>`).join(''); };
  draw('');
  document.getElementById('q').oninput = e => draw(e.target.value.toLowerCase());
}

function potm() {
  const rows = D.potm.slice(0, 50);
  $app.innerHTML = `<h1>POTM 순위</h1><div class="scroll"><table><thead><tr><th class="n">#</th><th>선수</th><th>최근 소속</th><th class="n">횟수</th><th>상태</th></tr></thead><tbody>${rows.map((r, i) => { return `<tr><td class="n">${i + 1}</td><td>${esc(r.handle)}</td><td>${r.lastTeam ? teamLink(r.lastTeam) : '-'}</td><td class="n">${r.count}</td><td>${r.current ? '' : '<span class="pill">이전 선수</span>'}</td></tr>`; }).join('')}</tbody></table></div><p class="muted">Liquipedia MVP 기록 기준 (2024~2026, 한국팀 경기)</p>`;
}

function competitions(sel) {
  const names = [...new Set(D.matches.map(m => m.competition))].sort().reverse();
  const cur = sel && names.includes(sel) ? sel : names[0];
  const ms = D.matches.filter(m => m.competition === cur).slice().reverse();
  const st = D.standings[cur];
  $app.innerHTML = `<h1>대회</h1><select id="sel">${names.map(n => `<option value="${esc(n)}" ${n === cur ? 'selected' : ''}>${esc(prettyComp(n))}</option>`).join('')}</select>
  ${st ? `<h2>순위</h2>${standingsTable(st)}` : ''}<h2>경기 (${ms.length})</h2>${ms.map(matchRow).join('')}`;
  document.getElementById('sel').onchange = e => { location.hash = '#/competitions/' + encodeURIComponent(e.target.value); };
}

// ---------- router ----------
async function route() {
  const [, page, arg] = location.hash.replace(/^#/, '').split('/');
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('on', a.dataset.nav === (page || 'home')));
  const a = arg ? decodeURIComponent(arg) : '';
  window.scrollTo(0, 0);
  if (page === 'teams') teams();
  else if (page === 'team') team(a);
  else if (page === 'players') players();
  else if (page === 'potm') potm();
  else if (page === 'competitions') competitions(a);
  else await home();
}
window.addEventListener('hashchange', route);
load().then(route).catch(e => { $app.innerHTML = `<p>데이터를 불러오지 못했습니다. (${esc(e.message)})</p>`; });
