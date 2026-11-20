/* ===== results dashboard: shared by every HQ site; RSTATS and FAVKEY are set per site ===== */
let HIST = null, HPL = null, HW = "7", HG = "T10", HV = "trend", HD = null, HDAY = {}, HSORT = "picks", RS = null;
const GROUPS = [["T10","Top 10"],["ELITE","Elite"],["STRONG","Strong"],["SOLID","Solid"],["FRINGE","Fringe"],["LONGSHOT","Longshot"]];
const TIERCOL = { ELITE:"var(--elite)", STRONG:"var(--strong)", SOLID:"var(--solid)", FRINGE:"var(--fringe)", LONGSHOT:"var(--long)" };

function favSet(){ try{ return new Set(JSON.parse(localStorage.getItem(FAVKEY) || "[]").map(String)); }catch(e){ return new Set(); } }
function toggleFav(id){
  const s = favSet(); id = String(id);
  if(s.has(id)) s.delete(id); else s.add(id);
  try{ localStorage.setItem(FAVKEY, JSON.stringify([...s])); }catch(e){}
}
function starHTML(id, name){
  return '<button class="star'+(favSet().has(String(id))?" on":"")+'" data-fav="'+esc(String(id))+'" aria-label="Star '+esc(name)+'">★</button>';
}

function rstat(){
  if(!RS) RS = RSTATS.some(x=>x[0]===F.stat) ? F.stat : RSTATS[0][0];
  return RS;
}
function rlabel(){ return RSTATS.find(x=>x[0]===rstat())[1]; }
function fmtDay(d){
  if(/-w\d+$/.test(d)) return "Week " + (+d.split("-w")[1]);
  return new Date(d+"T12:00:00").toLocaleDateString([], { weekday:"short", month:"short", day:"numeric" });
}
function fmtNum(v){ return Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : (v >= 10 ? v.toFixed(1) : v.toFixed(2).replace(/0$/, "")); }
function pct0(h, n){ return n ? Math.round(100*h/n)+"%" : "—"; }
function rangeDays(){
  if(!HIST) return [];
  if(HW === "season") return HIST.daily;
  if(HIST.weekly) return HIST.daily.slice(0, HW === "7" ? 1 : 4);
  const last = new Date(HIST.last+"T12:00:00");
  last.setDate(last.getDate() - (+HW - 1));
  const since = last.toISOString().slice(0,10);
  return HIST.daily.filter(d=>d.date >= since);
}
function groupOf(d){
  const s = d.stats[rstat()];
  if(!s) return [0,0,0];
  return HG === "T10" ? s.t10 : (s.tiers[HG] || [0,0,0]);
}
function groupColor(){ return HG === "T10" ? "var(--red)" : TIERCOL[HG]; }
function sumGroup(days){
  const t = [0,0,0];
  for(const d of days){ const g = groupOf(d); t[0]+=g[0]; t[1]+=g[1]; t[2]+=g[2]; }
  return t;
}
function slateWord(){ return HIST && HIST.weekly ? "weeks" : "nights"; }

function kpisHTML(days){
  const t = sumGroup(days), last = days[0], lg = last ? groupOf(last) : [0,0,0];
  let best = null;
  for(const d of days){ const g = groupOf(d); if(g[0] >= 3 && (!best || g[1]/g[0] > best.r)) best = { d, r:g[1]/g[0], g }; }
  const tile = (k, v, sub)=>'<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="s">'+sub+'</div></div>';
  const one = HIST.weekly ? "week" : "night";
  return '<div class="kpis">'
    + tile("Over rate", pct0(t[1], t[0]), "model expected "+pct0(t[2], t[0]))
    + tile("Picks graded", t[0], days.length+" "+slateWord())
    + tile("Last "+one, lg[0] ? lg[1]+" of "+lg[0]+" over" : "—", last ? fmtDay(last.date) : "")
    + tile("Best "+one, best ? best.g[1]+" of "+best.g[0]+" over" : "—", best ? fmtDay(best.d.date) : "needs 3+ picks")
    + '</div>';
}

