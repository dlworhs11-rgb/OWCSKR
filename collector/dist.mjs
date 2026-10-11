// Assemble the deployable static site: site/* + data/site/*.json -> dist/
import fs from 'node:fs';
fs.rmSync('dist', { recursive: true, force: true });
fs.cpSync('site', 'dist', { recursive: true });
fs.mkdirSync('dist/data', { recursive: true });
for (const f of fs.readdirSync('data/site').filter(f => f.endsWith('.json'))) fs.copyFileSync('data/site/' + f, 'dist/data/' + f);
console.log('dist ready:', fs.readdirSync('dist').join(', '), '| data:', fs.readdirSync('dist/data').length, 'files');
