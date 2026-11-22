/* ===== games view: shared by every HQ site; gList, gRows, GKIND are set per site ===== */
let GV = false, GOPEN = {}, GQ = null, GJUMP = null;
// arriving from Total HQ with ?game=<home team or match id> opens the Games tab on that game
try { GQ = new URLSearchParams(location.search).get("game"); if(GQ) GV = true; } catch(e) {}
function gPct(x){ return x == null ? "—" : Math.round(100*x)+"%"; }
function gLine(x){ return x > 0 ? "+"+x : x === 0 ? "PK" : String(x); }
function gSide(g, home){ return home ? g.home : g.away; }

function gWinBar(g){
  const w = g.proj.win;
  if(w.length === 3)   // soccer reads home first: home, draw, away
    return '<div class="gw-bar"><i class="gw-h" style="flex:'+w[0]+'"></i><i class="gw-d" style="flex:'+w[1]+'"></i><i class="gw-a" style="flex:'+w[2]+'"></i></div>'
      + '<div class="gw-lbl"><span>'+esc(g.home)+' <b>'+gPct(w[0])+'</b></span><span>Draw <b>'+gPct(w[1])+'</b></span><span><b>'+gPct(w[2])+'</b> '+esc(g.away)+'</span></div>';
  return '<div class="gw-bar"><i class="gw-a" style="flex:'+w[1]+'"></i><i class="gw-h" style="flex:'+w[0]+'"></i></div>'
    + '<div class="gw-lbl"><span>'+esc(g.away)+' <b>'+gPct(w[1])+'</b></span><span><b>'+gPct(w[0])+'</b> '+esc(g.home)+'</span></div>';
}

function gPrice(x){ return x == null ? "" : (x > 0 ? "+"+x : String(x)); }
function gEdge(g, mk, side){
  const v = (g.proj.value||[]).find(v=>v.mk===mk && v.side===side);
  return v ? ' <span class="g-val">+'+Math.round(100*(v.ours-v.book))+'%</span>' : '';
}
// one market: a row per side with our chance, the book's fair chance, and the best price out there
function gTable(title, sides){
  return '<div class="gm-t">'+title+'</div><div class="gm-tbl"><div class="gm-h"><span></span><span>Ours</span><span>Book</span><span>Best price</span></div>'
    + sides.map(x=>'<div class="gm-r"><span>'+x[0]+'</span><span><b>'+gPct(x[1])+'</b></span><span>'+gPct(x[2])+'</span><span>'+(x[3] ? gPrice(x[3][0])+' <em>'+x[3][1]+'</em>' : '—')+'</span></div>').join("")
    + '</div>';
}
function gMarkets(g){
  const p = g.proj, w = p.win, b = p.book && !p.book.src ? p.book : null, out = [];
  const H = esc(g.home), A = esc(g.away);
  if(GKIND === "soccer"){
    out.push(gTable("Result", [[H+gEdge(g,"Result",g.home), w[0], b&&b.ml&&b.ml[0], b&&b.mlp&&b.mlp[0]],
      ["Draw"+gEdge(g,"Result","Draw"), w[1], b&&b.ml&&b.ml[1], b&&b.mlp&&b.mlp[1]],
      [A+gEdge(g,"Result",g.away), w[2], b&&b.ml&&b.ml[2], b&&b.mlp&&b.mlp[2]]]));
    const ov = p.over_book != null ? p.over_book : p.over[1];
    out.push(gTable("Total goals 2.5", [["Over"+gEdge(g,"Total","Over 2.5"), ov, b&&b.over, b&&b.totp&&b.totp[0]],
      ["Under"+gEdge(g,"Total","Under 2.5"), 1-ov, b&&b.over!=null?1-b.over:null, b&&b.totp&&b.totp[1]]]));
    out.push(gTable("Both teams score", [["Yes"+gEdge(g,"Both score","Yes"), p.btts, b&&b.btts, b&&b.bttsp&&b.bttsp[0]],
      ["No"+gEdge(g,"Both score","No"), 1-p.btts, b&&b.btts!=null?1-b.btts:null, b&&b.bttsp&&b.bttsp[1]]]));
    return out;
  }
  out.push(gTable("Moneyline", [[A+gEdge(g,"Moneyline",g.away), w[1], b&&b.ml&&b.ml[1], b&&b.mlp&&b.mlp[1]],
    [H+gEdge(g,"Moneyline",g.home), w[0], b&&b.ml&&b.ml[0], b&&b.mlp&&b.mlp[0]]]));
  if(b && b.spread != null){
    const l = b.spread, hs = g.home+" "+(l>0?"+":"")+l, as = g.away+" "+(-l>0?"+":"")+(-l);
    out.push(gTable((GKIND==="hockey"?"Puck line":"Spread")+' <i>ours '+H+' '+gLine(p.spread)+'</i>',
      [[esc(as)+gEdge(g,"Spread",as), 1-p.cover_book, 1-b.cover, b.spreadp&&b.spreadp[1]],
       [esc(hs)+gEdge(g,"Spread",hs), p.cover_book, b.cover, b.spreadp&&b.spreadp[0]]]));
  } else {
    out.push('<div class="gm-t">'+(GKIND==="hockey"?"Puck line":"Spread")+' <i>ours '+H+' '+gLine(p.spread)+(p.book&&p.book.spread!=null?' · consensus '+gLine(p.book.spread):'')+'</i></div>');
  }
  if(b && b.total != null){
    const t = b.total;
    out.push(gTable('Total '+t+' <i>ours '+p.total+'</i>', [["Over"+gEdge(g,"Total","Over "+t), p.over_book, b.over, b.totp&&b.totp[0]],
      ["Under"+gEdge(g,"Total","Under "+t), 1-p.over_book, 1-b.over, b.totp&&b.totp[1]]]));
  } else {
    out.push('<div class="gm-t">Total <i>ours '+p.total+(p.book&&p.book.total!=null?' · consensus '+p.book.total:'')+'</i></div>');
  }
  return out;
}