function trendSVG(days){
  const list = days.slice().reverse().filter(d=>groupOf(d)[0] > 0);
  if(!list.length) return '<div class="dash-empty">No picks in this group for this range.</div>';
  const W = 360, H = 170, L = 30, R = 6, T = 10, B = 22, iw = W-L-R, ih = H-T-B;
  const bw = iw / list.length, gap = Math.min(4, bw*0.25);
  let g = '';
  for(const v of [0, 0.25, 0.5, 0.75, 1]){
    const y = T + ih*(1-v);
    g += '<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y+'" y2="'+y+'" class="grid"/><text x="'+(L-6)+'" y="'+(y+3.5)+'" class="ax" text-anchor="end">'+Math.round(v*100)+'%</text>';
  }
  let bars = '', pts = [];
  list.forEach((d,i)=>{
    const gp = groupOf(d), r = gp[1]/gp[0], e = gp[2]/gp[0];
    const x = L + i*bw + gap/2, h = Math.max(2, ih*r), y = T + ih - h;
    const on = HD === d.date;
    bars += '<g class="tbar" data-day="'+d.date+'"><rect x="'+(L+i*bw)+'" y="'+T+'" width="'+bw+'" height="'+ih+'" fill="transparent"/>'
      + '<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+(bw-gap).toFixed(1)+'" height="'+h.toFixed(1)+'" rx="2" fill="'+groupColor()+'" opacity="'+(HD && !on ? .45 : 1)+'"><title>'+fmtDay(d.date)+': '+gp[1]+' of '+gp[0]+' over</title></rect></g>';
    pts.push((L + i*bw + bw/2).toFixed(1)+","+(T + ih*(1-e)).toFixed(1));
  });
  const lab = d=> HIST.weekly ? "Wk "+(+d.split("-w")[1]) : new Date(d+"T12:00:00").toLocaleDateString([], {month:"short", day:"numeric"});
  const ticks = [0, Math.floor((list.length-1)/2), list.length-1].filter((v,i,a)=>a.indexOf(v)===i)
    .map(i=>'<text x="'+(i===0 ? L : i===list.length-1 ? W-R : L + i*bw + bw/2)+'" y="'+(H-6)+'" class="ax" text-anchor="'+(i===0 ? "start" : i===list.length-1 ? "end" : "middle")+'">'+lab(list[i].date)+'</text>').join("");
  return '<svg viewBox="0 0 '+W+' '+H+'" class="chart" role="img" aria-label="Over rate by '+(HIST.weekly?"week":"night")+'">'+g+bars
    + (pts.length > 1 ? '<polyline points="'+pts.join(" ")+'" class="expline"/>' : '')+ticks+'</svg>'
    + '<div class="legend-row"><span><i style="background:'+groupColor()+'"></i>Over rate</span><span><i class="dash"></i>Model expected</span><span class="tip">Tap a bar to open it</span></div>';
}

function tiersHTML(days){
  let h = '<div class="tr-tiers">';
  for(const t of ["ELITE","STRONG","SOLID","FRINGE","LONGSHOT"]){
    const v = [0,0,0];
    for(const d of days){ const s = d.stats[rstat()], g = s && s.tiers[t]; if(g){ v[0]+=g[0]; v[1]+=g[1]; v[2]+=g[2]; } }
    if(!v[0]){ h += '<div class="tr-row"><div class="tr-name" style="color:'+TIERCOL[t]+'">'+t+'</div><div></div><div class="tr-num">no picks</div></div>'; continue; }
    h += '<div class="tr-row'+(HG===t?' on':'')+'" data-group="'+t+'"><div class="tr-name" style="color:'+TIERCOL[t]+'">'+t+'</div>'
      + '<div class="tr-bar"><i style="width:'+(100*v[1]/v[0]).toFixed(1)+'%;background:'+TIERCOL[t]+'"></i><em style="left:'+(100*v[2]/v[0]).toFixed(1)+'%"></em></div>'
      + '<div class="tr-num"><b>'+pct0(v[1],v[0])+'</b>'+v[1]+' of '+v[0]+'</div></div>';
  }
  return h + '</div><div class="legend-row"><span><i class="dash v"></i>Model expected</span><span class="tip">Tap a tier to focus on it</span></div>';
}

