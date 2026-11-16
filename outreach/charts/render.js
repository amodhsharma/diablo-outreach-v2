// Renders a company-status Sankey (from per-company paths) to PNG (agreed 16 Nov 2026, Ariel).
// Usage: node render.js input.json output.png
// Input: {"title", "subtitle", "paths": [{"country"?, "path": ["GATE1", "Located"], "n": 3}]}, built by
// outreach/flow_charts.py. Labels and colours follow the agreed synopsis (handbook, "Nightly flow charts").
const fs = require('fs');
const { sankey, sankeyLeft, sankeyLinkHorizontal } = require('d3-sankey');
const { Resvg } = require('@resvg/resvg-js');

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const TERMINAL = new Set(['END Sales', 'Rejected', 'Said no', 'Opted out', 'No response',
  'Inbox bounced', 'Person bounced', 'No one left', 'Blocked/bounced', 'Channel paused',
  'Missing Info', 'No Apollo', 'Back to GATE1', 'Back to Attempted', 'Reopened (backlog)',
  'Back to New', 'Back', 'Team']);

function colour(name, kind) {
  if (kind === 'country') return '#7F77DD';
  if (kind === 'waiting') return '#C9C7BE';
  if (kind === 'carry') return '#A9A7EE';
  if (name === 'END Sales') return '#1D9E75';
  if (name === 'In Progress') return '#378ADD';
  if (name === 'Team') return '#0F6E56';  // 16 Nov 2026 (Ariel): dark teal, apart from blue and green
  if (name.startsWith('Back') || name.startsWith('Reopened')) return '#BA7517';
  if (['Missing Info', 'No Apollo', 'Contact exists'].includes(name)) return '#EF9F27';
  if (TERMINAL.has(name)) return '#D85A30';
  return '#5F5E5A';
}

const LABEL = {
  'Research':'Newly found\nby research','New':'Awaiting\nyour review','GATE1':'Approved by you',
  'Contact exists':'Only manual contacts','Located':'People found\nto email','Attempted':'Emailed',
  'In Progress':'In conversation','END Sales':'Passed to\nsales team','Rejected':'Rejected by you',
  'Channel paused':'Channel no longer\ntargeted','Missing Info':'Nobody usable\nfound',
  'No Apollo':'Nobody found\non Apollo','Opted out':'Asked not to\nbe emailed','No response':'No reply',
  'Person bounced':'Emails bounced','Inbox bounced':'Company inbox\nbounced','Blocked/bounced':'Blocked by their\nemail system',
  'No one left':'Nobody left\nto email','Back to GATE1':'Back in the\napproved queue','Back to Attempted':'Back to emailing',
  'Reopened (backlog)':'Reopened: more\npeople to email','Carried over':'Already in the\npipeline before the 1st',
  'Said no':'Said no','Team':'Taken over\nby the team','Back to New':'Back for\nyour review',
  'Back':'Back to an\nearlier step'};
const WAIT = {'New':'Still awaiting\nyour review','GATE1':'Still looking\nfor people','Located':'Queued to\nbe emailed',
  'Attempted':'Awaiting a reply','In Progress':'Still in\nconversation','Contact exists':'Waiting on\nmanual contacts'};
// Build nodes and links from paths
const nodes = new Map(), links = new Map();
const node = (id, name, kind) => { if (!nodes.has(id)) nodes.set(id, { id, name, kind }); return id; };
const link = (s, t, v) => { const k = s + '>' + t; links.set(k, (links.get(k) || 0) + v); };

const ORDER = ['Research','New','GATE1','Located','Attempted','In Progress','END Sales'];
for (const p of spec.paths) {
  let prev = null;
  if (p.country) {
    prev = node('c:' + p.country, p.country, 'country');
    if (p.path[0] !== 'Research') { const c = node('carry', 'Carried over', 'carry'); link(prev, c, p.n); prev = c; }
  }
  for (const st of p.path) {
    const id = node('s:' + st, st, 'stage');
    if (prev) link(prev, id, p.n);
    prev = id;
  }
  const last = p.path[p.path.length - 1];
  if (!TERMINAL.has(last)) link(prev, node('w:' + last, 'Waiting:' + last, 'waiting'), p.n);
}

const hasC = spec.paths.some(p => p.country);
const off = hasC ? 1 : 0;
const col = {};
for (const n of nodes.values()) {
  if (n.kind === 'country') col[n.id] = 0;
  else if (n.kind === 'carry') col[n.id] = 1;
  else if (n.kind === 'stage' && ORDER.includes(n.name)) col[n.id] = ORDER.indexOf(n.name) + off + (n.name==='Research'?0:0);
}
// 16 Nov 2026: a path that starts on a side status or a dead end (no arrows in) sits in its home column
const HOME = {'No Apollo':'GATE1','Contact exists':'Located','Missing Info':'Located'};
// (arrows from "Carried over" or a country do not count: those start there too)
const hasIn = new Set([...links.keys()].filter(k => k.startsWith('s:')).map(k => k.split('>')[1]));
for (const n of nodes.values()) {
  if (col[n.id] === undefined && n.kind === 'stage' && !hasIn.has(n.id))
    col[n.id] = ORDER.indexOf(HOME[n.name] || 'In Progress') + off;
}
// exits and waiting: one column after their furthest source
let changed = true;
while (changed) { changed = false;
  for (const [k] of links) { const [s2, t] = k.split('>');
    if (col[t] === undefined && col[s2] !== undefined) {
      const srcs = [...links.keys()].filter(x => x.endsWith('>' + t)).map(x => col[x.split('>')[0]]);
      if (srcs.every(v => v !== undefined)) { col[t] = Math.max(...srcs) + 1; changed = true; }
    } } }
