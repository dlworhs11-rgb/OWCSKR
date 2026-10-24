// Minimal MediaWiki template parser: enough for Liquipedia {{Match}} / {{Map}} / {{TeamOpponent}}.
const OPEN = '{{', CLOSE = '}}';

// <!-- comments --> (an unclosed one runs to the end, as in MediaWiki) -> spaces, newlines kept: offsets stay valid
export const blankComments = text => text.replace(/<!--[\s\S]*?(?:-->|$)/g, c => c.replace(/[^\n]/g, ' '));

// { start, end } of each top-level {{name ...}} (name case-blind, spaces allowed around it); an unclosed one is skipped,
// one nested in another is part of it. Callers blank comments first so a commented-out template is not found.
// (The old string pattern '\{\{\s*' lost its backslashes: '{{ Match' was not found while matchPlaces counted it.)
export function templateSpans(text, name) {
  const out = [];
  const re = new RegExp(String.raw`\{\{\s*` + name + String.raw`\s*(?=[|}\n])`, 'gi');
  let m;
  while ((m = re.exec(text))) {
    const end = matchEnd(text, m.index);
    if (end < 0) continue;
    out.push({ start: m.index, end });
    re.lastIndex = end;
  }
  return out;
}

export const findTemplates = (text, name) => templateSpans(text, name).map(({ start, end }) => text.slice(start, end));

function matchEnd(text, start) {
  let depth = 0;
  for (let i = start; i < text.length - 1; i++) {
    const two = text[i] + text[i + 1];
    if (two === OPEN) { depth++; i++; }
    else if (two === CLOSE) { depth--; i++; if (depth === 0) return i + 1; }
  }
  return -1;
}

// "{{Name|a|k=v}}" -> { name, pos: [a], args: {k: v} } ; nested templates stay as raw strings.
export function parseTemplate(raw) {
  const inner = raw.trim().slice(2, -2);
  const parts = splitTop(inner);
  const name = parts.shift().trim();
  const pos = [], args = {};
  for (const p of parts) {
    const eq = topEquals(p);
    if (eq < 0) pos.push(p.trim());
    else args[p.slice(0, eq).trim().toLowerCase()] = p.slice(eq + 1).trim();
  }
  return { name, pos, args };
}

function splitTop(s) {
  const parts = []; let depth = 0, cur = '';
  for (let i = 0; i < s.length; i++) {
    const two = s.slice(i, i + 2);
    if (two === '{{' || two === '[[') { depth++; cur += two; i++; }
    else if (two === '}}' || two === ']]') { depth--; cur += two; i++; }
    else if (s[i] === '|' && depth === 0) { parts.push(cur); cur = ''; }
    else cur += s[i];
  }
  parts.push(cur);
  return parts;
}

function topEquals(p) {
  let depth = 0;
  for (let i = 0; i < p.length; i++) {
    const two = p.slice(i, i + 2);
    if (two === '{{' || two === '[[') { depth++; i++; }
    else if (two === '}}' || two === ']]') { depth--; i++; }
    else if (p[i] === '=' && depth === 0) return i;
  }
  return -1;
}