function gCard(g){
  const p = g.proj, open = !!GOPEN[g.id];
  const score = p.hs.toFixed(1)+' – '+p.as.toFixed(1);
  let h = '<div class="gcard'+(open?" open":"")+'" data-gid="'+esc(g.id)+'">'
    + '<div class="gc-top"><div class="gc-teams">'+(GKIND === "soccer" ? esc(g.home)+' <span>v</span> '+esc(g.away) : esc(g.away)+' <span>@</span> '+esc(g.home))+'</div><div class="gc-when">'+esc(g.when||"")+'</div></div>'
    + (g.lg ? '<div class="gc-lg">'+esc(g.lg)+'</div>' : '')
    + gWinBar(g)
    + '<div class="gc-proj">Projected <b>'+esc(g.home)+' '+score+' '+esc(g.away)+'</b>'
    + ((p.value||[]).length ? '<span class="g-val">'+p.value.length+' edge'+(p.value.length>1?"s":"")+'</span>' : '')+'</div>';
  if(open){
    h += '<div class="gc-mk">'+gMarkets(g).join("")
      + (p.book && !p.book.src ? '<p class="gm-note">Book = the sportsbooks\' fair chance with their margin removed. Best price = the best odds across DraftKings, FanDuel, BetMGM, Caesars and others. A green tag means we rate that side higher than the books do.</p>' : '')
      + '</div>';
    const rows = gRows(g.id).slice(0, 3);
    if(rows.length){
      h += '<div class="gc-sub">Top picks in this game</div>' + rows.map((r,i)=>rowHTML(r,i)).join("")
        + '<button class="navbtn gc-all" data-all="'+esc(g.id)+'">Full board for this game</button>';
    }
  }
  return h + '</div>';
}

function gamesHTML(){
  const list = gList().filter(g=>g.proj);
  if(GQ){ const hit = list.find(g=>g.home===GQ || String(g.id)===GQ); if(hit){ GOPEN[hit.id] = true; GJUMP = hit.id; } GQ = null; }
  if(!list.length) return '<div class="status"><h2>No game projections yet</h2><p>They appear once today\'s teams have played enough to rate.</p></div>';
  return '<p class="g-intro">Every game, projected by the same model as the board. Tap a game for its markets and the best player picks in it.</p>'
    + list.map(gCard).join("");
}