function donutSVG(days){
  const t = sumGroup(days);
  if(!t[0]) return '<div class="dash-empty">No picks in this group for this range.</div>';
  const r = 58, c = 2*Math.PI*r, hit = t[1]/t[0];
  return '<div class="donut"><svg viewBox="0 0 160 160" role="img" aria-label="Overs and unders">'
    + '<circle cx="80" cy="80" r="'+r+'" fill="none" stroke="rgba(255,255,255,.09)" stroke-width="18"/>'
    + '<circle cx="80" cy="80" r="'+r+'" fill="none" stroke="'+groupColor()+'" stroke-width="18" stroke-dasharray="'+(c*hit).toFixed(1)+' '+c.toFixed(1)+'" transform="rotate(-90 80 80)"/>'
    + '<text x="80" y="80" text-anchor="middle" class="dv">'+pct0(t[1],t[0])+'</text><text x="80" y="100" text-anchor="middle" class="ax">over</text></svg>'
    + '<div class="dlist"><div><i style="background:'+groupColor()+'"></i>Over<b>'+t[1]+'</b></div><div><i style="background:rgba(255,255,255,.18)"></i>Under<b>'+(t[0]-t[1])+'</b></div><div class="mute">Model expected<b>'+Math.round(t[2])+' over</b></div></div></div>';
}

function pickRow(sc, name, team, a, pj, over){
  return '<div class="tr-pick"><span class="sc">'+sc+'</span><span class="n">'+esc(name)+'<small>'+esc(team)+'</small></span>'
    + '<span class="ln">'+fmtNum(a)+' <small>vs '+fmtNum(pj)+'</small></span><span class="ou '+(over?"over":"under")+'">'+(over?"OVER":"UNDER")+'</span></div>';
}
function drillHTML(){
  if(!HD) return '';
  const day = HDAY[HD], st = rstat();
  let h = '<div class="drill"><div class="drill-head"><b>'+fmtDay(HD)+'</b><button class="navbtn" id="drill-x" aria-label="Close">✕</button></div>';
  if(!day) return h + '<div class="dash-empty">Loading…</div></div>';
  let rows = day.rows.filter(r=>r.pj[st] && r.act[st] != null).sort((a,b)=>b.s[st]-a.s[st]);
  rows = HG === "T10" ? rows.slice(0,10) : rows.filter(r=>tierOf(r.s[st])===HG);
  const overs = rows.filter(r=>r.act[st] >= r.pj[st] - 1e-9).length;
  h += '<div class="drill-sub">'+GROUPS.find(g=>g[0]===HG)[1]+' · '+overs+' of '+rows.length+' over · actual vs our projection</div>';
  h += rows.map(r=>pickRow(r.s[st], r.n, r.t, r.act[st], r.pj[st], r.act[st] >= r.pj[st] - 1e-9)).join("");
  return h + '</div>';
}

function playersHTML(){
  const list = ((HIST.players||{})[rstat()]||{})[HW] || [];
  if(!list.length) return '';
  const rows = list.slice().sort((a,b)=> HSORT==="rate" ? (b.hits/b.picks - a.hits/a.picks) : HSORT==="hits" ? b.hits-a.hits : b.picks-a.picks);
  const th = (k, l)=>'<th data-sort="'+k+'" class="'+(HSORT===k?"on":"")+'">'+l+(HSORT===k?" ▾":"")+'</th>';
  return '<h3 class="dash-h">Most-backed players</h3><p class="dash-note">Who made our top 10 most often, and how often he went over.</p>'
    + '<table class="ptable"><thead><tr><th>Player</th>'+th("picks","Picks")+th("hits","Over")+th("rate","Rate")+'</tr></thead><tbody>'
    + rows.map(p=>'<tr><td>'+esc(p.n)+' <small>'+esc(p.t)+'</small></td><td>'+p.picks+'</td><td>'+p.hits+'</td><td>'+pct0(p.hits,p.picks)+'</td></tr>').join("")
    + '</tbody></table>';
}

