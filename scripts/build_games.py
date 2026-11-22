#!/usr/bin/env python3
"""Project every game on a sport's board: winner chances, score, spread and total.

Reads <sport>/board.json (or the file given) and writes a "proj" block into each game:
  hs, as     projected home and away score
  win        [home, away] chances, or [home, draw, away] for soccer
  spread     our home line (negative = home favored), to the half point
  total      our projected total, and over: [line, chance] at the usual half-point line
  cover      chance the home side covers our spread's nearest book-style line (NFL uses the book's line)
usage: build_games.py <nhl|nba|nfl|soccer> [board.json]
"""
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIG_FIVE = {47, 87, 55, 54, 53}


def pois(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def grid(lh, la, n=15):
    """Joint chances of each scoreline, home goals by away goals."""
    ph, pa = [pois(lh, k) for k in range(n)], [pois(la, k) for k in range(n)]
    return [[ph[i] * pa[j] for j in range(n)] for i in range(n)]


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def half(x):
    """Nearest half point, the way books post lines."""
    return math.floor(x) + 0.5


def r1(x):
    return round(x, 1)


def low_scoring(lh, la, line, ot_home=0.52):
    """Hockey: regulation from Poisson, a tie goes to overtime."""
    g = grid(lh, la)
    hw = sum(g[i][j] for i in range(15) for j in range(15) if i > j)
    aw = sum(g[i][j] for i in range(15) for j in range(15) if i < j)
    tie = 1 - hw - aw
    home = hw + tie * ot_home
    fav_home = lh >= la
    # puck line: the favorite by 2 or more
    pl = sum(g[i][j] for i in range(15) for j in range(15) if (i - j >= 2 if fav_home else j - i >= 2))
    over = sum(g[i][j] for i in range(15) for j in range(15) if i + j > line)
    return {"hs": r1(lh), "as": r1(la), "win": [round(home, 3), round(1 - home, 3)],
            "spread": -1.5 if fav_home else 1.5, "cover": round(pl, 3),
            "total": r1(lh + la), "over": [line, round(over, 3)]}


def nhl(bd):
    lg, T = bd["lg"], bd["teams"]
    base = lg["gf"]
    for gm in bd["games"]:
        h, a = T.get(gm["home"]), T.get(gm["away"])
        if not h or not a:
            continue
        att = lambda t: (0.5 * t["gf"] + 0.5 * t["xgf"] * base / lg["xg"]) / base
        dfn = lambda t: (0.5 * t["ga"] + 0.5 * t["xga"] * base / lg["xg"]) / base
        lh = base * att(h) * dfn(a) * 1.04
        la = base * att(a) * dfn(h) / 1.04
        gm["proj"] = low_scoring(lh, la, 6.5 if lh + la >= 5.75 else 5.5)


def points_game(hs, as_, sd_margin, sd_total, book_spread=None, book_total=None):
    """Basketball and football: normal margin and total around the projected score."""
    margin = hs - as_
    spread = -round(margin * 2) / 2
    line = book_spread if book_spread is not None else spread
    total_line = book_total if book_total is not None else half(hs + as_)
    out = {"hs": r1(hs), "as": r1(as_), "win": [round(ncdf(margin / sd_margin), 3), round(1 - ncdf(margin / sd_margin), 3)],
           "spread": spread, "total": r1(hs + as_),
           "cover": round(ncdf((margin + line) / sd_margin), 3),     # home covers `line` (home perspective)
           "over": [total_line, round(1 - ncdf((total_line - hs - as_) / sd_total), 3)]}
    if book_spread is not None:
        out["book"] = {"spread": book_spread, "total": book_total}
    return out


def nba(bd):
    T, pace_lg = bd["teams"], bd["lg"]["pace"]
    pf_lg = sum(t.get("pf", 0) for t in T.values()) / max(1, sum(1 for t in T.values() if t.get("pf")))
    rtg_lg = pf_lg / pace_lg
    for gm in bd["games"]:
        h, a = T.get(gm["home"]), T.get(gm["away"])
        if not h or not a or not h.get("pf") or not a.get("pf"):
            continue
        pace = h["pace"] * a["pace"] / pace_lg
        o = lambda t: t["pf"] / t["pace"]
        d = lambda t: t["pa"] / t["pace"]
        hs = o(h) * d(a) / rtg_lg * pace + 1.4
        as_ = o(a) * d(h) / rtg_lg * pace - 1.4
        gm["proj"] = points_game(hs, as_, 12.5, 18.0)


def nfl(bd):
    T, lg = bd.get("teams") or {}, (bd.get("lg") or {}).get("ppg", 22.5)
    for gm in bd["games"]:
        h, a = T.get(gm["home"]), T.get(gm["away"])
        if not h or not a:
            continue
        hs = h["pf"] * a["pa"] / lg + 0.9
        as_ = a["pf"] * h["pa"] / lg - 0.9
        # nflverse spread_line is the home side's edge in points; as a betting line the home spread is its negative
        bs = -gm["spread"] if gm.get("spread") is not None else None
        gm["proj"] = points_game(hs, as_, 13.5, 13.0, bs, gm.get("total"))


def soccer(bd):
    """Team attack and defense from this season's goals and xG, per league, home edge from the league's own split."""
    lids = {g["lid"] for g in bd["games"]}
    team = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])     # matches, goals for, xg for, goals against, xg against
    league = defaultdict(lambda: [0, 0.0, 0.0, 0.0])         # matches, home goals, away goals, xg
    for lid in lids:
        files = sorted((ROOT / "soccer" / "hist").glob(f"{lid}_*.csv.gz"))
        if not files:
            continue
        match = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, None]))
        with gzip.open(files[-1], "rt", newline="") as fh:
            for r in csv.DictReader(fh):
                m = match[r["mid"]][int(r["team"])]
                m[0] += float(r["g"] or 0)
                m[1] += float(r["xg"] or 0)
                m[2] = r["home"] == "1"
        for sides in match.values():
            if len(sides) != 2:
                continue
            (t1, s1), (t2, s2) = sides.items()
            for me, a, b in ((t1, s1, s2), (t2, s2, s1)):
                t = team[(lid, me)]
                t[0] += 1
                t[1] += a[0]
                t[2] += a[1] or a[0]
                t[3] += b[0]
                t[4] += b[1] or b[0]
            hm, aw = (s1, s2) if s1[2] else (s2, s1)
            lg = league[lid]
            lg[0] += 1
            lg[1] += hm[0]
            lg[2] += aw[0]
            lg[3] += (hm[1] or hm[0]) + (aw[1] or aw[0])
    tid = {}
    for p in bd["players"]:
        tid.setdefault(p.get("team") or p.get("t"), p.get("tid"))
    for gm in bd["games"]:
        lg = league.get(gm["lid"])
        if not lg or lg[0] < 10:
            continue
        hg, ag = lg[1] / lg[0], lg[2] / lg[0]
        avg, xavg = (hg + ag) / 2, lg[3] / lg[0] / 2

        def rate(t, f, x):
            # half goals, half xG, each against its own league average, pulled toward average over the first matches
            n = t[0]
            v = 0.5 * t[f] / n / avg + 0.5 * t[x] / n / xavg if n else 1
            return (n * v + 6) / (n + 6)

        h, a = team.get((gm["lid"], gm.get("hid"))), team.get((gm["lid"], gm.get("aid")))
        if not h or not a:
            continue
        lh = hg * rate(h, 1, 2) * rate(a, 3, 4)
        la = ag * rate(a, 1, 2) * rate(h, 3, 4)
        g = grid(lh, la, 11)
        rng = range(11)
        hw = sum(g[i][j] for i in rng for j in rng if i > j)
        dr = sum(g[i][i] for i in rng)
        o25 = sum(g[i][j] for i in rng for j in rng if i + j > 2.5)
        btts = sum(g[i][j] for i in rng for j in rng if i and j)
        gm["proj"] = {"hs": round(lh, 2), "as": round(la, 2), "win": [round(hw, 3), round(dr, 3), round(1 - hw - dr, 3)],
                      "total": round(lh + la, 2), "over": [2.5, round(o25, 3)], "btts": round(btts, 3)}


def main():
    sport = sys.argv[1]
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / sport / "board.json"
    bd = json.loads(path.read_text())
    if not bd.get("games"):
        print("no games")
        return
    {"nhl": nhl, "nba": nba, "nfl": nfl, "soccer": soccer}[sport](bd)
    n = sum(1 for g in bd["games"] if g.get("proj"))
    path.write_text(json.dumps(bd, separators=(",", ":"), ensure_ascii=False))
    print(f"{sport}: {n} of {len(bd['games'])} games projected")


if __name__ == "__main__":
    main()
