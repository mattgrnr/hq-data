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
from datetime import datetime, timezone
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
    return {"hs": r1(lh), "as": r1(la), "lh": round(lh, 3), "la": round(la, 3), "win": [round(home, 3), round(1 - home, 3)],
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
    if book_spread is not None:      # the NFL schedule's consensus line, until a sportsbook feed replaces it
        out["book"] = {"spread": book_spread, "total": book_total, "src": "consensus"}
        out["value"] = []
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


# ---------- sportsbook lines (PropLine, saved by odds.py) ----------

ALIAS = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}      # ESPN logo codes -> NHL codes
NFL_NICK = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears",
            "CIN": "Bengals", "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
            "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs", "LA": "Rams", "LAC": "Chargers",
            "LV": "Raiders", "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
            "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers",
            "TEN": "Titans", "WAS": "Commanders"}
VALUE = 0.05     # our chance beats the book's fair chance by this much


def implied(price):
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def norm(name):
    import unicodedata
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    for w in (" fc", "fc ", " cf", " afc", " city", " united", " club", "1. ", "ac ", " calcio", "as ", "ssc ", "rc "):
        n = n.replace(w, " ")
    return " ".join(n.replace(".", " ").replace("-", " ").split())


def same_team(a, b):
    a, b = norm(a), norm(b)
    return a == b or a in b or b in a or (a.split() and b.split() and a.split()[0] == b.split()[0] and len(a.split()[0]) > 3)


def find_event(sport, gm, events):
    """The book event for one of our games: same teams, starting within three hours."""
    if sport == "soccer":
        t, h, a = gm["t"], gm["h"], gm["a"]
    else:
        t = datetime.fromtimestamp(gm["ko"], timezone.utc).isoformat() if gm.get("ko") else gm.get("start", "").replace("Z", ":00Z")
        h, a = gm["home"], gm["away"]
    try:
        t0 = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    for ev in events:
        try:
            if abs((datetime.fromisoformat(ev["t"].replace("Z", "+00:00")) - t0).total_seconds()) > 3 * 3600:
                continue
        except (ValueError, AttributeError):
            continue
        if sport in ("nhl", "nba"):
            if ALIAS.get(ev.get("hk"), ev.get("hk")) == h and ALIAS.get(ev.get("ak"), ev.get("ak")) == a:
                return ev
        elif sport == "nfl":
            if (ev.get("h") or "").endswith(NFL_NICK.get(h, "?")) and (ev.get("a") or "").endswith(NFL_NICK.get(a, "?")):
                return ev
        elif same_team(ev.get("h"), h) and same_team(ev.get("a"), a):
            return ev
    return None


def two_way(rows, pick_a, pick_b):
    """Fair chance of side A (vig removed, median across books) and the best price on each side."""
    import statistics
    pa = [r for r in rows if pick_a(r)]
    pb = [r for r in rows if pick_b(r)]
    if not pa or not pb:
        return None
    fair = []
    for bk in set(pa[0][3]) & set(pb[0][3]):
        x, y = implied(pa[0][3][bk]), implied(pb[0][3][bk])
        fair.append(x / (x + y))
    if not fair:
        return None
    best = lambda r: max(r[0][3].items(), key=lambda kv: kv[1])
    return statistics.median(fair), best(pa), best(pb)


def main_line(rows, side):
    """The point most books post for this side (their main line)."""
    from collections import Counter
    c = Counter()
    for r in rows:
        if side(r) and r[2] is not None:
            c[r[2]] += len(r[3])
    return c.most_common(1)[0][0] if c else None


