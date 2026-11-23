/* ===== games view: shared by every HQ site; gList, gRows, GKIND are set per site ===== */
// a game is "pre" until its start time, then "live", then "final"; only pre-game bets can be added
function gState(t, fin){ return fin ? "final" : (t && Date.now() >= t ? "live" : "pre"); }
function gTag(st){ return st === "pre" ? "" : '<span class="g-tag '+st+'">'+(st === "final" ? "Final" : "Live")+'</span>'; }
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
// one market: [label html, our chance, book chance, [best price, book, every book's price, slip ids], what the bet slip calls it]
function gTable(title, sides, g){
  const pre = g && gState(g.t, g.fin) === "pre";
  return '<div class="gm-t">'+title+'</div><div class="gm-tbl"><div class="gm-h"><span></span><span>Ours</span><span>Book</span><span>Best price</span></div>'
    + sides.map(x=>{
      const q = x[3], all = q && q[2], top = all ? myBest(all) : (q ? [q[1], q[0]] : null);
      const leg = pre && top && x[4] && x[1] != null && x[2] != null
        ? legOf(x[4], { ours:x[1], book:x[2], price:top[1], bk:top[0], all:all || { [q[1]]: q[0] }, links:g.proj.links || {}, ids:q[3] || {},
                        game:{ n: GKIND === "soccer" ? g.home+" v "+g.away : g.away+" @ "+g.home, t:g.t } }) : null;
      return '<div class="gm-r"><span class="gm-l">'+(leg ? plBtn(leg) : '')+'<i>'+x[0]+'</i></span><span><b>'+gPct(x[1])+'</b></span><span>'+gPct(x[2])+'</span><span>'+(top ? gPrice(top[1])+' <em>'+top[0]+'</em>' : '—')+'</span></div>';
    }).join("")
    + '</div>';
}
function gMarkets(g){
  const p = g.proj, w = p.win, b = p.book && !p.book.src ? p.book : null, out = [];
  const H = esc(g.home), A = esc(g.away);
  if(GKIND === "soccer"){
    out.push(gTable("Result", [[H+gEdge(g,"Result",g.home), w[0], b&&b.ml&&b.ml[0], b&&b.mlp&&b.mlp[0], g.home+" to win"],
      ["Draw"+gEdge(g,"Result","Draw"), w[1], b&&b.ml&&b.ml[1], b&&b.mlp&&b.mlp[1], "Draw"],
      [A+gEdge(g,"Result",g.away), w[2], b&&b.ml&&b.ml[2], b&&b.mlp&&b.mlp[2], g.away+" to win"]], g));
    const ov = p.over_book != null ? p.over_book : p.over[1];
    out.push(gTable("Total goals 2.5", [["Over"+gEdge(g,"Total","Over 2.5"), ov, b&&b.over, b&&b.totp&&b.totp[0], "Over 2.5 goals"],
      ["Under"+gEdge(g,"Total","Under 2.5"), 1-ov, b&&b.over!=null?1-b.over:null, b&&b.totp&&b.totp[1], "Under 2.5 goals"]], g));
    out.push(gTable("Both teams score", [["Yes"+gEdge(g,"Both score","Yes"), p.btts, b&&b.btts, b&&b.bttsp&&b.bttsp[0], "Both teams to score: Yes"],
      ["No"+gEdge(g,"Both score","No"), 1-p.btts, b&&b.btts!=null?1-b.btts:null, b&&b.bttsp&&b.bttsp[1], "Both teams to score: No"]], g));
    return out;
  }
  out.push(gTable("Moneyline", [[A+gEdge(g,"Moneyline",g.away), w[1], b&&b.ml&&b.ml[1], b&&b.mlp&&b.mlp[1], g.away+" to win"],
    [H+gEdge(g,"Moneyline",g.home), w[0], b&&b.ml&&b.ml[0], b&&b.mlp&&b.mlp[0], g.home+" to win"]], g));
  if(b && b.spread != null){
    const l = b.spread, hs = g.home+" "+(l>0?"+":"")+l, as = g.away+" "+(-l>0?"+":"")+(-l);
    out.push(gTable((GKIND==="hockey"?"Puck line":"Spread")+' <i>ours '+H+' '+gLine(p.spread)+'</i>',
      [[esc(as)+gEdge(g,"Spread",as), 1-p.cover_book, 1-b.cover, b.spreadp&&b.spreadp[1], as],
       [esc(hs)+gEdge(g,"Spread",hs), p.cover_book, b.cover, b.spreadp&&b.spreadp[0], hs]], g));
  } else {
    out.push('<div class="gm-t">'+(GKIND==="hockey"?"Puck line":"Spread")+' <i>ours '+H+' '+gLine(p.spread)+(p.book&&p.book.spread!=null?' · consensus '+gLine(p.book.spread):'')+'</i></div>');
  }
  if(b && b.total != null){
    const t = b.total;
    const unit = GKIND === "hockey" ? " goals" : " points";
    out.push(gTable('Total '+t+' <i>ours '+p.total+'</i>', [["Over"+gEdge(g,"Total","Over "+t), p.over_book, b.over, b.totp&&b.totp[0], "Over "+t+unit],
      ["Under"+gEdge(g,"Total","Under "+t), 1-p.over_book, 1-b.over, b.totp&&b.totp[1], "Under "+t+unit]], g));
  } else {
    out.push('<div class="gm-t">Total <i>ours '+p.total+(p.book&&p.book.total!=null?' · consensus '+p.book.total:'')+'</i></div>');
  }
  return out;
}