function wireGames(){
  document.querySelectorAll(".gcard").forEach(el=> el.onclick = (e)=>{
    if(e.target.closest(".row, .gc-all")) return;
    GOPEN[el.dataset.gid] = !GOPEN[el.dataset.gid]; render();
  });
  document.querySelectorAll(".gc-all").forEach(b=> b.onclick = ()=>{ GV = false; F.game = b.dataset.all; render(); scrollTo(0, 0); });
  if(typeof wireStars === "function") wireStars();
  if(GJUMP){ const el = document.querySelector('.gcard[data-gid="'+GJUMP+'"]'); GJUMP = null; if(el) el.scrollIntoView({ block:"start" }); }
}
// ---------- book prices on player rows ----------
const PONE = { G:1, A:1, P:1, GA:1, TD:1, BLK:1, STL:1, "3PM":2 };           // tabs shown as a chance of at least this many
const PSD = { PTS:x=>1.35*Math.sqrt(x), REB:x=>1.25*Math.sqrt(x), AST:x=>1.3*Math.sqrt(x), PRA:x=>1.4*Math.sqrt(x),
              CYD:x=>0.55*x+8, RYD:x=>0.55*x+8, PYD:x=>0.25*x+30 };            // spread of volume stats; the rest are counts
function pName(n){
  n = String(n||"").normalize("NFKD").replace(/[̀-ͯ]/g,"").toLowerCase();
  [" fc","fc "," cf"," afc"," city"," united"," club","1. ","ac "," calcio","as ","ssc ","rc "].forEach(w=>{ n = n.split(w).join(" "); });
  return n.replace(/[.\-]/g," ").split(/\s+/).filter(w=>w && !["jr","sr","ii","iii","iv"].includes(w)).join(" ");
}
function erfc1(x){ const t = 1/(1+0.3275911*Math.abs(x)), y = t*(0.254829592+t*(-0.284496736+t*(1.421413741+t*(-1.453152027+t*1.061405429))))*Math.exp(-x*x); return x >= 0 ? y : 2-y; }
function atLeast(stat, lam, k){
  if(lam == null || !(lam >= 0)) return null;
  if(PSD[stat]){ const sd = Math.max(0.8, PSD[stat](lam)); return 0.5*erfc1((k-0.5-lam)/(sd*Math.SQRT2)); }
  let p = 0, t = Math.exp(-lam);
  for(let i=0; i<k; i++){ p += t; t *= lam/(i+1); }
  return Math.max(0, 1-p);
}
function bookHTML(r){
  const b = typeof BOARD !== "undefined" && BOARD && BOARD.props ? BOARD.props : (typeof PRO !== "undefined" && PRO && PRO.props ? PRO.props : null);
  if(!b) return "";
  const o = bookOf(r); if(!o) return "";
  const rows = (b[pName(o.name)]||{})[o.stat]; if(!rows || !rows.length) return "";
  let x;
  if(PONE[o.stat]) x = rows.find(e=>e[0]===PONE[o.stat] && e[5]) || rows.find(e=>e[0]===PONE[o.stat]);
  else x = rows.find(e=>e[5]) || rows.slice().sort((a,c)=>Math.abs(a[0]-o.lam)-Math.abs(c[0]-o.lam))[0];
  if(!x) return "";
  const ours = atLeast(o.stat, o.lam, x[0]); if(ours == null) return "";
  const lbl = PONE[o.stat] ? "" : '<b>'+(x[5] ? "o"+(x[0]-0.5) : x[0]+"+")+'</b> ';
  const edge = ours - x[1];
  return '<div class="bk">Book '+lbl+gPct(x[1])+' · ours '+gPct(ours)+' · '+gPrice(x[2])+' <em>'+x[3]+'</em>'
    + (edge >= 0.05 ? ' <span class="g-val">+'+Math.round(100*edge)+'%</span>' : '')+'</div>';
}
/* ===== end games view ===== */
