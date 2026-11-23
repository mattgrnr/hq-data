#!/usr/bin/env python3
"""Add the shared Games view to a site's worker.js; later runs refresh it in place.

usage: inject.py <site> [<site> ...]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS_START, JS_END = "/* ===== games view:", "/* ===== end games view ===== */"
CSS_START = "/* ===== games view (shared) ===== */"
DASH_JS, DASH_CSS = "/* ===== results dashboard:", "/* ===== results dashboard + starred players (shared) ===== */"

ROWS_OF = {"slapshot": "sortedRows()", "slam": "sorted()", "touchdown": "tabRows()", "futbol": "sortedRows()"}
BOOKOF = {
    "slapshot": 'function bookOf(r, st){ st = st || F.stat; return { name:r.p.name, stat:st, lam:{ G:r.projG, A:r.projA, P:r.projP, S:r.projS }[st] }; }\n'
                'const BSTATS = ["G","A","P","S"]; function hurt(r){ return false; }\n',
    "slam": 'function bookOf(r, st){ st = st || F.stat; return { name:r.p.name, stat:st, lam:r.proj[KEY[st]] }; }\n'
            'const BSTATS = STATS; function hurt(r){ return !!injOf(r.p); }\n',
    "touchdown": 'function bookOf(r, st){ st = st || F.stat; const x = r.tab && r.tab[st]; return { name:r.p.name, stat:st, lam:st==="TD" ? r.projTD : x && x.proj }; }\n'
                 'const BSTATS = ["TD","CYD","RYD","REC","PYD","PTD"]; function hurt(r){ return !!r.p.st; }\n',
    "futbol": 'function bookOf(r, st){ st = st || F.stat; const p = r.p; return { name:p.n, stat:st, lam:{ G:p.pg, A:p.pa, GA:p.pg+p.pa, T:p.psot, S:p.psh }[st] }; }\n'
              'const BSTATS = ["G","A","GA"]; function hurt(r){ return r.p.st === "bench"; }\n',
}
GLUE = {
    "slapshot": 'const PTABS = [["G","Goals"],["A","Assists"],["P","Points"],["S","SOG"]];\nfunction logCols(r){ return [["TOI",s=>s.toi],["G",s=>s.g,"G"],["A",s=>s.a,"A"],["PTS",s=>s.g+s.a,"P"],["SOG",s=>s.sog,"S"]]; }\n' + 'const GKIND = "hockey", PSITE = "Slapshot";\nfunction gList(){ return GAMES.map(g=>({ id:g.id, home:g.home, away:g.away, when:g.detail, t:g.start, fin:g.final, proj:g.proj })); }\nfunction gInfo(r){ return { n:r.gm.short, t:r.gm.start, f:r.gm.final }; }\n',
    "slam": 'const PTABS = STATS.map(x=>[x, x]);\nfunction logCols(r){ return [["MIN",s=>s.min],["PTS",s=>s.pts,"PTS"],["REB",s=>s.reb,"REB"],["AST",s=>s.ast,"AST"],["PRA",s=>s.pts+s.reb+s.ast,"PRA"],["3PM",s=>s.fg3m,"3PM"],["STL",s=>s.stl,"STL"],["BLK",s=>s.blk,"BLK"]]; }\n' + 'const GKIND = "points", PSITE = "Slam";\nfunction gList(){ return GAMES.map(g=>({ id:g.id, home:g.home, away:g.away, when:g.detail, t:g.start, fin:g.final, proj:g.proj })); }\nfunction gInfo(r){ return { n:r.gm.short, t:r.gm.start, f:r.gm.final }; }\n',
    "touchdown": 'const PTABS = TABS;\nfunction logCols(r){ return r.p.pos === "QB" ? [["PYD",s=>s.pyd,"PYD"],["PTD",s=>s.ptd,"PTD"],["RUSH YDS",s=>s.ryd,"RYD"],["TD",s=>s.rtd+s.ctd,"TD"]]\n  : [["TGT",s=>s.tgt],["REC",s=>s.rec,"REC"],["REC YDS",s=>s.cyd,"CYD"],["CAR",s=>s.car],["RUSH YDS",s=>s.ryd,"RYD"],["TD",s=>s.rtd+s.ctd,"TD"]]; }\n' + 'const GKIND = "points", PSITE = "Touchdown";\nfunction gList(){ return GAMES.map(g=>({ id:g.id, home:g.home, away:g.away, when:g.detail, t:g.ko ? g.ko*1000 : null, fin:g.final, proj:g.proj })); }\nfunction gInfo(r){ return { n:r.gm.short, t:r.gm.ko ? r.gm.ko*1000 : null, f:r.gm.final }; }\n',
    "futbol": 'const PTABS = TABS;\nfunction logCols(r){ return [["MIN",s=>s.min],["G",s=>s.g,"G"],["A",s=>s.a,"A"],["G+A",s=>s.g+s.a,"GA"],["SOT",s=>s.sot,"T"],["SH",s=>s.sh,"S"]]; }\n' + 'const GKIND = "soccer", PSITE = "Futbol";\nfunction gList(){ return dayGames().filter(g=>F.lg==="all" || String(g.lid)===F.lg).map(g=>({ id:String(g.id), home:g.h, away:g.a, lg:g.league,\n  when:new Date(g.t).toLocaleTimeString([], { hour:"numeric", minute:"2-digit" }), t:Date.parse(g.t), proj:g.proj })); }\nfunction gInfo(r){ return { n:r.gm.h+" v "+r.gm.a, t:Date.parse(r.gm.t) }; }\n',
}


def tl(js):
    return js.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def block(site):
    rows = f"function gRows(id){{ return {ROWS_OF[site]}.filter(r=>String(r.gm.id)===String(id)); }}\n"
    return tl((HERE / "games.js").read_text().rstrip("\n").replace(JS_END, GLUE[site] + BOOKOF[site] + rows + JS_END) + "\n")


def one(s, pat, repl, flags=0):
    new, k = re.subn(pat, repl, s, count=1, flags=flags)
    if not k:
        raise SystemExit(f"anchor not found: {pat[:80]}")
    return new


def book_rows(s):
    """Put bookHTML(r) at the end of the player block in rowHTML, once."""
    if "bookHTML(r)" in s.split(JS_END)[-1]:
        return s
    i = s.index("function rowHTML(", s.index(JS_END))
    j = s.index("\n}\n", i)
    body = s[i:j]
    if "statLine(r, k)+'</div>'" in body:
        body = body.replace("statLine(r, k)+'</div>'", "statLine(r, k)+bookHTML(r)+'</div>'", 1)
    else:
        k = body.index("<div class=\"meta\">")
        e = body.index("</div></div>'", k)
        body = body[:e] + "</div>'+bookHTML(r)+'</div>'" + body[e + len("</div></div>'"):]
    return s[:i] + body + s[j:]


def main(site):
    p = Path("sites") / site / "worker.js"
    s = p.read_text()
    css = (HERE / "games.css").read_text()
    if JS_START in s:
        a = s.index(JS_START); b = s.index(JS_END, a) + len(JS_END) + 1
        s = s[:a] + block(site) + s[b:]
        a = s.index(CSS_START); b = s.index(JS_END, a) + len(JS_END) + 1
        s = s[:a] + css + s[b:]
        s = book_rows(s)
        p.write_text(s)
        print(f"{site}: games view refreshed")
        return
    s = s.replace(DASH_CSS, css + DASH_CSS, 1)
    s = s.replace(DASH_JS, block(site) + DASH_JS, 1)
    if site != "futbol":
        s = one(s, r"(function parseSlate\([a-z]+\)\{\n  return \([a-z]+\.games\|\|\[\]\)\.map\(function\(g,ix\)\{ return \{\n)", r"\1    proj: g.proj,\n")
    # the Games tab, first in the tab row
    s = one(s, r"""  h \+= '<div class="posrow">'\+(.*?)\(F\.stat===""",
            lambda m: """  h += '<div class="posrow"><div class="pos'+(GV?" on":"")+'" data-stat="GAMES">GAMES</div>'+""" + m.group(1) + "(!GV&&F.stat===")
    s = one(s, r"""(  h \+= '<div class="posrow">[^\n]*\n)""", lambda m: m.group(1) + "  if(GV){ h += gamesHTML(); app.innerHTML = h; wire(); return; }\n")
    s = one(s, r"""(  document\.querySelectorAll\("\.pos"\)\.forEach\(el=> el\.onclick = \(\)=>\{ )([^\n]*\n)""",
            lambda m: m.group(1) + 'if(el.dataset.stat==="GAMES"){ GV = true; render(); return; } GV = false; ' + m.group(2) + "  if(GV){ wireGames(); return; }\n")
    s = book_rows(s)
    p.write_text(s)
    print(f"{site}: games view added")


if __name__ == "__main__":
    for site in sys.argv[1:]:
        main(site)
