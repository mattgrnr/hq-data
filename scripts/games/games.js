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
    + '<div class="gc-proj">Projected <b>'+esc(g.home)+' '+score+' '+esc(g.away)+'</b></div>';
  const bets = bestBets(g);
  if(bets.length && !open) h += '<div class="gc-sub">Best bet</div>' + betHTML(bets[0], true);
  if(bets.length && open) h += '<div class="gc-sub">Best bets in this game</div>' + bets.map((b,i)=>betHTML(b, i===0)).join("");
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
  return '<p class="g-intro">Every game, projected by the same model as the board. Each game shows its best bet: where our chance beats the sportsbooks\' by the most at the best price out there. Tap a game for its top three, every market and the top player picks.</p>'
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
function boardData(){ return typeof BOARD !== "undefined" && BOARD && BOARD.props ? BOARD : (typeof PRO !== "undefined" && PRO && PRO.props ? PRO : null); }
function bookPick(o){
  const bd = boardData(), b = bd && bd.props;
  if(!b || !o) return null;
  const rows = (b[pName(o.name)]||{})[o.stat]; if(!rows || !rows.length) return null;
  let x;
  if(PONE[o.stat]) x = rows.find(e=>e[0]===PONE[o.stat] && e[5]) || rows.find(e=>e[0]===PONE[o.stat]);
  else x = rows.find(e=>e[5]) || rows.slice().sort((a,c)=>Math.abs(a[0]-o.lam)-Math.abs(c[0]-o.lam))[0];
  if(!x) return null;
  const ours = atLeast(o.stat, o.lam, x[0]); if(ours == null) return null;
  return { k:x[0], book:x[1], price:x[2], bk:x[3], n:x[4], two:!!x[5], all:x[6] || { [x[3]]: x[2] }, links:(bd.evlinks||{})[x[7]] || {}, ids:x[8] || {}, ours };
}
function bookHTML(r){
  const o = bookOf(r), x = bookPick(o); if(!x) return "";
  const lbl = PONE[o.stat] ? "" : '<b>'+(x.two ? "o"+(x.k-0.5) : x.k+"+")+'</b> ';
  const edge = x.ours - x.book;
  const line = PONE[o.stat] ? (o.stat==="3PM" ? x.k+"+ threes" : BLBL[o.stat]) : (x.two ? "o"+(x.k-0.5) : x.k+"+")+" "+BLBL[o.stat];
  const leg = legOf(shortName(o.name)+" "+line, { ours:x.ours, book:x.book, price:x.price, bk:x.bk, all:x.all, links:x.links, ids:x.ids, game:gInfo(r) });
  return '<div class="bk">'+plBtn(leg)+'Book '+lbl+gPct(x.book)+' · ours '+gPct(x.ours)+' · '+gPrice(x.price)+' <em>'+x.bk+'</em>'
    + (edge >= 0.05 ? ' <span class="g-val">+'+Math.round(100*edge)+'%</span>' : '')+'</div>';
}

// ---------- best bets: every priced bet in a game on one scale ----------
const BLBL = { G:"to score", A:"to assist", P:"1+ point", GA:"goal or assist", TD:"anytime TD", BLK:"1+ block", STL:"1+ steal",
  "3PM":"threes", PTS:"pts", REB:"reb", AST:"ast", PRA:"pts+reb+ast", REC:"receptions", CYD:"rec yds", RYD:"rush yds", PYD:"pass yds",
  PTD:"pass TDs", S:"shots on goal" };