function favsHTML(){
  const fav = [...favSet()];
  const st = rstat();
  let h = '<h3 class="dash-h">Your players</h3>';
  if(!fav.length) return h + '<p class="dash-note">Tap ★ next to a player on the board to follow him here.</p>';
  if(!HPL) return h + '<p class="dash-note">Loading your players…</p>';
  const rows = fav.map(id=>HPL[id] && Object.assign({ id }, HPL[id])).filter(Boolean);
  if(!rows.length) return h + '<p class="dash-note">None of your starred players have a graded game yet.</p>';
  return h + '<p class="dash-note">'+rlabel()+' this season, and his last five.</p>' + rows.map(p=>{
    const t = p.s[st], last = p.l[st] || [];
    return '<div class="favcard"><div class="fc-top"><span class="n">'+esc(p.n)+'<small>'+esc(p.t)+'</small></span>'
      + '<span class="fc-rate">'+(t ? '<b>'+pct0(t[1], t[0])+'</b> over · '+t[1]+' of '+t[0] : 'no '+rlabel().toLowerCase()+' picks')+'</span></div>'
      + (last.length ? '<div class="fc-last">'+last.map(x=>'<span class="'+(x[3]?"o":"u")+'" title="'+fmtDay(x[0])+'"><b>'+(x[3]?"O":"U")+'</b>'+fmtNum(x[1])+' <small>vs '+fmtNum(x[2])+'</small></span>').join("")+'</div>' : '')
      + '</div>';
  }).join("");
}

function nightsHTML(days){
  const one = HIST.weekly ? "Week" : "Night";
  return '<h3 class="dash-h">'+(HIST.weekly?"Weeks":"Nights")+'</h3><table class="ptable nights"><thead><tr><th>'+one+'</th><th>Games</th><th>Over</th><th>Rate</th></tr></thead><tbody>'
    + days.map(d=>{ const g = groupOf(d); return '<tr data-day="'+d.date+'" class="'+(HD===d.date?"on":"")+'"><td>'+fmtDay(d.date)+'</td><td>'+d.games+'</td><td>'+(g[0] ? g[1]+" / "+g[0] : "—")+'</td><td>'+pct0(g[1],g[0])+'</td></tr>'; }).join("")
    + '</tbody></table>';
}

function rangeText(days){
  if(!days.length) return "No graded "+slateWord()+" in this range yet.";
  const a = days[days.length-1].date, b = days[0].date;
  const span = a === b ? fmtDay(a) : fmtDay(a)+" to "+fmtDay(b);
  return "Showing "+span+" ("+days.length+" "+(days.length === 1 ? slateWord().slice(0,-1) : slateWord())+").";
}
function resultsHTML(){
  const tabs = '<div class="rtabs">'+RSTATS.map(x=>'<button class="'+(rstat()===x[0]?"on":"")+'" data-rstat="'+x[0]+'">'+x[1]+'</button>').join("")+'</div>';
  if(!HIST) return tabs + '<div class="status"><div class="spinner"></div><h2>Loading results</h2></div>';
  if(HIST.error) return tabs + '<div class="status"><h2>No results yet</h2><p>The first graded '+(HIST.weekly?"week":"night")+' shows up here the morning after.</p></div>';
  const days = rangeDays();
  let h = '<p class="tr-intro">Every pick is graded after the game. <b>Over</b> means his actual '+RSTATS.find(x=>x[0]===rstat())[2]+' reached our projection, <b>Under</b> means it fell short. '+rangeText(days)+'</p>';
  h += tabs;
  h += '<div class="dash-filters">'
    + '<div class="ctrl"><label>Range</label><select id="d-range">'+(HIST.weekly ? [["7","Last week"],["30","Last 4 weeks"],["season","Season"]] : [["7","Last 7 days"],["30","Last 30 days"],["season","Season"]]).map(o=>'<option value="'+o[0]+'"'+(HW===o[0]?" selected":"")+'>'+o[1]+'</option>').join("")+'</select></div>'
    + '<div class="ctrl"><label>Picks</label><select id="d-group">'+GROUPS.map(o=>'<option value="'+o[0]+'"'+(HG===o[0]?" selected":"")+'>'+o[1]+'</option>').join("")+'</select></div>'
    + '</div>';
  h += kpisHTML(days);
  h += '<div class="dash-card"><div class="seg">'+[["trend","Trend"],["tiers","By tier"],["donut","Over / under"]].map(v=>'<button class="'+(HV===v[0]?"on":"")+'" data-view="'+v[0]+'">'+v[1]+'</button>').join("")+'</div>'
    + (HV==="trend" ? trendSVG(days) : HV==="tiers" ? tiersHTML(days) : donutSVG(days)) + '</div>';
  h += drillHTML();
  h += favsHTML();
  h += playersHTML();
  h += nightsHTML(days);
  return h;
}

