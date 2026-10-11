import fs from 'node:fs/promises';
import { wikitext, parseMatches } from './liquipedia.mjs';
const comps = JSON.parse(await fs.readFile('data/competitions.json', 'utf8'));
const titles = [...comps.core, ...comps.world_cup.filter(t => /20(23|26)$/.test(t))];
await fs.mkdir('data/lp', { recursive: true });
const summary = [];
for (const title of titles) {
  try {
    const t = await wikitext(title, { maxAgeMs: 6 * 3600e3 });
    if (t == null) { console.log('MISSING', title); summary.push({ title, missing: true }); continue; }
    const matches = parseMatches(t, title);
    const slug = title.replace(/^Overwatch (Champions Series|World Cup)\//, '').replace(/[^a-z0-9]+/gi, '-').toLowerCase();
    const prefix = title.includes('World Cup') ? 'owwc-' : 'owcs-';
    await fs.writeFile(`data/lp/${prefix}${slug}.json`, JSON.stringify({ title, matches }, null, 1));
    const played = matches.filter(m => m.played).length;
    console.log(String(matches.length).padStart(4), 'matches', String(played).padStart(4), 'played', title);
    summary.push({ title, matches: matches.length, played });
  } catch (e) { console.log('ERR', title, e.message); }
}
await fs.writeFile('data/lp/_summary.json', JSON.stringify(summary, null, 1));
console.log('DONE');