function dec(a){ return a > 0 ? 1 + a/100 : 1 + 100/(-a); }
// our number pulled halfway to the book's: the books are sharp and our edges are not proven yet
function betOf(name, label, ours, book, price, bk, kind, game, all, links, ids){
  const adj = book + 0.5*(ours - book);
  return { name, label, ours, book, adj, price, bk, kind, game, all, links, ids, ev: adj*dec(price) - 1 };
}
function bestBets(g){
  const out = [], seen = {};
  for(const r of gRows(g.id)){
    if(hurt(r)) continue;
    for(const st of BSTATS){
      const o = bookOf(r, st), x = bookPick(o); if(!x || x.n < 2) continue;      // priced by at least two books
      // a volume line far from our projection usually means the books know about a role change we don't
      if(!PONE[st] && st !== "S" && Math.abs(o.lam - x.k) > 0.5 * Math.max(x.k, 4)) continue;
      const line = PONE[st] ? (st==="3PM" ? x.k+"+ threes" : BLBL[st]) : (x.two ? "o"+(x.k-0.5) : x.k+"+")+" "+BLBL[st];
      out.push(betOf(shortName(o.name), line, x.ours, x.book, x.price, x.bk, "prop", gInfo(r), x.all, x.links, x.ids));
    }
  }
  for(const v of (g.proj.value||[])){
    const what = v.mk === "Moneyline" || v.mk === "Result" ? [v.side, v.side === "Draw" ? "" : "to win"]
      : v.mk === "Total" ? [v.side, GKIND === "soccer" ? "goals" : GKIND === "hockey" ? "goals" : "points"]
      : v.mk === "Both score" ? ["Both teams to score:", v.side] : [v.side, ""];
    out.push(betOf(what[0], what[1], v.ours, v.book, v.price, v.bk, "game",
      { n: GKIND === "soccer" ? g.home+" v "+g.away : g.away+" @ "+g.home, t: g.t }, v.all, g.proj.links, v.ids));
  }
  return out.filter(b=>b.adj >= 0.2 && b.ours > b.book && b.ev > 0)
    .sort((a,c)=>c.ev - a.ev)
    .filter(b=>{ if(b.kind==="prop"){ if(seen[b.name]) return false; seen[b.name] = 1; } return true; })
    .slice(0, 3);
}
function betHTML(b, top){
  return '<div class="bb'+(top?" top":"")+'">'+plBtn(legOf(b.name+" "+b.label, b))+'<div class="bb-what"><b>'+esc(b.name)+'</b> '+esc(b.label)+'</div>'
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
let PLU = 0, PLBK = null;
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
  return plFresh(st.legs || []);
})();
function plSave(v){ PLU = Date.now(); try { localStorage.setItem(PLKEY, JSON.stringify({ u:PLU, legs:v, bk:PLBK })); } catch(e){} plLinks(); }
// every link to another HQ site carries the slip
function plLinks(){
  const tag = PLU ? "pl=" + plEnc({ u:PLU, legs:PL, bk:PLBK }) : "";
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
function plBtn(leg){
  const on = PL.some(l=>l.i===leg.i);
  return '<button class="pl-add'+(on?" on":"")+'" data-leg="'+encodeURIComponent(JSON.stringify(leg))+'" aria-label="Add to parlay">'+(on?"✓":"+")+'</button>';
}
const BKHOME = { DK:"https://sportsbook.draftkings.com", FD:"https://sportsbook.fanduel.com", MGM:"https://sports.betmgm.com",
  CZR:"https://sportsbook.caesars.com", FAN:"https://sportsbook.fanatics.com", ESPN:"https://espnbet.com", BR:"https://www.betrivers.com",
  HR:"https://app.hardrock.bet" };
// links that drop every leg into a book's bet slip (null when a leg has no id at that book)
function slipUrl(bk, legs){
  const ids = legs.map(l=>(l.x||{})[bk]);
  if(!ids.length || ids.some(x=>!x)) return null;
  if(bk === "DK" || bk === "FD" || bk === "FAN") return "https://total-hq.com/betlink?bk=" + bk + "&ids=" + ids.join(",");
  if(bk === "MGM") return "https://sports.betmgm.com/en/sports?options=" + ids.map(encodeURIComponent).join(",");
  return null;
}
const BKNAME = { DK:"DraftKings", FD:"FanDuel", MGM:"BetMGM", CZR:"Caesars", FAN:"Fanatics", ESPN:"ESPN Bet", BR:"BetRivers", HR:"Hard Rock", BOV:"Bovada", PIN:"Pinnacle" };
function amer(d){ return d >= 2 ? Math.round((d-1)*100) : Math.round(-100/(d-1)); }
// a parlay is placed at one book, so it is priced book by book from that book's own prices
function plMath(legs){
  const ours = legs.reduce((a,l)=>a*l.o, 1), book = legs.reduce((a,l)=>a*l.k, 1);
  const prices = l => l.a || { [l.b]: l.p };
  const books = [...new Set(legs.flatMap(l=>Object.keys(prices(l))))].map(bk=>{
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
    const p = at(l), url = pick && l.u && l.u[pick.bk];
    const px = p == null ? '<span class="pl-no">not at '+esc(BKNAME[pick.bk]||pick.bk)+'</span>' : gPrice(p)+' <em>'+esc(pick.bk)+'</em>';
    return '<div class="pl-leg"><div><b>'+esc(l.l)+'</b><span>'+esc(l.g||"")+(url ? ' · <a href="'+esc(url)+'" target="_blank" rel="noopener">open game</a>' : '')+'</span></div>'
      + '<div class="pl-p">'+px+'</div><button class="pl-x" data-i="'+i+'" aria-label="Remove">✕</button></div>';
  };
  const bookRow = b=>'<button class="pl-bk'+(pick&&b.bk===pick.bk?" on":"")+(b.n<PL.length?" part":"")+'" data-bk="'+b.bk+'"><span>'+esc(BKNAME[b.bk]||b.bk)+'</span>'
    + (b.n === PL.length ? '<b>'+gPrice(b.price)+'</b>' : '<i>'+b.n+' of '+PL.length+' legs</i>')+'</button>';
  const games = [...new Set(PL.map(l=>l.g))];
  const oneGameUrl = pick && games.length === 1 ? (PL.find(l=>l.u && l.u[pick.bk])||{u:{}}).u[pick.bk] : null;
  const slip = pick && full ? slipUrl(pick.bk, PL) : null;
  const placeUrl = pick ? (slip || oneGameUrl || BKHOME[pick.bk]) : null;
  el.innerHTML = (PLOPEN ? '<div class="pl-legs">'+PL.map(legLine).join("")
      + '<div class="pl-where"><div class="pl-wt">Tap a sportsbook to price your parlay there</div>'+all.slice(0, 8).map(bookRow).join("")+'</div>'
      + (m.full.length ? '' : '<p class="pl-note pl-warn">No single sportsbook has every leg right now. Remove a leg or swap it for one your book has.</p>')
      + (m.sameGame ? '<p class="pl-note">Some legs share a game. Books price same-game parlays their own way, so the price there may differ.</p>' : '')
      + '<div class="pl-acts">'+(placeUrl ? '<a class="navbtn pl-go" href="'+esc(placeUrl)+'" target="_blank" rel="noopener">'+(slip ? 'Add to '+esc(BKNAME[pick.bk]||pick.bk)+' bet slip' : 'Open '+esc(BKNAME[pick.bk]||pick.bk))+'</a>' : '')
      + '<button class="navbtn" id="pl-copy">Copy legs</button></div>'
      + '<p class="pl-note">'+(slip ? 'Loads every leg into your '+esc(BKNAME[pick.bk]||pick.bk)+' bet slip. ' : (oneGameUrl ? 'Opens this game at '+esc(BKNAME[pick.bk]||pick.bk)+'. ' : 'Opens '+esc(BKNAME[pick.bk]||pick.bk||"the book")+'; add each leg there, or tap "open game" on a leg. ')
        + 'FanDuel, DraftKings, Fanatics and BetMGM can load the whole slip. ')+'Your parlay follows you to every HQ site.</p>'
      + '<div class="pl-acts"><button class="navbtn" id="pl-clear">Clear</button><a class="navbtn" href="https://total-hq.com/" style="text-align:center;text-decoration:none">See it on Total HQ</a></div></div>' : '')
    + '<button class="pl-head" id="pl-toggle"><span>Parlay · '+PL.length+' leg'+(PL.length>1?"s":"")+(pick ? ' · '+esc(BKNAME[pick.bk]||pick.bk) : '')+'</span>'
    + '<b>'+(full ? gPrice(pick.price) : '—')+'</b><span class="pl-ch">'+(full ? 'ours '+gPct(m.ours)+' · book '+gPct(m.book) : pick ? pick.n+' of '+PL.length+' legs at this book' : '')+'</span></button>';
  el.querySelectorAll(".pl-bk[data-bk]").forEach(b=> b.onclick = ()=>{ PLBK = b.dataset.bk; plSave(PL); plBar(); });
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
/* ===== end games view ===== */
