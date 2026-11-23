#!/usr/bin/env python3
"""Show every factor bar in a player's detail as a percentile of today's board, with the raw value beside it.

usage: pct_bars.py <site> [<site> ...]   (slapshot slam touchdown futbol); safe to rerun
"""
import re
import sys
from pathlib import Path

# who a bar is ranked against: everyone on today's board for the tab being viewed
POP = {"slapshot": "ROWS", "slam": "ROWS", "touchdown": "tabRows()", "futbol": "dayRows()"}

HELPERS = r"""/* ===== percentile bars ===== */
// each bar ranks the player against everyone on today's board for this tab: 96th = ahead of 96% of them
let PCT = null;
function pctKey(label){ return String(label).split(" · ")[0]; }
function pctNote(label, idx){
  if(!PCT || !PCT.on) return false;
  const k = pctKey(label);
  if(typeof idx === "number" && isFinite(idx)) (PCT.m[k] = PCT.m[k] || []).push(idx);
  return true;
}
function pctOf(label, idx){
  const k = pctKey(label);
  if(k.indexOf("vs ") === 0 || typeof idx !== "number" || !isFinite(idx)) return null;
  const key = F.stat + "|" + (F.day == null ? "" : F.day);
  if(!PCT || PCT.key !== key || PCT.rows !== ROWS){
    PCT = { key:key, rows:ROWS, m:{}, on:true };
    try{ __POP__.forEach(r=>{ try{ detailHTML(r); }catch(e){} }); } finally { PCT.on = false; }
  }
  const a = PCT.m[k];
  if(!a || a.length < 8) return null;
  let below = 0, same = 0;
  for(const v of a){ if(v < idx - 1e-9) below++; else if(v <= idx + 1e-9) same++; }
  return clamp(Math.round((below + same/2) / a.length * 100), 1, 99);
}
function pctClass(pc){ return pc >= 80 ? " hi" : pc <= 20 ? " lo" : ""; }
/* ===== end percentile bars ===== */
"""

BAR = r"""function bar(label, idx, val, expl){
  if(pctNote(label, idx)) return "";
  const pc = pctOf(label, idx);
  const w = pc != null ? clamp(pc, 3, 100) : clamp(idx/2*100, 4, 100);
  return '<div class="bar'+(pc != null ? pctClass(pc) : '')+'" onclick="this.classList.toggle(\\'show\\')">'
    + '<div class="bl"><span>'+esc(label)+'</span><b>'+(pc != null ? '<em>'+ordn(pc)+'</em><small>'+val+'</small>' : val)+'</b></div>'
    + '<div class="track"><i style="width:'+w.toFixed(1)+'%"></i></div>'
    + (expl ? '<div class="bexp">'+expl+'</div>' : '') + '</div>';
}"""

CSS = r"""/* percentile bars */
#app .bar{grid-template-columns:minmax(104px,150px) 1fr 58px}
#app .bar .bl span{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.25}
#app .bar .bl b{display:flex;flex-direction:column;align-items:flex-end;line-height:1.1}
#app .bar .bl b em{font-style:normal;font-size:13.5px;font-weight:700}
#app .bar .bl b small{font-size:10.5px;font-weight:500;color:var(--faint);margin-top:2px}
#app .bar.hi .bl b em{color:var(--ink)}
#app .bar.lo .bl b em{color:var(--faint)}
#app .bar.lo .track i{opacity:.55}
"""

LEGEND = ("Each bar ranks him against <b>everyone on today's board</b> for this stat: <b>90th</b> means he's ahead of 90% of them, "
          "and the tick in the middle is the 50th. The small number under it is the raw figure. Tap any bar to see what it means.")

ORDN = """function ordn(n){
  const s = ["th","st","nd","rd"], v = n % 100;
  return n + (s[(v-20)%10] || s[v] || s[0]);
}
"""


def main(site):
    p = Path("sites") / site / "worker.js"
    s = p.read_text()
    h = HELPERS.replace("__POP__", POP[site])
    if "/* ===== percentile bars ===== */" in s:
        a = s.index("/* ===== percentile bars ===== */"); b = s.index("/* ===== end percentile bars ===== */") + len("/* ===== end percentile bars ===== */\n")
        s = s[:a] + h + s[b:]
    else:
        s = s.replace("\nfunction bar(label", "\n" + h + "function bar(label", 1)
    if site == "futbol" and "function ordn(" not in s:
        s = s.replace("function pct(p){", ORDN + "function pct(p){", 1)
    i = s.index("function bar(label"); j = s.index("\n}", i) + 2
    s = s[:i] + BAR + s[j:]
    # legend: keep each site's first sentence about baselines, swap the 1.00 tick sentence
    s = re.sub(r"The tick in the middle is <b>1\.00[^<]*</b>[^<]*?Tap any bar to see what it means\.",
               lambda m: "The raw number is an index where <b>1.00</b> is that baseline. " + LEGEND.replace("'", "\u2019"), s)
    if "/* percentile bars */" not in s:
        k = s.index("#app .bar .bexp{")
        k = s.index("\n", k) + 1
        s = s[:k] + CSS + s[k:]
    p.write_text(s)
    print(site, "ok")


if __name__ == "__main__":
    for site in sys.argv[1:]:
        main(site)
