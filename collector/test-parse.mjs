import fs from 'node:fs/promises';
import { parseMatches } from './liquipedia.mjs';
const t = await fs.readFile('data/lp_korea_s3_rs.wiki', 'utf8');
const ms = parseMatches(t, 'korea-s3-rs');
console.log('matches', ms.length, 'played', ms.filter(m => m.played).length);
console.log(JSON.stringify(ms[0], null, 1).slice(0, 1400));
console.log('potm', ms.filter(m => m.potm).length, 'no-date', ms.filter(m => !m.date).length);
