// Who is live right now? Chzzk + SOOP -> data/site/live.json
import fs from 'node:fs';

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function getJson(url, tries = 3) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(10000) });
      if (r.ok) return await r.json();
      if (r.status === 404) return null;
    } catch { /* network reset: retry */ }
    await sleep(800 * (i + 1));
  }
  return null;
}

const chzzkId = u => (u || '').match(/chzzk\.naver\.com\/(?:live\/)?([0-9a-f]{32})/i)?.[1];
const soopId = u => (u || '').match(/(?:sooplive\.com|afreecatv\.com)\/(?:station\/)?([A-Za-z0-9_]+)/)?.[1];

export async function checkLive(players) {
  const out = [];
  for (const p of players) {
    const entry = { handle: p.handle, team: p.team, platforms: {} };
    const c = chzzkId(p.chzzk);
    if (c) {
      const j = await getJson(`https://api.chzzk.naver.com/polling/v2/channels/${c}/live-status`);
      const d = j?.content; // content is null when the channel is not broadcasting
      entry.platforms.chzzk = { ok: j?.code === 200, live: d?.status === 'OPEN', title: d?.status === 'OPEN' ? d.liveTitle : null, viewers: d?.status === 'OPEN' ? d.concurrentUserCount : null, url: `https://chzzk.naver.com/live/${c}` };
      await sleep(250);
    }
    // SOOP is checked in the visitor's own browser (the old site did this in the browser): its API rejects non-browser servers.
    if (soopId(p.soop)) entry.soop = soopId(p.soop);
    if (Object.keys(entry.platforms).length || entry.soop) out.push(entry);
  }
  return out;
}

if (process.argv[1].endsWith('live.mjs')) {
  const players = JSON.parse(fs.readFileSync('data/site/players.json', 'utf8')).filter(p => p.region === 'KR');
  const list = await checkLive(players);
  const res = { updatedAt: new Date().toISOString(), live: list.filter(e => Object.values(e.platforms).some(x => x.live)), checked: list.length, soopTargets: list.filter(e => e.soop).map(e => ({ handle: e.handle, team: e.team, id: e.soop })), errors: list.flatMap(e => Object.entries(e.platforms).filter(([, v]) => !v.ok).map(([k]) => `${e.handle}/${k}`)) };
  fs.writeFileSync('data/site/live.json', JSON.stringify(res, null, 1));
  console.log(`checked ${res.checked} players, live now: ${res.live.length}, errors: ${res.errors.length}`);
  for (const e of res.live) console.log(' LIVE', e.handle, JSON.stringify(Object.fromEntries(Object.entries(e.platforms).filter(([, v]) => v.live).map(([k, v]) => [k, v.title]))));
  if (res.errors.length) console.log(' errors:', res.errors.slice(0, 8).join(', '));
}