const minCol = Math.min(...Object.values(col));
const nCols = Math.max(...Object.values(col)) - minCol + 1;
// 16 Nov 2026: d3-sankey has as many columns as the longest chain of arrows, so a short day squeezed the
// last columns together. An invisible chain through every column keeps each stage in its own column.
for (let i = 0; i < nCols; i++) {
  node('d:' + i, '', 'dummy'); col['d:' + i] = i + minCol;
  if (i) link('d:' + (i - 1), 'd:' + i, 1e-6);
}
const rank = n => n.kind==='dummy'?99 : n.kind==='country'?0 : ORDER.includes(n.name)&&n.name!=='END Sales'?0 : n.name==='END Sales'?1 : n.kind==='waiting'?2 : n.kind==='carry'?3 : ['Missing Info','No Apollo','Contact exists'].includes(n.name)?4 : n.name.startsWith('Back')||n.name.startsWith('Reopened')?5 : 6;
const W = 40 + (nCols - 1) * (spec.colGap || 190) + 200;
const graphIn = {
  nodes: [...nodes.values()].map(d => ({ ...d })),
  links: [...links].map(([k, v]) => { const [source, target] = k.split('>'); return { source, target, value: v }; })
};
// height: based on busiest column
const tmp = sankey().nodeId(d => d.id).nodeAlign(n => col[n.id] - minCol)({ nodes: graphIn.nodes.map(d => ({ ...d })), links: graphIn.links.map(d => ({ ...d })) });
const perCol = {}; tmp.nodes.forEach(n => perCol[n.depth] = (perCol[n.depth] || 0) + 1);
const maxCol = Math.max(...Object.values(perCol));
const TOP = 100, H = Math.max(400, TOP + maxCol * 78 + 40);
const RIGHT = 190;

const g = sankey().nodeId(d => d.id).nodeAlign(n => col[n.id] - minCol).nodeWidth(12).nodePadding(60)
  .nodeSort((a, b) => rank(a) - rank(b)).iterations(0).extent([[24, TOP], [W - RIGHT, H - 30]])(graphIn);

const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<rect width="100%" height="100%" fill="#ffffff"/>
<style>text{font-family:'DejaVu Sans',Arial,sans-serif}</style>
<text x="24" y="38" font-size="22" font-weight="bold" fill="#1a1a19">${esc(spec.title)}</text>
<text x="24" y="66" font-size="15" fill="#5F5E5A">${esc(spec.subtitle)}</text>\n`;

const path = sankeyLinkHorizontal();
for (const l of g.links) {
  if (l.source.kind === 'dummy') continue;
  svg += `<path d="${path(l)}" fill="none" stroke="${colour(l.target.name, l.target.kind)}" stroke-opacity="0.32" stroke-width="${Math.max(2, l.width)}"/>\n`;
}
for (const n of g.nodes) {
  if (n.kind === 'dummy') continue;
  const h = Math.max(3, n.y1 - n.y0);
  svg += `<rect x="${n.x0}" y="${n.y0}" width="${n.x1 - n.x0}" height="${h}" rx="2" fill="${colour(n.name, n.kind)}"/>\n`;
}
for (const n of g.nodes) {
  if (n.kind === 'dummy') continue;
  const inflow = n.targetLinks.reduce((a, l) => a + l.value, 0);
  const shown = inflow || n.value;
  let pct = '';
  const stageLinks = n.targetLinks.filter(l => l.source.kind === 'stage');
  if (stageLinks.length) {
    const num = stageLinks.reduce((a, l) => a + l.value, 0);
    const den = [...new Set(stageLinks.map(l => l.source))].reduce((a, s) => a + s.value, 0);
    pct = ` (${Math.round(100 * num / den)}%)`;
  }
  const y = (n.y0 + n.y1) / 2;
  const halo = 'stroke="#ffffff" stroke-width="5" paint-order="stroke" stroke-linejoin="round"';
  const lab = (n.kind === 'waiting' ? (WAIT[n.name.slice(8)] || 'Still at this step') : (LABEL[n.name] || n.name)).split('\n');
  const y0 = y - 9.5 * lab.length;
  lab.forEach((t, i) => { svg += `<text x="${n.x1 + 7}" y="${y0 + i * 19}" dominant-baseline="central" font-size="16" fill="#1a1a19" ${halo}>${esc(t)}</text>\n`; });
  svg += `<text x="${n.x1 + 7}" y="${y0 + lab.length * 19}" dominant-baseline="central" font-size="16" fill="#1a1a19" ${halo}><tspan font-weight="bold">${shown}</tspan><tspan fill="#5F5E5A">${pct}</tspan></text>
`;
}
svg += '</svg>';

fs.writeFileSync(process.argv[3].replace(/\.png$/, '.svg'), svg);
const png = new Resvg(svg, { fitTo: { mode: 'zoom', value: 2 }, font: { loadSystemFonts: true, defaultFontFamily: 'DejaVu Sans' } }).render().asPng();
fs.writeFileSync(process.argv[3], png);
console.log('ok', W, H);