function gCard(g){
  const p = g.proj, open = !!GOPEN[g.id], st = gState(g.t, g.fin);
  const score = p.hs.toFixed(1)+' – '+p.as.toFixed(1);
  let h = '<div class="gcard'+(open?" open":"")+(st !== "pre" ? " gc-off" : "")+'" data-gid="'+esc(g.id)+'">'
    + '<div class="gc-top"><div class="gc-teams">'+(GKIND === "soccer" ? esc(g.home)+' <span>v</span> '+esc(g.away) : esc(g.away)+' <span>@</span> '+esc(g.home))+'</div><div class="gc-when">'+(st !== "pre" ? gTag(st) : esc(g.when||""))+'</div></div>'
    + (st !== "pre" ? '<div class="gc-closed">Game started · these bets can\'t be added anymore</div>' : '')
    + (g.lg ? '<div class="gc-lg">'+esc(g.lg)+'</div>' : '')
    + gWinBar(g)
    + '<div class="gc-proj">Projected <b>'+esc(g.home)+' '+score+' '+esc(g.away)+'</b></div>';
  const bets = bestBets(g);
  if(bets.length && !open) h += '<div class="gc-sub">Best bet</div>' + betHTML(bets[0], true);
  if(bets.length && open) h += '<div class="gc-sub">Best bets in this game</div>' + bets.map((b,i)=>betHTML(b, i===0)).join("");
  if(open){
    h += '<div class="gc-mk">'+gMarkets(g).join("")
      + (p.book && !p.book.src ? '<p class="gm-note">Book = the sportsbooks\' fair chance with their margin removed. Best price = the best odds across DraftKings, FanDuel, BetMGM, Caesars and others. A green tag means we rate that side higher than the books do.</p>' : '')
      + '</div>';
    h += topPicks(g, st);
  }
  return h + '</div>';
}

function gamesHTML(){
  const list = gList().filter(g=>g.proj);
  if(GQ){ const hit = list.find(g=>g.home===GQ || String(g.id)===GQ); if(hit){ GOPEN[hit.id] = true; GJUMP = hit.id; } GQ = null; }
  if(!list.length) return '<div class="status"><h2>No game projections yet</h2><p>They appear once today\'s teams have played enough to rate.</p></div>';
  return '<p class="g-intro">Every game, projected by the same model as the board. Each game shows its best bet: where our chance beats the sportsbooks\' by the most at the best price out there. Tap a game for its top three, every market and the top player picks.</p>'
    + list.slice().sort((a,c)=>(gState(a.t, a.fin) !== "pre") - (gState(c.t, c.fin) !== "pre")).map(gCard).join("");     // started games sink below upcoming ones
}