def attach_odds(sport, bd, lam=None):
    f = ROOT / sport / "odds.json"
    if not f.exists():
        return 0
    events = json.loads(f.read_text()).get("events", [])
    n = 0
    for gm in bd["games"]:
        p = gm.get("proj")
        ev = p and find_event(sport, gm, events)
        if not ev:
            continue
        m, book, value = ev["m"], {}, []
        hn, an = ev["h"], ev["a"]
        home, away = (gm["h"], gm["a"]) if sport == "soccer" else (gm["home"], gm["away"])

        def add_value(mk, side, ours, fair, best):
            if ours - fair >= VALUE:
                value.append({"mk": mk, "side": side, "ours": round(ours, 3), "book": round(fair, 3), "price": best[1], "bk": best[0]})

        h2h = m.get("h2h", [])
        if sport == "soccer":
            import statistics
            sides = {}
            for key, nm in (("h", hn), ("d", "Draw"), ("a", an)):
                rows = [r for r in h2h if (r[0] == "Draw" if key == "d" else same_team(r[0], nm))]
                if rows:
                    sides[key] = rows[0]
            if len(sides) == 3:
                fair = {k: [] for k in sides}
                for bk in set.intersection(*(set(r[3]) for r in sides.values())):
                    tot = sum(implied(r[3][bk]) for r in sides.values())
                    for k, r in sides.items():
                        fair[k].append(implied(r[3][bk]) / tot)
                if fair["h"]:
                    fm = [statistics.median(fair[k]) for k in ("h", "d", "a")]
                    bests = [max(sides[k][3].items(), key=lambda kv: kv[1]) for k in ("h", "d", "a")]
                    book["ml"] = [round(x, 3) for x in fm]
                    book["mlp"] = [[b[1], b[0]] for b in bests]
                    for i, (lab, k) in enumerate(((home, "h"), ("Draw", "d"), (away, "a"))):
                        add_value("Result", lab, p["win"][i], fm[i], bests[i])
            bt = two_way(m.get("both_teams_to_score", []), lambda r: r[0] == "Yes", lambda r: r[0] == "No")
            if bt:
                book["btts"] = round(bt[0], 3)
                book["bttsp"] = [[bt[1][1], bt[1][0]], [bt[2][1], bt[2][0]]]
                add_value("Both score", "Yes", p["btts"], bt[0], bt[1])
                add_value("Both score", "No", 1 - p["btts"], 1 - bt[0], bt[2])
        else:
            ml = two_way(h2h, lambda r: r[0] == hn, lambda r: r[0] == an)
            if ml:
                book["ml"] = [round(ml[0], 3), round(1 - ml[0], 3)]
                book["mlp"] = [[ml[1][1], ml[1][0]], [ml[2][1], ml[2][0]]]
                add_value("Moneyline", home, p["win"][0], ml[0], ml[1])
                add_value("Moneyline", away, p["win"][1], 1 - ml[0], ml[2])
            sp = m.get("spreads", [])
            line = main_line(sp, lambda r: r[0] == hn)
            if line is not None:
                s2 = two_way(sp, lambda r: r[0] == hn and r[2] == line, lambda r: r[0] == an and r[2] == -line)
                if s2:
                    ours = cover_at(sport, p, line, lam)
                    book["spread"] = line
                    book["spreadp"] = [[s2[1][1], s2[1][0]], [s2[2][1], s2[2][0]]]
                    book["cover"] = round(s2[0], 3)
                    p["cover_book"] = round(ours, 3)
                    add_value("Spread", f"{home} {line:+g}", ours, s2[0], s2[1])
                    add_value("Spread", f"{away} {-line:+g}", 1 - ours, 1 - s2[0], s2[2])
        tot = m.get("totals", [])
        tl = 2.5 if sport == "soccer" else main_line(tot, lambda r: r[0] == "Over")
        if tl is not None:
            t2 = two_way(tot, lambda r: r[0] == "Over" and r[2] == tl, lambda r: r[0] == "Under" and r[2] == tl)
            if t2:
                ours = over_at(sport, p, tl, lam)
                book["total"] = tl
                book["totp"] = [[t2[1][1], t2[1][0]], [t2[2][1], t2[2][0]]]
                book["over"] = round(t2[0], 3)
                p["over_book"] = round(ours, 3)
                add_value("Total", f"Over {tl:g}", ours, t2[0], t2[1])
                add_value("Total", f"Under {tl:g}", 1 - ours, 1 - t2[0], t2[2])
        if book:
            p["book"] = book
            p["value"] = sorted(value, key=lambda v: v["book"] - v["ours"])
            n += 1
    return n


def cover_at(sport, p, line, lam):
    """Our chance the home side covers `line` (home perspective, -1.5 = home gives 1.5)."""
    if sport == "nhl":
        g = grid(p["lh"], p["la"])
        return sum(g[i][j] for i in range(15) for j in range(15) if i - j + line > 0)
    sd = 12.5 if sport == "nba" else 13.5
    return ncdf((p["hs"] - p["as"] + line) / sd)


def over_at(sport, p, line, lam):
    if sport in ("nhl", "soccer"):
        lh, la = (p["lh"], p["la"]) if sport == "nhl" else (p["hs"], p["as"])
        g = grid(lh, la)
        return sum(g[i][j] for i in range(15) for j in range(15) if i + j > line)
    sd = 18.0 if sport == "nba" else 13.0
    return 1 - ncdf((line - p["hs"] - p["as"]) / sd)


def main():
    sport = sys.argv[1]
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / sport / "board.json"
    bd = json.loads(path.read_text())
    if not bd.get("games"):
        print("no games")
        return
    {"nhl": nhl, "nba": nba, "nfl": nfl, "soccer": soccer}[sport](bd)
    n = sum(1 for g in bd["games"] if g.get("proj"))
    print(f"{sport}: book lines on {attach_odds(sport, bd)} games")
    path.write_text(json.dumps(bd, separators=(",", ":"), ensure_ascii=False))
    print(f"{sport}: {n} of {len(bd['games'])} games projected")


if __name__ == "__main__":
    main()
