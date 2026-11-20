#!/usr/bin/env python3
"""Add the shared results dashboard and starred players to a site's worker.js. Run once per site."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITES = {
    "slapshot": ("nhl", '[["G","Goals","goals"],["A","Assists","assists"],["P","Points","points"],["S","SOG","shots on goal"]]'),
    "slam": ("nba", '[["PTS","PTS","points"],["PRA","PRA","points + rebounds + assists"],["REB","REB","rebounds"],["AST","AST","assists"],["3PM","3PM","threes"],["BLK","BLK","blocks"],["STL","STL","steals"]]'),
    "touchdown": ("nfl", '[["TD","TD","touchdowns"],["CYD","REC YDS","receiving yards"],["RYD","RUSH YDS","rushing yards"],["REC","REC","receptions"],["PYD","PASS YDS","passing yards"],["PTD","PASS TD","passing TDs"]]'),
    "golazo": ("soccer", '[["G","Goals","goals"],["T","SOT","shots on target"],["S","Shots","shots"],["A","Assists","assists"]]'),
}


def tl(js):
    """Escape plain JS for the HTML template literal inside worker.js."""
    return js.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def one(s, pattern, repl, flags=0):
    new, k = re.subn(pattern, repl, s, count=1, flags=flags)
    if not k:
        raise SystemExit(f"anchor not found: {pattern[:70]}")
    return new


def main(site):
    sport, rstats = SITES[site]
    p = Path("sites") / site / "worker.js"
    s = p.read_text()
    if "results dashboard" in s:
        raise SystemExit(f"{site}: already has the dashboard")

    # worker: history endpoints
    s = one(s, r'(const BOARD_URL = "[^"]+";\n)', r'\1const HISTORY_URL = "https://raw.githubusercontent.com/mattgrnr/hq-data/main/' + sport + '/history/summary.json";\n')
    s = one(s, r'(\n    if \(path === "/board"\) \{)', lambda m: '''
    if (path === "/history" || path === "/history/day") {
      if (!fromSite(request)) return new Response("Forbidden", { status: 403 });
      const d = url.searchParams.get("d") || "";
      if (path === "/history/day" && !/^\\d{4}-(\\d{2}-\\d{2}|w\\d{2})$/.test(d)) return new Response("Bad request", { status: 400 });
      const src = path === "/history" ? HISTORY_URL : HISTORY_URL.replace("summary.json", "graded/" + d + ".json");
      const res = await fetch(src, { cf: { cacheTtl: 600, cacheEverything: true } });
      if (!res.ok) return new Response(JSON.stringify({ error: "history upstream " + res.status }), { status: 502, headers: { "Content-Type": "application/json" } });
      return new Response(res.body, { headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=300" } });
    }
''' + m.group(1))

    # styles
    css = (HERE / "dash.css").read_text()
    s = one(s, r"\n</style>", lambda m: "\n" + css + "</style>")

    # script: shared dashboard before rowHTML
    js = (HERE / "dash.js").read_text()
    head = f'const RSTATS = {rstats};\nconst FAVKEY = "hq.{site}.fav";\n'
    pinned = '''function pinnedHTML(rows){
  const fav = favSet(), pinned = [];
  rows.forEach((r,i)=>{ if(fav.has(String(r.p.id))) pinned.push([r,i]); });
  return pinned.length ? '<div class="favhead">Your players</div>' + pinned.map(x=>rowHTML(x[0], x[1])).join("") + '<div class="favhead all">Full board</div>' : '';
}
function wireTop(){
  document.getElementById("btn-refresh").onclick = ()=>boot(true);
  const rb = document.getElementById("btn-results");
  if(rb) rb.onclick = ()=>{ F.view = F.view === "results" ? "board" : "results"; window.scrollTo(0,0); if(F.view === "board" && !GAMES.length) boot(false); else render(); };
  const sb = document.getElementById("btn-sports"), sm = document.getElementById("sportmenu");
  if(sb && sm){
    sb.onclick = (e)=>{ e.stopPropagation(); sm.classList.toggle("open"); };
    document.addEventListener("click", ()=>sm.classList.remove("open"));
  }
}
'''
    s = one(s, r"\nfunction rowHTML\(", lambda m: "\n" + tl(head + js + pinned) + "\nfunction rowHTML(")
    s = one(s, r"(let F = \{[^\n]*?)( \};)", r'\1, view:"board"\2')

    # star on each row, just before the projection
    i = s.index("function rowHTML(")
    j = s.index("\n}\n", i)
    body = s[i:j]
    body = one(body, r"\n(    \+ (proj\n|'<div class=\"yproj\">|projCell\(r\)))", lambda m: "\n    + starHTML(r.p.id, r.p.name || r.p.n)\n" + m.group(1))
    s = s[:i] + body + s[j:]

    # header: Results button, and the results view
    s = one(s, r"'<button class=\"navbtn\" id=\"btn-refresh\">(↻|\\\\u21bb) Refresh</button></div></div></header>';\n",
            lambda m: "'<button class=\"navbtn'+(F.view===\"results\"?\" on\":\"\")+'\" id=\"btn-results\">Results</button><button class=\"navbtn\" id=\"btn-refresh\" aria-label=\"Refresh\">" + m.group(1) + "</button></div></div></header>';\n"
            "  if(F.view === \"results\"){\n    h += resultsHTML();\n    app.innerHTML = h;\n    wireTop();\n    wireResults();\n    loadHistory();\n    return;\n  }\n")

    # starred players pinned above the board
    s = one(s, r"rows\.length \? rows\.", "rows.length ? pinnedHTML(rows) + rows.")

    # wiring on the board view
    s = one(s, r"(function wire\(\)\{\n  document\.getElementById\(\"btn-refresh\"\)\.onclick = \(\)=>boot\(true\);\n)",
            lambda m: m.group(1) + "  const rb = document.getElementById(\"btn-results\");\n  if(rb) rb.onclick = ()=>{ F.view = \"results\"; window.scrollTo(0,0); render(); };\n  wireStars();\n")

    # a day with no games can still open results
    m = re.search(r"\n(\s+)app\.innerHTML = '<div class=\"status\"><div class=\"big\">[^\n]*No games[^\n]*\n\s+document\.getElementById\(\"btn-refresh\"\)\.onclick = \(\)=>boot\(true\);\n", s)
    if m:
        ind = m.group(1)
        blk = m.group(0)
        new = blk.replace("app.innerHTML", "ROWS = [];\n" + ind + "if(F.view === \"results\"){ render(); return; }\n" + ind + "app.innerHTML", 1)
        new = re.sub(r"(<button class=\"navbtn\" id=\"btn-refresh\">)", r'<button class="navbtn" id="btn-results">See how the board did</button> \1', new, count=1)
        new += ind + "document.getElementById(\"btn-results\").onclick = ()=>{ F.view = \"results\"; render(); };\n"
        s = s.replace(blk, new, 1)

    p.write_text(s)
    print(f"{site}: dashboard added")


if __name__ == "__main__":
    for site in sys.argv[1:]:
        main(site)
