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

function gMarkets(g){
  const p = g.proj, w = p.win, rows = [];
  const fav = w[0] >= w[w.length-1];
  if(GKIND === "soccer"){
    rows.push(["Result", esc(g.home)+' '+gPct(w[0])+' · Draw '+gPct(w[1])+' · '+esc(g.away)+' '+gPct(w[2])]);
    rows.push(["Total goals", 'Over '+p.over[0]+' '+gPct(p.over[1])+' · Under '+gPct(1-p.over[1])]);
    rows.push(["Both teams score", 'Yes '+gPct(p.btts)+' · No '+gPct(1-p.btts)]);
    return rows;
  }
  rows.push(["Moneyline", esc(g.home)+' '+gPct(w[0])+' · '+esc(g.away)+' '+gPct(w[1])]);
  if(GKIND === "hockey"){
    rows.push(["Puck line", esc(fav ? g.home : g.away)+' -1.5 '+gPct(p.cover)+' · '+esc(fav ? g.away : g.home)+' +1.5 '+gPct(1-p.cover)]);
  } else if(p.book && p.book.spread != null){
    const bs = p.book.spread, homeEdge = p.cover - 0.5;
    rows.push(["Spread", 'Book '+esc(g.home)+' '+gLine(bs)+' · ours '+gLine(p.spread)
      + '<br>'+esc(g.home)+' covers '+gPct(p.cover)+' · '+esc(g.away)+' '+gPct(1-p.cover)
      + (Math.abs(homeEdge) >= 0.05 ? ' <span class="g-val">Value: '+esc(homeEdge > 0 ? g.home+' '+gLine(bs) : g.away+' '+gLine(-bs))+'</span>' : '')]);
  } else {
    rows.push(["Spread", 'Ours '+esc(g.home)+' '+gLine(p.spread)]);
  }
  const ov = p.over[1], book = p.book && p.book.total != null;
  rows.push(["Total", 'Proj '+p.total+(book ? ' · book '+p.over[0] : '')+'<br>Over '+p.over[0]+' '+gPct(ov)+' · Under '+gPct(1-ov)
    + (book && Math.abs(ov - 0.5) >= 0.05 ? ' <span class="g-val">Value: '+(ov > 0.5 ? "Over" : "Under")+'</span>' : '')]);
  return rows;
}

function gCard(g){
  const p = g.proj, open = !!GOPEN[g.id];
  const score = p.hs.toFixed(1)+' – '+p.as.toFixed(1);
  let h = '<div class="gcard'+(open?" open":"")+'" data-gid="'+esc(g.id)+'">'
    + '<div class="gc-top"><div class="gc-teams">'+(GKIND === "soccer" ? esc(g.home)+' <span>v</span> '+esc(g.away) : esc(g.away)+' <span>@</span> '+esc(g.home))+'</div><div class="gc-when">'+esc(g.when||"")+'</div></div>'
    + (g.lg ? '<div class="gc-lg">'+esc(g.lg)+'</div>' : '')
    + gWinBar(g)
    + '<div class="gc-proj">Projected <b>'+esc(g.home)+' '+score+' '+esc(g.away)+'</b></div>';
  if(open){
    h += '<div class="gc-mk">'+gMarkets(g).map(r=>'<div class="gm-row"><span>'+r[0]+'</span><div>'+r[1]+'</div></div>').join("")+'</div>';
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
/* ===== end games view ===== */
