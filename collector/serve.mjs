import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..', 'dist'), port = Number(process.env.PORT) || 4173;
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
http.createServer((req, res) => {
  let p = path.join(root, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(root)) { res.writeHead(403).end(); return; }
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, 'index.html');
  if (!fs.existsSync(p)) { res.writeHead(404).end('not found'); return; }
  res.writeHead(200, { 'content-type': types[path.extname(p)] || 'application/octet-stream' }).end(fs.readFileSync(p));
}).listen(port, () => console.log('http://localhost:' + port));