function wireGames(){
  document.querySelectorAll(".gcard").forEach(el=> el.onclick = (e)=>{
    if(e.target.closest(".row, .gc-all, .tp")) return;
    GOPEN[el.dataset.gid] = !GOPEN[el.dataset.gid]; render();
  });
  document.querySelectorAll(".gc-all").forEach(b=> b.onclick = ()=>{
    const tp = b.closest(".gcard").querySelector(".tp"), k = tp && tp.dataset.tp;
    GV = false; F.game = b.dataset.all; if(k && k !== "BEST") F.stat = k; render(); scrollTo(0, 0);
  });
  if(typeof wireStars === "function") wireStars();
  if(GJUMP){ const el = document.querySelector('.gcard[data-gid="'+GJUMP+'"]'); GJUMP = null; if(el) el.scrollIntoView({ block:"start" }); }
}
// ---------- top player picks: the model's top three for each prop in one game ----------
let GTP = {};   // game -> chip picked ("BEST" = the #1 player for every prop)
function gTop(id, st){
  const keep = F.stat; F.stat = st;
  let rows = [];
  try { rows = gRows(id).filter(r=>!hurt(r)); } finally { F.stat = keep; }
  return rows;
}
function tpOurs(r, st, tl){
  const o = bookOf(r, st);
  if(!o || o.lam == null) return { v:"—", w:"" };
  if(PONE[st]){ const c = atLeast(st, o.lam, PONE[st]); return { v:gPct(c), w:st === "3PM" ? PONE[st]+"+ threes" : BLBL[st] }; }
  return { v:o.lam >= 20 ? String(Math.round(o.lam)) : o.lam.toFixed(1), w:"proj "+String(tl).toLowerCase() };
}
function tpRow(r, t, rank, best, open){
  const st = t[0], lbl = best ? t[1] : "", o = bookOf(r, st), us = tpOurs(r, st, t[1]);
  let bk = "";
  const x = o ? bookPick(o) : null;
  if(x){
    const line = lineName(o.stat, x);
    const edge = x.ours - x.book;
    const leg = open ? legOf(shortName(o.name)+" "+line, { ours:x.ours, book:x.book, price:x.price, bk:x.bk, all:x.all, links:x.links, ids:x.ids, game:gInfo(r) }) : null;
    bk = '<div class="tp-bk">'+(leg ? plBtn(leg) : '')+'<span>'+(PONE[o.stat] ? '' : '<b>'+(x.two ? "o"+(x.k-0.5) : x.k+"+")+'</b> ')+gPrice(x.price)+' <em>'+x.bk+'</em>'
      + (edge >= 0.05 ? ' <span class="g-val">+'+Math.round(100*edge)+'%</span>' : '')+'</span></div>';
  } else bk = '<div class="tp-bk tp-none">No book line yet</div>';
  const team = r.team || r.p.team || "";
  return '<div class="tp-row'+(lbl ? ' tp-best' : '')+'"><div class="tp-rk">'+(lbl ? '' : rank)+'</div>'
    + '<div class="tp-who">'+(lbl ? '<i class="tp-tag">'+lbl+'</i>' : '')+'<b>'+esc(shortName(r.p.name || r.p.n || ""))+'</b><span>'+esc(team)+'</span></div>'
    + '<div class="tp-us"><b>'+us.v+'</b><span>'+esc(us.w)+'</span></div>' + bk + '</div>';
}
function topPicks(g, st){
  const open = st === "pre", tabs = PTABS.filter(t=>gTop(g.id, t[0]).length);
  if(!tabs.length) return "";
  const cur = GTP[g.id] || "BEST";
  const chip = (k, t) => '<button type="button" class="tp-chip'+(cur === k ? ' on' : '')+'" data-k="'+k+'" onclick="tpPick(event,this)">'+t+'</button>';
  let h = '<div class="gc-sub">Top 3 player picks in this game</div><div class="tp" data-tp="'+cur+'"><div class="tp-chips">'+chip("BEST", "Best of each")+tabs.map(t=>chip(t[0], t[1])).join("")+'</div>';
  h += '<div class="tp-pane'+(cur === "BEST" ? ' on' : '')+'" data-k="BEST">'+tabs.map(t=>{ const r = gTop(g.id, t[0])[0]; return tpRow(r, t, 1, true, open); }).join("")+'</div>';
  h += tabs.map(t=>'<div class="tp-pane'+(cur === t[0] ? ' on' : '')+'" data-k="'+t[0]+'">'+gTop(g.id, t[0]).slice(0, 3).map((r, i)=>tpRow(r, t, i+1, false, open)).join("")+'</div>').join("");
  return h + '</div><button class="navbtn gc-all" data-all="'+esc(g.id)+'">Full board for this game</button>';
}
function tpPick(e, el){
  e.stopPropagation();
  const tp = el.closest(".tp"), k = el.dataset.k;
  tp.dataset.tp = k; GTP[el.closest(".gcard").dataset.gid] = k;
  tp.querySelectorAll(".tp-chip").forEach(c=>c.classList.toggle("on", c === el));
  tp.querySelectorAll(".tp-pane").forEach(p=>p.classList.toggle("on", p.dataset.k === k));
}
// ---------- book prices on player rows ----------
const PONE = { G:1, A:1, P:1, GA:1, TD:1 };           // yes/no props, shown as a chance of at least one; the rest use the books' main line
const PEXTRA = { P:[2] };     // extra rungs priced alongside a tab's main line (2+ points in hockey)
const PSD = { PTS:x=>1.35*Math.sqrt(x), REB:x=>1.25*Math.sqrt(x), AST:x=>1.3*Math.sqrt(x), PRA:x=>1.4*Math.sqrt(x),
              PR:x=>1.35*Math.sqrt(x), PA:x=>1.35*Math.sqrt(x), RA:x=>1.3*Math.sqrt(x),
              CYD:x=>0.55*x+8, RYD:x=>0.55*x+8, PYD:x=>0.25*x+30 };            // spread of volume stats; the rest are counts
function pName(n){
  n = String(n||"").normalize("NFKD").replace(/[̀-ͯ]/g,"").toLowerCase();
  [" fc","fc "," cf"," afc"," city"," united"," club","1. ","ac "," calcio","as ","ssc ","rc "].forEach(w=>{ n = n.split(w).join(" "); });
  return n.replace(/[.\-]/g," ").split(/\s+/).filter(w=>w && !["jr","sr","ii","iii","iv"].includes(w)).join(" ");
}
function erfc1(x){ const t = 1/(1+0.3275911*Math.abs(x)), y = t*(0.254829592+t*(-0.284496736+t*(1.421413741+t*(-1.453152027+t*1.061405429))))*Math.exp(-x*x); return x >= 0 ? y : 2-y; }
// our raw chance, corrected by how chances like it have actually held up this season (see the Results Dashboard)
function calFix(key, c){
  const bd = logBoard(), m = bd && bd.cal && bd.cal[key];
  if(!m || c == null) return c;
  if(c <= m[0][0]) return c * m[0][1] / m[0][0];
  for(let i = 1; i < m.length; i++) if(c <= m[i][0]){ const a = m[i-1], b = m[i]; return a[1] + (b[1]-a[1]) * (c-a[0]) / (b[0]-a[0]); }
  const z = m[m.length-1]; return Math.min(0.99, c + (z[1] - z[0]));
}
function atLeast(stat, lam, k){ return PSD[stat] ? atLeastRaw(stat, lam, k) : calFix(stat+k, atLeastRaw(stat, lam, k)); }
function atLeastRaw(stat, lam, k){
  if(lam == null || !(lam >= 0)) return null;
  if(PSD[stat]){ const sd = Math.max(0.8, PSD[stat](lam)); return 0.5*erfc1((k-0.5-lam)/(sd*Math.SQRT2)); }
  let p = 0, t = Math.exp(-lam);
  for(let i=0; i<k; i++){ p += t; t *= lam/(i+1); }
  return Math.max(0, 1-p);
}
// the best price among the books this person uses (every book when none are picked)
function myBest(all){
  let top = null;
  for(const bk in all) if((!PLMY.length || PLMY.includes(bk)) && (!top || all[bk] > top[1])) top = [bk, all[bk]];
  return top;
}
function boardData(){ return typeof BOARD !== "undefined" && BOARD && BOARD.props ? BOARD : (typeof PRO !== "undefined" && PRO && PRO.props ? PRO : null); }
function bookPick(o, kk){
  const bd = boardData(), b = bd && bd.props;
  if(!b || !o) return null;
  const rows = (b[pName(o.name)]||{})[o.stat]; if(!rows || !rows.length) return null;
  let x;
  if(kk) x = rows.find(e=>e[0]===kk && e[5]) || rows.find(e=>e[0]===kk);
  else if(PONE[o.stat]) x = rows.find(e=>e[0]===PONE[o.stat] && e[5]) || rows.find(e=>e[0]===PONE[o.stat]);
  else x = rows.find(e=>e[5]) || rows.slice().sort((a,c)=>Math.abs(a[0]-o.lam)-Math.abs(c[0]-o.lam))[0];
  if(!x) return null;
  const ours = atLeast(o.stat, o.lam, x[0]); if(ours == null) return null;
  const all = x[6] || { [x[3]]: x[2] }, top = myBest(all); if(!top) return null;
  return { k:x[0], book:x[1], price:top[1], bk:top[0], n:x[4], two:!!x[5], all, links:(bd.evlinks||{})[x[7]] || {}, ids:x[8] || {}, ours };
}
function lineName(st, x, kk){
  if(kk) return kk+"+ "+(BLBL[st+kk] || BLBL[st]);
  return PONE[st] ? (st === "3PM" ? x.k+"+ threes" : BLBL[st]) : (x.two ? "o"+(x.k-0.5) : x.k+"+")+" "+BLBL[st];
}
function bookHTML(r){
  const gi = gInfo(r), st = gState(gi.t, gi.f);
  if(st !== "pre") return '<div class="bk bk-off">'+gTag(st)+' Game started · can\'t be added</div>';
  const o = bookOf(r);
  return [0].concat(PEXTRA[o.stat] || []).map(kk=>{
    const x = bookPick(o, kk); if(!x) return "";
    const lbl = kk ? '<b>'+kk+'+</b> ' : PONE[o.stat] ? "" : '<b>'+(x.two ? "o"+(x.k-0.5) : x.k+"+")+'</b> ';
    const edge = x.ours - x.book;
    const leg = legOf(shortName(o.name)+" "+lineName(o.stat, x, kk), { ours:x.ours, book:x.book, price:x.price, bk:x.bk, all:x.all, links:x.links, ids:x.ids, game:gInfo(r) });
    return '<div class="bk">'+plBtn(leg)+'Book '+lbl+gPct(x.book)+' · ours '+gPct(x.ours)+' · '+gPrice(x.price)+' <em>'+x.bk+'</em>'
      + (edge >= 0.05 ? ' <span class="g-val">+'+Math.round(100*edge)+'%</span>' : '')+'</div>';
  }).join("");
}

