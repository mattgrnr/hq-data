#!/usr/bin/env python3
"""Add the shared results dashboard and starred players to a site's worker.js.

The first run wires it in; later runs refresh the shared dashboard code and styles in place.
usage: inject.py <site> [<site> ...]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITES = {
    "slapshot": ("nhl", '[["G","Goals","goals"],["A","Assists","assists"],["P","Points","points"],["S","SOG","shots on goal"]]'),
    "slam": ("nba", '[["PTS","PTS","points"],["REB","REB","rebounds"],["AST","AST","assists"],["PRA","PRA","points + rebounds + assists"],["3PM","3PM","threes"],["BLK","BLK","blocks"],["STL","STL","steals"]]'),
    "touchdown": ("nfl", '[["TD","TD","touchdowns"],["CYD","REC YDS","receiving yards"],["RYD","RUSH YDS","rushing yards"],["REC","REC","receptions"],["PYD","PASS YDS","passing yards"],["PTD","PASS TD","passing TDs"]]'),
    "futbol": ("soccer", '[["G","Goals","goals"],["T","SOT","shots on target"],["S","Shots","shots"],["A","Assists","assists"],["GA","TSOA","goals plus assists"]]'),
}
JS_START, JS_END = "/* ===== results dashboard:", "/* ===== end results dashboard ===== */"
CSS_START = "/* ===== results dashboard + starred players (shared) ===== */"

ROUTES = '''
    if (path === "/history" || path === "/history/day" || path === "/history/players") {
      if (!fromSite(request)) return new Response("Forbidden", { status: 403 });
      const d = url.searchParams.get("d") || "";
      if (path === "/history/day" && !/^\\d{4}-(\\d{2}-\\d{2}|w\\d{2})$/.test(d)) return new Response("Bad request", { status: 400 });
      const src = path === "/history" ? HISTORY_URL : path === "/history/players" ? HISTORY_URL.replace("summary.json", "players.json")
        : HISTORY_URL.replace("summary.json", "graded/" + d + ".json");
      const res = await fetch(src, { cf: { cacheTtl: 600, cacheEverything: true } });
      if (!res.ok) return new Response(JSON.stringify({ error: "history upstream " + res.status }), { status: 502, headers: { "Content-Type": "application/json" } });
      return new Response(res.body, { headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=300" } });
    }
'''

GLUE = '''function pinnedHTML(rows){
  const fav = favSet(), pinned = [];
  rows.forEach((r,i)=>{ if(fav.has(String(r.p.id))) pinned.push([r,i]); });
  return pinned.length ? '<div class="favhead">Your players</div>' + pinned.map(x=>rowHTML(x[0], x[1])).join("") + '<div class="favhead all">Full board</div>' : '';
}
function wireTop(){
  document.getElementById("btn-refresh").onclick = ()=>boot(true);
  const rb = document.getElementById("btn-results");
  if(rb) rb.onclick = ()=>{ if(F.view === "results") history.back(); else openResults(); };
  const sb = document.getElementById("btn-sports"), sm = document.getElementById("sportmenu");
  if(sb && sm){
    sb.onclick = (e)=>{ e.stopPropagation(); sm.classList.toggle("open"); };
    document.addEventListener("click", ()=>sm.classList.remove("open"));
  }
}
'''


def tl(js):
    """Escape plain JS for the HTML template literal inside worker.js."""
    return js.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def one(s, pattern, repl, flags=0):
    new, k = re.subn(pattern, repl, s, count=1, flags=flags)
    if not k:
        raise SystemExit(f"anchor not found: {pattern[:70]}")
    return new


def refresh(site, s):
    """Swap in the current shared code and styles."""
    sport, rstats = SITES[site]
    js = tl((HERE / "dash.js").read_text())
    a = s.index(JS_START)
    b = s.index(JS_END, a) + len(JS_END) + 1
    s = s[:a] + js + s[b:]
    s = re.sub(r"const RSTATS = [^\n]*;\n", lambda m: f"const RSTATS = {rstats};\n", s, count=1)
    css = (HERE / "dash.css").read_text()
    a = s.index(CSS_START)
    b = s.index(JS_END, a) + len(JS_END) + 1
    return s[:a] + css + s[b:]


def install(site, s):
    sport, rstats = SITES[site]
    s = one(s, r'(const BOARD_URL = "[^"]+";\n)', r'\1const HISTORY_URL = "https://raw.githubusercontent.com/mattgrnr/hq-data/main/' + sport + '/history/summary.json";\n')
    s = one(s, r'(\n    if \(path === "/board"\) \{)', lambda m: ROUTES + m.group(1))
    s = one(s, r"\n</style>", lambda m: "\n" + (HERE / "dash.css").read_text() + "</style>")
    head = f'const RSTATS = {rstats};\nconst FAVKEY = "hq.{site}.fav";\n'
    s = one(s, r"\nfunction rowHTML\(", lambda m: "\n" + tl(head + (HERE / "dash.js").read_text() + GLUE) + "\nfunction rowHTML(")
    s = one(s, r"(let F = \{[^\n]*?)( \};)", r'\1, view:"board"\2')

    # star on each row, just before the projection
    i = s.index("function rowHTML(")
    j = s.index("\n}\n", i)
    body = one(s[i:j], r"\n(    \+ (proj\n|'<div class=\"yproj\">|projCell\(r\)))", lambda m: "\n    + starHTML(r.p.id, r.p.name || r.p.n)\n" + m.group(1))
    s = s[:i] + body + s[j:]

    # header: the dashboard button, and the dashboard view
    s = one(s, r"'<button class=\"navbtn\" id=\"btn-refresh\">(↻|\\\\u21bb) Refresh</button></div></div></header>';\n",
            lambda m: "'<button class=\"navbtn'+(F.view===\"results\"?\" on\":\"\")+'\" id=\"btn-results\">Results Dashboard</button><button class=\"navbtn\" id=\"btn-refresh\" aria-label=\"Refresh\">" + m.group(1) + "</button></div></div></header>';\n"
            "  if(F.view === \"results\"){\n    h += resultsHTML();\n    app.innerHTML = h;\n    wireTop();\n    wireResults();\n    wireBrand();\n    loadHistory();\n    return;\n  }\n")

    # starred players pinned above the board
    s = one(s, r"rows\.length \? rows\.", "rows.length ? pinnedHTML(rows) + rows.")

    # wiring on the board view
    s = one(s, r"(function wire\(\)\{\n  document\.getElementById\(\"btn-refresh\"\)\.onclick = \(\)=>boot\(true\);\n)",
            lambda m: m.group(1) + "  const rb = document.getElementById(\"btn-results\");\n  if(rb) rb.onclick = ()=> openResults();\n  wireStars();\n")

    # a day with no games can still open the dashboard
    m = re.search(r"\n(\s+)app\.innerHTML = '<div class=\"status\"><div class=\"big\">[^\n]*No games[^\n]*\n\s+document\.getElementById\(\"btn-refresh\"\)\.onclick = \(\)=>boot\(true\);\n", s)
    if m:
        ind, blk = m.group(1), m.group(0)
        new = blk.replace("app.innerHTML", "ROWS = [];\n" + ind + "if(F.view === \"results\"){ render(); return; }\n" + ind + "app.innerHTML", 1)
        new = re.sub(r"(<button class=\"navbtn\" id=\"btn-refresh\">)", r'<button class="navbtn" id="btn-results">See how the board did</button> \1', new, count=1)
        new += ind + "document.getElementById(\"btn-results\").onclick = ()=> openResults();\n"
        s = s.replace(blk, new, 1)
    return s


def main(site):
    p = Path("sites") / site / "worker.js"
    s = p.read_text()
    if JS_START in s:
        s = refresh(site, s)
        print(f"{site}: dashboard refreshed")
    else:
        s = install(site, s)
        print(f"{site}: dashboard added")
    p.write_text(s)


if __name__ == "__main__":
    for site in sys.argv[1:]:
        main(site)
