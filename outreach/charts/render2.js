// Outcome-first month Sankey. Input: {title, subtitle, nodes:{id:[label,colour,col]}, links:[[s,t,v]]}
const fs=require('fs');const {sankey,sankeyLinkHorizontal}=require('d3-sankey');const {Resvg}=require('@resvg/resvg-js');
const spec=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const nodes=Object.entries(spec.nodes).map(([id,[name,c,col]])=>({id,name,c,col}));
const links=spec.links.map(([source,target,value])=>({source,target,value}));
const perCol={};nodes.forEach(n=>perCol[n.col]=(perCol[n.col]||0)+1);
const maxCol=Math.max(...Object.values(perCol)),nCols=Math.max(...nodes.map(n=>n.col))+1;
const GAP=330,W=40+(nCols-1)*GAP+330,TOP=100,H=TOP+maxCol*(spec.pad?spec.pad+30:62)+40;
const g=sankey().nodeId(d=>d.id).nodeAlign(n=>n.col).nodeWidth(12).nodePadding(spec.pad||44).nodeSort(null).iterations(0)
 .extent([[24,TOP],[W-330,H-30]])({nodes,links});
function arrow(n,v){ const p=(spec.prev||{})[n.id]; if(v===null||p===undefined) return '';
 const bad=n.c==='#D85A30'||n.c==='#E8826A';
 if(v===p) return ` <tspan fill="#888780">= ${p}%</tspan>`;
 const up=v>p, good=bad?!up:up;
 return ` <tspan fill="${good?'#0F6E56':'#C0392B'}" font-weight="bold">${up?'\u25B2':'\u25BC'}</tspan><tspan fill="#888780" font-size="13"> was ${p}%</tspan>`; }
const esc=s=>String(s).replace(/&/g,'&amp;');
let svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><rect width="100%" height="100%" fill="#fff"/>
<text x="24" y="38" font-family="DejaVu Sans" font-size="22" font-weight="bold" fill="#1a1a19">${esc(spec.title)}</text>
<text x="24" y="66" font-family="DejaVu Sans" font-size="15" fill="#5F5E5A">${esc(spec.subtitle)}</text>\n`;
const p=sankeyLinkHorizontal();
for(const l of g.links)svg+=`<path d="${p(l)}" fill="none" stroke="${l.target.c}" stroke-opacity="0.3" stroke-width="${Math.max(2,l.width)}"/>\n`;
const halo='stroke="#fff" stroke-width="5" paint-order="stroke" stroke-linejoin="round"';
for(const n of g.nodes){
 svg+=`<rect x="${n.x0}" y="${n.y0}" width="12" height="${Math.max(3,n.y1-n.y0)}" rx="2" fill="${n.c}"/>\n`;
 const par=n.targetLinks.length===1&&n.targetLinks[0].source.col>0?n.targetLinks[0].source:null;
 const pctNum=n.col===1?Math.round(100*n.value/spec.total):par?Math.round(100*n.value/par.value):null;
 const pct=n.col===1?` (${Math.round(100*n.value/spec.total)}%)`:par?` (${Math.round(100*n.value/par.value)}%)`:'';
 const lines=n.name.split('\n'),y=(n.y0+n.y1)/2,y0=y-9.5*lines.length;
 lines.forEach((t,i)=>svg+=`<text x="${n.x1+7}" y="${y0+i*19}" dominant-baseline="central" font-family="DejaVu Sans" font-size="16" fill="#1a1a19" ${halo}>${esc(t)}</text>\n`);
 svg+=`<text x="${n.x1+7}" y="${y0+lines.length*19}" dominant-baseline="central" font-family="DejaVu Sans" font-size="16" fill="#1a1a19" ${halo}><tspan font-weight="bold">${n.value}</tspan><tspan fill="#5F5E5A">${pct}</tspan>${arrow(n,pctNum)}</text>\n`;}
svg+='</svg>';
fs.writeFileSync(process.argv[3],new Resvg(svg,{fitTo:{mode:'zoom',value:2},font:{loadSystemFonts:true,defaultFontFamily:'DejaVu Sans'}}).render().asPng());console.log('ok',W,H);