async function loadHistory(){
  if(!HIST){
    try{ HIST = await fetchJSON("/history"); if(!HIST || !HIST.daily) HIST = { error:true }; }catch(e){ HIST = { error:true }; }
    if(F.view === "results") render();
  }
  if(!HPL && favSet().size && !HIST.error){
    try{ HPL = await fetchJSON("/history/players"); }catch(e){ HPL = {}; }
    if(F.view === "results") render();
  }
}
// the board and the dashboard share one page: the phone's back gesture and the logo both return to the board
function openResults(){
  if(F.view !== "results"){ F.view = "results"; try{ history.pushState({ hq:"results" }, ""); }catch(e){} }
  window.scrollTo(0,0); render();
}
function closeResults(){
  if(F.view !== "results") return;
  F.view = "board";
  window.scrollTo(0,0);
  if(!GAMES.length) boot(false); else render();
}
window.addEventListener("popstate", ()=> closeResults());
async function openDay(d){
  HD = HD === d ? null : d;
  render();
  if(HD && !HDAY[HD]){
    try{ HDAY[HD] = await fetchJSON("/history/day?d="+HD); }catch(e){ HDAY[HD] = { rows:[], games:0 }; }
    if(HD === d) render();
  }
  const el = document.querySelector(".drill"); if(el) el.scrollIntoView({ block:"nearest" });
}
function wireResults(){
  const rg = document.getElementById("d-range"); if(rg) rg.onchange = e=>{ HW = e.target.value; HD = null; render(); };
  const gp = document.getElementById("d-group"); if(gp) gp.onchange = e=>{ HG = e.target.value; render(); };
  document.querySelectorAll("[data-rstat]").forEach(el=> el.onclick = ()=>{ RS = el.dataset.rstat; render(); });
  document.querySelectorAll("[data-view]").forEach(el=> el.onclick = ()=>{ HV = el.dataset.view; render(); });
  document.querySelectorAll("[data-day]").forEach(el=> el.onclick = ()=> openDay(el.dataset.day));
  document.querySelectorAll(".tr-row[data-group]").forEach(el=> el.onclick = ()=>{ HG = el.dataset.group; HV = "trend"; render(); });
  document.querySelectorAll("th[data-sort]").forEach(el=> el.onclick = ()=>{ HSORT = el.dataset.sort; render(); });
  const x = document.getElementById("drill-x"); if(x) x.onclick = ()=>{ HD = null; render(); };
}
function wireBrand(){
  fitBrand();
  const b = document.querySelector(".brand");
  if(b){ b.style.cursor = "pointer"; b.onclick = ()=>{ if(F.view === "results") history.back(); }; }
}
function wireStars(){
  document.querySelectorAll(".star").forEach(el=> el.onclick = (e)=>{ e.stopPropagation(); toggleFav(el.dataset.fav); render(); });
  fitBrand();
  setTimeout(fitBrand, 250);
}
// size the site name to fill the room left of the buttons, so every site's header lines up the same way
function fitBrand(){
  const b = document.querySelector("header.hero .brand");
  if(!b) return;
  const bar = b.closest(".topbar"), btns = bar && bar.lastElementChild;
  if(!btns || btns === b.parentNode) return;
  const room = bar.clientWidth - btns.offsetWidth - 14;
  b.style.setProperty("font-size", "40px", "important");
  const r = document.createRange();
  r.selectNodeContents(b);
  const w = r.getBoundingClientRect().width;
  if(room > 0 && w > 0) b.style.setProperty("font-size", Math.max(18, Math.min(48, 40 * room / w)).toFixed(1) + "px", "important");
}
window.addEventListener("resize", ()=> fitBrand());
if(document.fonts){
  document.fonts.ready.then(()=> fitBrand());
  document.fonts.addEventListener("loadingdone", ()=> fitBrand());
}
/* ===== end results dashboard ===== */
