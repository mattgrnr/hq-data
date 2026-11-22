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
    "slapshot": 'function bookOf(r){ return { name:r.p.name, stat:F.stat, lam:{ G:r.projG, A:r.projA, P:r.projP, S:r.projS }[F.stat] }; }\n',
    "slam": 'function bookOf(r){ return { name:r.p.name, stat:F.stat, lam:r.proj[KEY[F.stat]] }; }\n',
    "touchdown": 'function bookOf(r){ const x = r.tab && r.tab[F.stat]; return { name:r.p.name, stat:F.stat, lam:F.stat==="TD" ? r.projTD : x && x.proj }; }\n',
    "futbol": 'function bookOf(r){ const p = r.p; return { name:p.n, stat:F.stat, lam:{ G:p.pg, A:p.pa, GA:p.pg+p.pa, T:p.psot, S:p.psh }[F.stat] }; }\n',
}
GLUE = {
    "slapshot": 'const GKIND = "hockey";\nfunction gList(){ return GAMES.map(g=>({ id:g.id, home:g.home, away:g.away, when:g.detail, proj:g.proj })); }\n',
    "slam": 'const GKIND = "points";\nfunction gList(){ return GAMES.map(g=>({ id:g.id, home:g.home, away:g.away, when:g.detail, proj:g.proj })); }\n',
    "touchdown": 'const GKIND = "points";\nfunction gList(){ return GAMES.map(g=>({ id:g.id, home:g.home, away:g.away, when:g.detail, proj:g.proj })); }\n',
    "futbol": 'const GKIND = "soccer";\nfunction gList(){ return dayGames().filter(g=>F.lg==="all" || String(g.lid)===F.lg).map(g=>({ id:String(g.id), home:g.h, away:g.a, lg:g.league,\n  when:new Date(g.t).toLocaleTimeString([], { hour:"numeric", minute:"2-digit" }), proj:g.proj })); }\n',
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