// ---------- best bets: every priced bet in a game on one scale ----------
const BLBL = { G:"to score", A:"to assist", P:"1+ point", GA:"goal or assist", TD:"anytime TD", BLK:"1+ block", STL:"1+ steal",
  "3PM":"threes", PTS:"pts", REB:"reb", AST:"ast", PRA:"pts+reb+ast", REC:"receptions", CYD:"rec yds", RYD:"rush yds", PYD:"pass yds",
  PTD:"pass TDs", S:"shots on goal", P2:"points", PR:"pts+reb", PA:"pts+ast", RA:"reb+ast" };
function dec(a){ return a > 0 ? 1 + a/100 : 1 + 100/(-a); }
// our number pulled halfway to the book's: the books are sharp and our edges are not proven yet
function betOf(name, label, ours, book, price, bk, kind, game, all, links, ids){
  const adj = book + 0.5*(ours - book);
  return { name, label, ours, book, adj, price, bk, kind, game, all, links, ids, ev: adj*dec(price) - 1 };
}
function bestBets(g){
  const out = [], seen = {};
  if(gState(g.t, g.fin) !== "pre") return out;
  for(const r of gRows(g.id)){
    if(hurt(r)) continue;
    for(const st of BSTATS) for(const kk of [0].concat(PEXTRA[st] || [])){
      const o = bookOf(r, st), x = bookPick(o, kk); if(!x || x.n < 2) continue;      // priced by at least two books
      // a volume line far from our projection usually means the books know about a role change we don't
      if(!kk && !PONE[st] && st !== "S" && Math.abs(o.lam - x.k) > 0.5 * Math.max(x.k, 4)) continue;
      out.push(betOf(shortName(o.name), lineName(st, x, kk), x.ours, x.book, x.price, x.bk, "prop", gInfo(r), x.all, x.links, x.ids));
    }
  }
  for(const v of (g.proj.value||[])){
    const top = myBest(v.all || { [v.bk]: v.price }); if(!top) continue;
    const what = v.mk === "Moneyline" || v.mk === "Result" ? [v.side, v.side === "Draw" ? "" : "to win"]
      : v.mk === "Total" ? [v.side, GKIND === "soccer" ? "goals" : GKIND === "hockey" ? "goals" : "points"]
      : v.mk === "Both score" ? ["Both teams to score:", v.side] : [v.side, ""];
    out.push(betOf(what[0], what[1], v.ours, v.book, top[1], top[0], "game",
      { n: GKIND === "soccer" ? g.home+" v "+g.away : g.away+" @ "+g.home, t: g.t }, v.all, g.proj.links, v.ids));
  }
  return out.filter(b=>b.adj >= 0.2 && b.ours > b.book && b.ev > 0)
    .sort((a,c)=>c.ev - a.ev)
    .filter(b=>{ if(b.kind==="prop"){ if(seen[b.name]) return false; seen[b.name] = 1; } return true; })
    .slice(0, 3);
}
function betHTML(b, top){
  return '<div class="bb'+(top?" top":"")+'">'+plBtn(legOf((b.name+" "+b.label).trim(), b))+'<div class="bb-what"><b>'+esc(b.name)+'</b> '+esc(b.label)+'</div>'
    + '<div class="bb-num">'+gPct(b.ours)+' <span>vs book '+gPct(b.book)+'</span></div>'
    + '<div class="bb-px">'+gPrice(b.price)+' <em>'+b.bk+'</em></div></div>';
}
// ---------- parlay slip: one slip that travels with you between the HQ sites ----------
// Each site keeps it in its own storage; every link to another HQ site carries it in the address,
// and whichever copy was changed last wins.
const PLKEY = "hq.parlay", HQ_HOSTS = /(^|\.)(total|moonshot|touchdown|slapshot|slam|futbol)-hq\.com$/;
function plFresh(v){ return v.filter(l=>!l.t || l.t > Date.now() - 6*3600e3); }
function plRead(){ try { const v = JSON.parse(localStorage.getItem(PLKEY) || "[]"); return Array.isArray(v) ? { u:0, legs:v } : v; } catch(e){ return { u:0, legs:[] }; } }
function plEnc(o){ return btoa(unescape(encodeURIComponent(JSON.stringify(o)))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,""); }
function plDec(x){ x = x.replace(/-/g,"+").replace(/_/g,"/"); while(x.length % 4) x += "="; return JSON.parse(decodeURIComponent(escape(atob(x)))); }
let PLU = 0, PLBK = null, PLMY = [];      // PLMY: the books this person uses (empty = every book)
let PL = (function(){
  let st = plRead();
  const m = /[#&]pl=([A-Za-z0-9_-]+)/.exec(location.hash);
  if(m){
    try { const inc = plDec(m[1]); if(inc && (inc.u||0) >= (st.u||0)) st = inc; } catch(e) {}
    try { localStorage.setItem(PLKEY, JSON.stringify(st)); } catch(e) {}
    try { history.replaceState(null, "", location.pathname + location.search); } catch(e) {}
  }
  PLU = st.u || 0;
  PLBK = st.bk || null;
  PLMY = st.my || [];
  return plFresh(st.legs || []);
})();
function plSave(v){ PLU = Date.now(); try { localStorage.setItem(PLKEY, JSON.stringify({ u:PLU, legs:v, bk:PLBK, my:PLMY })); } catch(e){} plLinks(); }
// every link to another HQ site carries the slip
function plLinks(){
  const tag = PLU ? "pl=" + plEnc({ u:PLU, legs:PL, bk:PLBK, my:PLMY }) : "";
  document.querySelectorAll("a[href]").forEach(a=>{
    let u; try { u = new URL(a.getAttribute("href"), location.href); } catch(e){ return; }
    if(!HQ_HOSTS.test(u.hostname) || u.hostname === location.hostname) return;
    u.hash = tag;
    a.setAttribute("href", u.toString());
  });
}
let PLMO = null;
try { new MutationObserver(()=>{ clearTimeout(PLMO); PLMO = setTimeout(plLinks, 50); }).observe(document.documentElement, { childList:true, subtree:true }); } catch(e) {}
let PLOPEN = false;
function legOf(label, b){
  return { i: PSITE+"|"+(b.game&&b.game.n)+"|"+label, s:PSITE, g:b.game&&b.game.n, t:b.game&&b.game.t, l:label,
           p:b.price, b:b.bk, a:b.all || { [b.bk]: b.price }, u:b.links || {}, x:b.ids || {}, o:Math.round(1000*b.ours)/1000, k:Math.round(1000*b.book)/1000 };
}
// a leg already in the parlay picks up the board's latest prices, links and bet ids whenever its row is drawn
let PLFIX = null;
function plRefresh(leg){
  const at = PL.findIndex(l=>l.i===leg.i);
  if(at < 0) return false;
  const old = PL[at];
  if(JSON.stringify([old.a, old.x, old.u, old.p]) !== JSON.stringify([leg.a, leg.x, leg.u, leg.p])){
    PL[at] = Object.assign({}, old, { p:leg.p, b:leg.b, a:leg.a, u:leg.u, x:leg.x, o:leg.o, k:leg.k });
    clearTimeout(PLFIX); PLFIX = setTimeout(()=>{ plSave(PL); plBar(); }, 0);
  }
  return true;
}
function plBtn(leg){
  const on = plRefresh(leg);
  return '<button class="pl-add'+(on?" on":"")+'" data-leg="'+encodeURIComponent(JSON.stringify(leg))+'" aria-label="Add to parlay">'+(on?"✓":"+")+'</button>';
}
const BKHOME = { DK:"https://sportsbook.draftkings.com", FD:"https://sportsbook.fanduel.com", MGM:"https://sports.betmgm.com",
  CZR:"https://sportsbook.caesars.com", FAN:"https://sportsbook.fanatics.com", ESPN:"https://espnbet.com", BR:"https://www.betrivers.com",
  HR:"https://app.hardrock.bet" };
// links that drop every leg into a book's bet slip (null when a leg has no id at that book)
const SLIPLINK = {};
function slipUrl(bk, legs){
  const ids = legs.map(l=>(l.x||{})[bk]);
  if(!ids.length || ids.some(x=>!x)) return null;
  if(bk === "DK" || bk === "FD" || bk === "FAN"){
    if(ids.length > 12 || ids.some(x=>!/^\d{4,20}$/.test(String(x)))) return null;     // legs saved before the current ids
    return "https://total-hq.com/betlink?bk=" + bk + "&ids=" + ids.join(",");
  }
  if(bk === "HR"){       // Hard Rock's own share-link format, from its bet ids
    if(ids.some(x=>!/^\d{6,25}$/.test(String(x)))) return null;
    return "hardrock://betslip/" + ids.join(",");     // the app's own address; the share domain fell back to Safari
  }
  if(bk === "MGM") return "https://sports.betmgm.com/en/sports?options=" + ids.map(encodeURIComponent).join(",");
  return null;
}
const MYBOOKS = ["FD", "DK", "FAN", "HR", "MGM", "BR"];
const BKNAME = { DK:"DraftKings", FD:"FanDuel", MGM:"BetMGM", CZR:"Caesars", FAN:"Fanatics", ESPN:"ESPN Bet", BR:"BetRivers", HR:"Hard Rock", BOV:"Bovada", PIN:"Pinnacle" };
function amer(d){ return d >= 2 ? Math.round((d-1)*100) : Math.round(-100/(d-1)); }
// a parlay is placed at one book, so it is priced book by book from that book's own prices
function plMath(legs){
  const ours = legs.reduce((a,l)=>a*l.o, 1), book = legs.reduce((a,l)=>a*l.k, 1);
  const prices = l => l.a || { [l.b]: l.p };
  const books = [...new Set(legs.flatMap(l=>Object.keys(prices(l))))].filter(bk=>!PLMY.length || PLMY.includes(bk)).map(bk=>{
    const have = legs.filter(l=>prices(l)[bk] != null);
    return { bk, n: have.length, missing: legs.filter(l=>prices(l)[bk] == null), price: amer(have.reduce((a,l)=>a*dec(prices(l)[bk]), 1)) };
  }).sort((a,c)=> c.n - a.n || dec(c.price) - dec(a.price));
  const full = books.filter(b=>b.n === legs.length);
  return { best: full[0] || null, full, partial: books.filter(b=>b.n < legs.length), ours, book,
           sameGame: new Set(legs.map(l=>l.g)).size < legs.length, at: bk => l => prices(l)[bk] };
}
function plBar(){
  let el = document.getElementById("plbar");
  if(!el){ el = document.createElement("div"); el.id = "plbar"; document.body.appendChild(el); }
  if(!PL.length){ el.innerHTML = ""; el.className = ""; return; }
  const m = plMath(PL), all = m.full.concat(m.partial);
  const pick = all.find(b=>b.bk===PLBK) || m.best || all[0];
  const full = pick && pick.n === PL.length;
  el.className = "on"+(PLOPEN?" open":"");
  const at = pick ? m.at(pick.bk) : (l=>l.p);
  const legLine = (l,i)=>{
    if(l.t && Date.now() >= l.t)
      return '<div class="pl-leg pl-gone"><div><b>'+esc(l.l)+'</b><span>'+esc(l.g||"")+'</span></div><div class="pl-p"><span class="g-tag live">Started</span></div><button class="pl-x" data-i="'+i+'" aria-label="Remove">✕</button></div>';
    const p = at(l), url = pick && l.u && l.u[pick.bk];
    const px = p == null ? '<span class="pl-no">not at '+esc(BKNAME[pick.bk]||pick.bk)+'</span>' : gPrice(p)+' <em>'+esc(pick.bk)+'</em>';
    return '<div class="pl-leg"><div><b>'+esc(l.l)+'</b><span>'+esc(l.g||"")+(url ? ' · <a href="'+esc(url)+'" target="_blank" rel="noopener">open game</a>' : '')+'</span></div>'
      + '<div class="pl-p">'+px+'</div><button class="pl-x" data-i="'+i+'" aria-label="Remove">✕</button></div>';
  };
  const bookRow = b=>'<button class="pl-bk'+(pick&&b.bk===pick.bk?" on":"")+(b.n<PL.length?" part":"")+'" data-bk="'+b.bk+'"><span>'+esc(BKNAME[b.bk]||b.bk)+'</span>'
    + (b.n === PL.length ? '<b>'+gPrice(b.price)+'</b>' : '<i>'+b.n+' of '+PL.length+' legs</i>')+'</button>';
  const games = [...new Set(PL.map(l=>l.g))];
  const oneGameUrl = pick && games.length === 1 ? (PL.find(l=>l.u && l.u[pick.bk])||{u:{}}).u[pick.bk] : null;
  const gone = PL.filter(l=>l.t && Date.now() >= l.t);
  const slip = pick && full && !gone.length ? slipUrl(pick.bk, PL) : null;
  const placeUrl = pick ? (slip || oneGameUrl || BKHOME[pick.bk]) : null;
  el.innerHTML = (PLOPEN ? '<div class="pl-legs">'+PL.map(legLine).join("")
      + '<div class="pl-where"><div class="pl-wt">Tap a sportsbook to price your parlay there</div>'+all.slice(0, 8).map(bookRow).join("")+'</div>'
      + '<div class="pl-my"><div class="pl-wt">My books <span>'+(PLMY.length ? 'only these are priced' : 'tap the ones you use')+'</span></div>'
      + MYBOOKS.map(bk=>'<button class="pl-chip'+(PLMY.includes(bk)?" on":"")+'" data-my="'+bk+'">'+esc(BKNAME[bk])+'</button>').join("")+'</div>'
      + (gone.length ? '<p class="pl-note pl-warn">'+gone.length+' leg'+(gone.length>1?"s have":" has")+' started and can\'t be bet anymore. <button class="pl-link" id="pl-drop">Remove started legs</button></p>' : '')
      + (m.full.length ? '' : '<p class="pl-note pl-warn">No single sportsbook has every leg right now. Remove a leg or swap it for one your book has.</p>')
      + (m.sameGame ? '<p class="pl-note">Some legs share a game. Books price same-game parlays their own way, so the price there may differ.</p>' : '')
      + '<div class="pl-acts">'+(placeUrl ? '<a class="navbtn pl-go" id="pl-go" href="'+esc(SLIPLINK[placeUrl] || placeUrl)+'"'+(slip ? '' : ' target="_blank" rel="noopener"')+'>'+(slip ? 'Add to '+esc(BKNAME[pick.bk]||pick.bk)+' bet slip' : 'Open '+esc(BKNAME[pick.bk]||pick.bk))+'</a>' : '')
      + '<button class="navbtn" id="pl-copy">Copy legs</button></div>'
      + '<p class="pl-note">'+(slip ? 'Loads every leg into your '+esc(BKNAME[pick.bk]||pick.bk)+' bet slip. ' : (oneGameUrl ? 'Opens this game at '+esc(BKNAME[pick.bk]||pick.bk)+'. ' : 'Opens '+esc(BKNAME[pick.bk]||pick.bk||"the book")+'; add each leg there, or tap "open game" on a leg. ')
        + 'FanDuel, DraftKings, Fanatics, Hard Rock and BetMGM can load the whole slip. ')+'Your parlay follows you to every HQ site.</p>'
      + '<div class="pl-acts"><button class="navbtn" id="pl-clear">Clear</button><a class="navbtn" href="https://total-hq.com/" style="text-align:center;text-decoration:none">See it on Total HQ</a></div></div>' : '')
    + '<button class="pl-head" id="pl-toggle"><span>Parlay · '+PL.length+' leg'+(PL.length>1?"s":"")+(pick ? ' · '+esc(BKNAME[pick.bk]||pick.bk) : '')+'</span>'
    + '<b>'+(full && !gone.length ? gPrice(pick.price) : '—')+'</b><span class="pl-ch">'+(gone.length ? gone.length+' leg'+(gone.length>1?"s":"")+' started · tap to fix' : full ? 'ours '+gPct(m.ours)+' · book '+gPct(m.book) : pick ? pick.n+' of '+PL.length+' legs at this book' : '')+'</span></button>';
  el.querySelectorAll(".pl-bk[data-bk]").forEach(b=> b.onclick = ()=>{ PLBK = b.dataset.bk; plSave(PL); plBar(); });
  el.querySelectorAll(".pl-chip[data-my]").forEach(b=> b.onclick = ()=>{
    const bk = b.dataset.my;
    PLMY = PLMY.includes(bk) ? PLMY.filter(x=>x!==bk) : PLMY.concat(bk);
    if(PLBK && PLMY.length && !PLMY.includes(PLBK)) PLBK = null;
    plSave(PL); plBar();
    if(typeof render === "function") render();      // every price on the board follows your books
  });
  // put the sportsbook's own link on the button, so a tap opens the book's app rather than a browser redirect
  if(slip && !SLIPLINK[slip] && slip.indexOf("/betlink?") > 0){
    fetch(slip + "&json=1").then(r=>r.json()).then(d=>{
      if(!d || !d.link) return;
      SLIPLINK[slip] = d.link;
      const a = document.getElementById("pl-go"); if(a) a.setAttribute("href", d.link);
    }).catch(()=>{});
  }
  const dr = document.getElementById("pl-drop");
  if(dr) dr.onclick = ()=>{ PL = PL.filter(l=>!(l.t && Date.now() >= l.t)); plSave(PL); plBar(); plSync(); };
  const cp = document.getElementById("pl-copy");
  if(cp) cp.onclick = ()=>{
    const txt = PL.map(l=>l.l+" ("+(l.g||"")+")"+(at(l)!=null ? " "+gPrice(at(l)) : "")).join("\n") + (full ? "\nParlay "+gPrice(pick.price)+" at "+(BKNAME[pick.bk]||pick.bk) : "");
    try { navigator.clipboard.writeText(txt).then(()=>{ cp.textContent = "Copied"; setTimeout(()=>{ cp.textContent = "Copy legs"; }, 1500); }); } catch(e) {}
  };
  document.getElementById("pl-toggle").onclick = ()=>{ PLOPEN = !PLOPEN; plBar(); };
  el.querySelectorAll(".pl-x").forEach(b=> b.onclick = ()=>{ PL.splice(+b.dataset.i, 1); plSave(PL); plBar(); plSync(); });
  const c = document.getElementById("pl-clear"); if(c) c.onclick = ()=>{ PL = []; plSave(PL); PLOPEN = false; plBar(); plSync(); };
  plLinks();
}
function plSync(){ document.querySelectorAll(".pl-add").forEach(b=>{ const l = JSON.parse(decodeURIComponent(b.dataset.leg)); const on = PL.some(x=>x.i===l.i); b.classList.toggle("on", on); b.textContent = on ? "✓" : "+"; }); }
document.addEventListener("click", e=>{
  const b = e.target.closest && e.target.closest(".pl-add"); if(!b) return;
  e.stopPropagation(); e.preventDefault();
  const l = JSON.parse(decodeURIComponent(b.dataset.leg)), at = PL.findIndex(x=>x.i===l.i);
  if(at >= 0) PL.splice(at, 1); else PL.push(l);
  plSave(PL); plSync(); plBar();
}, true);
setTimeout(plBar, 0);
// ---------- game logs: Last 5 | vs opponent at the bottom of every player's detail ----------
// each site supplies logCols(r): [[label, value of a game, tab it belongs to]], first column is minutes or volume
let LOGTAB = "l5";
function logBoard(){ return typeof BOARD !== "undefined" && BOARD && (BOARD.logcols || BOARD.cal) ? BOARD : (typeof PRO !== "undefined" && PRO ? PRO : null); }
function logRows(list, opp){
  const cols = (logBoard() || {}).logcols || [];
  return (list || []).map(x=>{ const s = {}, o = opp ? 2 : 1; cols.forEach((c, i)=>{ s[c] = +x[o + i] || 0; }); return { d:x[0], opp:opp ? x[1] : "", s }; });
}
function logDay(d, yr){
  let m = /^(\d{4})-W(\d+)$/.exec(d);
  if(m) return (m[1] !== yr ? "'"+m[1].slice(2)+" " : "")+"Wk "+(+m[2]);
  m = /^(\d{4})-(\d\d)-(\d\d)$/.exec(d); if(!m) return d;
  const t = new Date(+m[1], +m[2]-1, +m[3]).toLocaleDateString([], { month:"short", day:"numeric" });
  return m[1] !== yr ? t+" '"+m[1].slice(2) : t;
}
function logNum(v){ return Math.round(v*10)/10; }
function logLine(r){
  let x = null; try { x = bookPick(bookOf(r)); } catch(e){}
  if(x) return { k:x.k, txt:x.two ? "o"+(x.k-0.5) : x.k+"+" };
  const one = PONE[F.stat]; return one ? { k:one, txt:one+"+" } : null;
}
function logCards(games, cols, main, line, yr){
  const sub = cols[0] === main ? cols[1] : cols[0];
  return '<div class="lg-cards">'+games.map((g, i)=>{
    const v = main[1](g.s), hit = line ? (v >= line.k ? " hit" : " miss") : "";
    return '<div class="lg-c'+hit+(i >= 5 ? ' lg-x' : '')+'"><div class="lg-d">'+logDay(g.d, yr)+'</div>'+(g.opp ? '<div class="lg-o">'+esc(g.opp)+'</div>' : '')
      + '<div class="lg-v">'+logNum(v)+'</div><div class="lg-k">'+main[0]+'</div><div class="lg-s">'+logNum(sub[1](g.s))+' '+sub[0]+'</div></div>';
  }).join("")+'</div>';
}
function logSum(games, main, line, what){
  if(!games.length) return "";
  const vals = games.map(g=>main[1](g.s)), avg = vals.reduce((a,b)=>a+b, 0)/vals.length;
  const hits = line ? vals.filter(v=>v >= line.k).length : null;
  return '<div class="lg-sum">Avg <b>'+avg.toFixed(1)+'</b> '+main[0]+(line ? ' · cleared <b>'+line.txt+'</b> in <b>'+hits+' of '+vals.length+'</b>' : '')+(what ? ' '+what : '')+'</div>';
}
function logsHTML(r){
  const p = r.p, cols = logCols(r), st = F.stat;
  if(!cols || !(p.last5 || p.vs)) return "";
  const main = cols.find(c=>c[2]===st) || cols[1] || cols[0], line = logLine(r);
  const l5 = logRows(p.last5, true), v = p.vs || {}, vg = logRows(v.g, false);
  const yr = l5.length ? String(l5[0].d).slice(0, 4) : String(new Date().getFullYear());
  const opp = v.opp || "", gw = GKIND === "soccer" ? "Matches" : "Games";
  const tab = (k, t) => '<button type="button" class="lg-tab'+(LOGTAB===k ? ' on' : '')+'" onclick="logSwitch(event,this,\''+k+'\')">'+t+'</button>';
  let h = '<div class="glog" data-tab="'+LOGTAB+'"><div class="lg-tabs">'+tab("l5", "Last "+(l5.length || 5)+" "+gw)+tab("vs", gw+" vs "+esc(opp)+(vg.length ? " ("+vg.length+")" : ""))+'</div>';
  h += '<div class="lg-pane lg-l5">'+(l5.length ? logSum(l5, main, line, "") + logCards(l5, cols, main, line, yr) : '<div class="lg-none">No games logged yet this season</div>')+'</div>';
  h += '<div class="lg-pane lg-vs">';
  const span = GKIND === "soccer" ? "this season and last" : "last 3 seasons and this one";
  if(!vg.length) h += '<div class="lg-none">No history against '+esc(opp)+'</div>';
  else {
    const avg = c => logNum(vg.reduce((a,g)=>a + c[1](g.s), 0)/vg.length);
    h += '<div class="lg-grid">'+cols.map(c=>'<div class="lg-gc'+(c===main ? ' on' : '')+'"><div class="lg-gk">'+c[0]+'</div><div class="lg-gv">'+avg(c)+'</div></div>').join("")+'</div>'
      + '<div class="lg-note">Per game, all '+vg.length+' · '+span+'</div>'
      + logSum(vg, main, line, "")
      + logCards(vg, cols, main, line, yr)
      + (vg.length > 5 ? '<button type="button" class="lg-all" onclick="logAll(event,this)">Show all '+vg.length+'</button>' : '');
  }
  return h + '</div></div>';
}
function logAll(e, el){
  e.stopPropagation();
  const b = el.closest(".glog"), on = b.classList.toggle("all");
  el.textContent = on ? "Show fewer" : "Show all "+b.querySelectorAll(".lg-vs .lg-c").length;
}
function logSwitch(e, el, k){
  e.stopPropagation(); LOGTAB = k;
  document.querySelectorAll(".glog").forEach(b=>{ b.dataset.tab = k; b.querySelectorAll(".lg-tab").forEach((t, i)=>t.classList.toggle("on", (i===0) === (k==="l5"))); });
}
/* ===== end games view ===== */
