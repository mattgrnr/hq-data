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
import re
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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
        gm["proj"] = soccer_proj(lh, la)


def soccer_proj(lh, la):
    g = grid(lh, la, 11)
    rng = range(11)
    hw = sum(g[i][j] for i in rng for j in rng if i > j)
    dr = sum(g[i][i] for i in rng)
    o25 = sum(g[i][j] for i in rng for j in rng if i + j > 2.5)
    btts = sum(g[i][j] for i in rng for j in rng if i and j)
    return {"hs": round(lh, 2), "as": round(la, 2), "win": [round(hw, 3), round(dr, 3), round(1 - hw - dr, 3)],
            "total": round(lh + la, 2), "over": [2.5, round(o25, 3)], "btts": round(btts, 3)}


def solve(f, lo, hi, want):
    """x in [lo, hi] where the increasing function f(x) hits want."""
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < want else (lo, mid)
    return (lo + hi) / 2


def soccer_lean(bd):
    """Take out the slate-wide lean in our soccer goal numbers, competition by competition.

    Each game's total line implies how many goals the books expect. Where ours run high across a whole
    competition, that is a lean in our model, not an edge in every game, so we scale ours to the books'
    average and keep each game's own differences.
    """
    groups = defaultdict(list)
    for gm in bd["games"]:
        p = gm.get("proj")
        b = (p or {}).get("book") or {}
        if not p or b.get("over") is None:
            continue
        tl = b.get("total", 2.5)
        tot = solve(lambda x: 1 - sum(pois(x, k) for k in range(int(tl) + 1)), 0.3, 8, b["over"])
        groups[gm["lid"]].append((tot, p["hs"] + p["as"]))
    every = [r for rs in groups.values() for r in rs]
    if len(every) < 3:
        return {}
    out = {}
    for gm in bd["games"]:
        p = gm.get("proj")
        if not p or not p.get("book"):
            continue
        rows = groups.get(gm["lid"]) if len(groups.get(gm["lid"], [])) >= 3 else every     # too few lines: judge the whole slate
        kt = min(1.25, max(0.75, sum(r[0] for r in rows) / sum(r[1] for r in rows)))
        keep = {k: v for k, v in p.items() if k not in ("hs", "as", "win", "total", "over", "btts")}
        gm["proj"] = {**soccer_proj(p["hs"] * kt, p["as"] * kt), **keep, "lean": round(kt, 2)}
        out[gm.get("league")] = round(kt, 2)
    return out


# ---------- sportsbook lines (PropLine, saved by odds.py) ----------

ALIAS = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}      # ESPN logo codes -> NHL codes
NFL_NICK = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears",
            "CIN": "Bengals", "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
            "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs", "LA": "Rams", "LAC": "Chargers",
            "LV": "Raiders", "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
            "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers",
            "TEN": "Titans", "WAS": "Commanders"}
VALUE = 0.05     # our chance beats the book's fair chance by this much
OFFSHORE = {"PIN", "BOV"}   # sharp enough to set the fair price, but not where most US bettors can place a bet


def placeable(prices):
    return {bk: v for bk, v in prices.items() if bk not in OFFSHORE}


def best_of(prices):
    """(book, price, every placeable book's price) for the best price a US bettor can get, or None."""
    p = placeable(prices)
    if not p:
        return None
    bk = max(p, key=p.get)
    return bk, p[bk], p


def implied(price):
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


SHORT = {"spurs": "tottenham", "wolves": "wolverhampton", "nottm forest": "nottingham forest", "psg": "paris saint germain",
         "bayern": "bayern munchen", "bayern munich": "bayern munchen", "atletico": "atletico madrid", "atl madrid": "atletico madrid"}


def norm(name):
    import unicodedata
    n = (name or "").lower().strip()
    n = SHORT.get(n, n)
    # the two Manchester clubs, however a feed spells them, kept apart before " city" / " united" are dropped
    n = re.sub(r"\bman(chester|\.)?\s*(city)\b.*", "mancity", n)
    n = re.sub(r"\bman(chester|\.)?\s*(utd|united)\b.*", "manutd", n)
    for x, y in (("ø", "o"), ("æ", "ae"), ("ß", "ss"), ("đ", "d"), ("ł", "l"), ("ı", "i"), ("/", " ")):   # letters NFKD can't split
        n = n.replace(x, y)
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
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


def px(b):
    """One side's price for the sites: [best price, its book, every book's price, bet-slip ids]."""
    return [b[1], b[0], b[2], b[3] if len(b) > 3 else {}]


def merged(rows):
    """One side can come in several rows (books label it differently); fold their prices into one row."""
    if not rows:
        return []
    prices, ids = {}, {}
    for r in rows:
        prices.update(r[3])
        if len(r) > 4:
            ids.update(r[4])
    return [[rows[0][0], rows[0][1], rows[0][2], prices, ids]]


def two_way(rows, pick_a, pick_b):
    """Fair chance of side A (vig removed, median across books) and the best price on each side."""
    import statistics
    pa = merged([r for r in rows if pick_a(r)])
    pb = merged([r for r in rows if pick_b(r)])
    if not pa or not pb:
        return None
    fair = []
    for bk in set(pa[0][3]) & set(pb[0][3]):
        x, y = implied(pa[0][3][bk]), implied(pb[0][3][bk])
        fair.append(x / (x + y))
    if not fair:
        return None
    a, b = best_of(pa[0][3]), best_of(pb[0][3])
    if not a or not b:
        return None
    ids = lambda r: r[0][4] if len(r[0]) > 4 else {}
    return statistics.median(fair), a + (ids(pa),), b + (ids(pb),)


def double_chance(rows, hn, an):
    """Fair chances of [home or draw, away or draw, either side wins] (margin removed per book) and the best price on each."""
    import statistics
    import re
    pick = []
    for want in ((hn, "Draw"), (an, "Draw"), (hn, an)):
        hits = []
        for r in rows:
            parts = [x.strip() for x in re.split(r"\s*/\s*|\s+or\s+", str(r[0]))]
            if len(parts) == 2 and all(any(w == "Draw" and x.lower() == "draw" or w != "Draw" and same_team(x, w) for x in parts) for w in want):
                hits.append(r)
        if not hits:
            return None
        pick.append(merged(hits)[0])
    fair = [[], [], []]
    for bk in set.intersection(*(set(r[3]) for r in pick)):
        tot = sum(implied(r[3][bk]) for r in pick)
        for i, r in enumerate(pick):
            fair[i].append(2 * implied(r[3][bk]) / tot)      # the three sides cover every result twice
    bests = [best_of(r[3]) for r in pick]
    if not fair[0] or not all(bests):
        return None
    return [statistics.median(f) for f in fair], [b + ((r[4] if len(r) > 4 else {}),) for b, r in zip(bests, pick)]


def handicap(rows, hn, an):
    """The half-goal Asian handicap closest to even money (no pushes to account for): home line, fair home chance, best prices."""
    best = None
    for line in sorted({r[2] for r in rows if r[2] is not None and same_team(r[0], hn) and abs(r[2] * 2) % 2 == 1}):
        t = two_way(rows, lambda r: same_team(r[0], hn) and r[2] == line, lambda r: same_team(r[0], an) and r[2] == -line)
        if t and (best is None or abs(t[0] - 0.5) < abs(best[1] - 0.5)):
            best = (line, t[0], t[1], t[2])
    return best


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
            if p:
                who = (gm.get("h"), gm.get("a")) if sport == "soccer" else (gm.get("away"), gm.get("home"))
                near = [f'{e.get("h")} v {e.get("a")}' for e in events if str(e.get("t", ""))[:10] == str(gm.get("t") or gm.get("start") or "")[:10]]
                print(f"{sport}: no book lines for {who[0]} v {who[1]}; the books' games that day: {near[:12]}")
            continue
        m, book, value = ev["m"], {}, []
        hn, an = ev["h"], ev["a"]
        home, away = (gm["h"], gm["a"]) if sport == "soccer" else (gm["home"], gm["away"])

        def add_value(mk, side, ours, fair, best):
            if ours - fair >= VALUE:
                value.append({"mk": mk, "side": side, "ours": round(ours, 3), "book": round(fair, 3), "price": best[1], "bk": best[0],
                              "all": best[2] if len(best) > 2 else {best[0]: best[1]}, "ids": best[3] if len(best) > 3 else {}})

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
                bests = [best_of(sides[k][3]) + ((sides[k][4] if len(sides[k]) > 4 else {}),) if best_of(sides[k][3]) else None
                         for k in ("h", "d", "a")]
                if fair["h"] and all(bests):
                    fm = [statistics.median(fair[k]) for k in ("h", "d", "a")]
                    book["ml"] = [round(x, 3) for x in fm]
                    book["mlp"] = [px(b) for b in bests]
                    for i, (lab, k) in enumerate(((home, "h"), ("Draw", "d"), (away, "a"))):
                        add_value("Result", lab, p["win"][i], fm[i], bests[i])
            hw, dr, aw = p["win"]
            dn = two_way(m.get("draw_no_bet", []), lambda r: same_team(r[0], hn), lambda r: same_team(r[0], an))
            if dn and hw + aw > 0:
                ours = hw / (hw + aw)
                book["dnb"] = round(dn[0], 3)
                book["dnbp"] = [px(dn[1]), px(dn[2])]
                p["dnb"] = round(ours, 3)
                add_value("Draw no bet", home, ours, dn[0], dn[1])
                add_value("Draw no bet", away, 1 - ours, 1 - dn[0], dn[2])
            dc = double_chance(m.get("double_chance", []), hn, an)
            if dc:
                ours = [hw + dr, dr + aw, hw + aw]
                book["dc"] = [round(x, 3) for x in dc[0]]
                book["dcp"] = [px(b) for b in dc[1]]
                p["dc"] = [round(x, 3) for x in ours]
                for i, lab in enumerate((f"{home} or draw", f"{away} or draw", f"{home} or {away}")):
                    add_value("Double chance", lab, ours[i], dc[0][i], dc[1][i])
            ah = handicap(m.get("spreads", []), hn, an)
            if ah:
                line, fair, bh, ba = ah
                ours = cover_at("soccer", p, line, lam)
                book["ah"] = line
                book["ahc"] = round(fair, 3)
                book["ahp"] = [px(bh), px(ba)]
                p["ah_book"] = round(ours, 3)
                add_value("Handicap", f"{home} {line:+g}", ours, fair, bh)
                add_value("Handicap", f"{away} {-line:+g}", 1 - ours, 1 - fair, ba)
            bt = two_way(m.get("both_teams_to_score", []), lambda r: r[0] == "Yes", lambda r: r[0] == "No")
            if bt:
                book["btts"] = round(bt[0], 3)
                book["bttsp"] = [px(bt[1]), px(bt[2])]
                add_value("Both score", "Yes", p["btts"], bt[0], bt[1])
                add_value("Both score", "No", 1 - p["btts"], 1 - bt[0], bt[2])
        else:
            ml = two_way(h2h, lambda r: r[0] == hn, lambda r: r[0] == an)
            if ml:
                book["ml"] = [round(ml[0], 3), round(1 - ml[0], 3)]
                book["mlp"] = [px(ml[1]), px(ml[2])]
                add_value("Moneyline", home, p["win"][0], ml[0], ml[1])
                add_value("Moneyline", away, p["win"][1], 1 - ml[0], ml[2])
            sp = m.get("spreads", [])
            line = main_line(sp, lambda r: r[0] == hn)
            if line is not None:
                s2 = two_way(sp, lambda r: r[0] == hn and r[2] == line, lambda r: r[0] == an and r[2] == -line)
                if s2:
                    ours = cover_at(sport, p, line, lam)
                    book["spread"] = line
                    book["spreadp"] = [px(s2[1]), px(s2[2])]
                    book["cover"] = round(s2[0], 3)
                    p["cover_book"] = round(ours, 3)
                    add_value("Spread", f"{home} {line:+g}", ours, s2[0], s2[1])
                    add_value("Spread", f"{away} {-line:+g}", 1 - ours, 1 - s2[0], s2[2])
        tot = m.get("totals", [])
        tl = main_line(tot, lambda r: r[0] == "Over")
        if sport == "soccer" and any(r[0] == "Over" and r[2] == 2.5 for r in tot):
            tl = 2.5
        if tl is not None:
            t2 = two_way(tot, lambda r: r[0] == "Over" and r[2] == tl, lambda r: r[0] == "Under" and r[2] == tl)
            if t2:
                ours = over_at(sport, p, tl, lam)
                book["total"] = tl
                book["totp"] = [px(t2[1]), px(t2[2])]
                book["over"] = round(t2[0], 3)
                p["over_book"] = round(ours, 3)
                add_value("Total", f"Over {tl:g}", ours, t2[0], t2[1])
                add_value("Total", f"Under {tl:g}", 1 - ours, 1 - t2[0], t2[2])
        if ev.get("lk"):
            p["links"] = {bk: u for bk, u in ev["lk"].items() if bk not in OFFSHORE}
        if book:
            p["book"] = book
            p["value"] = sorted(value, key=lambda v: v["book"] - v["ours"])
            n += 1
    return n


# ---------- player props ----------

PROP_STAT = {
    "nhl": {"player_goals": "G", "player_goals_2plus": ("G", 2), "player_points": "P", "player_points_1plus": "P", "player_points_2plus": ("P", 2), "player_shots_on_goal": "S"},
    "nba": {"player_points": "PTS", "player_rebounds": "REB", "player_assists": "AST", "player_points_rebounds_assists": "PRA",
            "player_points_rebounds": "PR", "player_points_assists": "PA", "player_rebounds_assists": "RA",
            "player_threes": "3PM", "player_blocks": "BLK", "player_steals": "STL"},
    "nfl": {"player_anytime_td": "TD", "player_pass_tds": "PTD", "player_pass_yds": "PYD", "player_reception_yds": "CYD",
            "player_rush_yds": "RYD", "player_receptions": "REC"},
    "soccer": {"anytime_goal_scorer": "G", "player_assists": "A", "goal_or_assist": "GA",
               "player_shots_on_target": "T", "player_shots": "S"},
}
ONE_SIDED_VIG = 1.07     # a yes-only price carries the book's margin with nothing to net it against


def pname(n):
    n = norm(n)
    return " ".join(w for w in n.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def attach_cal(sport, bd):
    """How our yes/no chances have held up, so the sites can correct them before comparing with the books."""
    f = ROOT / sport / "history" / "summary.json"
    try:
        cm = json.loads(f.read_text()).get("calmap")
    except (OSError, ValueError):
        cm = None
    if cm:
        bd["cal"] = cm
    else:
        bd.pop("cal", None)


def attach_props(sport, bd):
    """Book prices for player props, as 'at least k' lines: props[name][stat] = [[k, fair, price, book, books, over_under, prices]].

    Books post the same bet in different shapes ("Raphinha", "Yes" + Raphinha, "Over 0.5"), so every shape of
    'at least k' for a player is merged into one line carrying every book's price.
    """
    import re
    import statistics
    f = ROOT / sport / "odds.json"
    if not f.exists():
        return 0
    # (player, stat, k, kickoff) -> {"yes": {book: price}, "no": {book: price}, "ou": bool}
    # A player can be priced for more than one upcoming game; each game stays separate and the next one is used.
    now = datetime.now(timezone.utc)
    lines = {}
    events = json.loads(f.read_text()).get("events", [])
    evlinks = {str(ev.get("id")): {bk: u for bk, u in (ev.get("lk") or {}).items() if bk not in OFFSHORE} for ev in events}
    for ev in events:
        try:
            t = datetime.fromisoformat(str(ev.get("t")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t < now - timedelta(hours=3):
            continue
        for mk, stat in PROP_STAT[sport].items():
            stat, kfix = stat if isinstance(stat, tuple) else (stat, None)   # "Yes" in a 2+ market means at least 2
            for row in ev["m"].get(mk, []):
                name, desc, point, prices = row[:4]
                ids = row[4] if len(row) > 4 else {}
                who = pname(desc or name)
                if name in ("Over", "Under"):
                    if point is None:
                        continue
                    k, side, ou = math.floor(point) + 1, "yes" if name == "Over" else "no", True
                else:
                    m = re.match(r"(\d+)\+", name or "")
                    k, side, ou = (int(m.group(1)) if m else kfix or 1), "no" if name == "No" else "yes", False
                ln = lines.setdefault((who, stat, k, t), {"yes": {}, "no": {}, "ids": {}, "ou": False, "ev": ev.get("id")})
                ln[side].update(prices)
                if side == "yes":
                    ln["ids"].update(ids)
                ln["ou"] = ln["ou"] or ou
    nxt = {}
    for (who, stat, k, t) in lines:
        if (who, stat, k) not in nxt or t < nxt[(who, stat, k)]:
            nxt[(who, stat, k)] = t
    out = {}
    for (who, stat, k, t), ln in lines.items():
        if t != nxt[(who, stat, k)]:
            continue
        best = best_of(ln["yes"]) if ln["yes"] else None
        if not best:
            continue
        both = set(ln["yes"]) & set(ln["no"])
        if both:       # the book's margin netted out where a book posts both sides
            fair = statistics.median(implied(ln["yes"][b]) / (implied(ln["yes"][b]) + implied(ln["no"][b])) for b in both)
        else:
            fair = statistics.median(implied(v) for v in ln["yes"].values()) / ONE_SIDED_VIG
        out.setdefault(who, {}).setdefault(stat, []).append(
            [k, round(min(fair, 0.99), 3), best[1], best[0], len(ln["yes"]), 1 if ln["ou"] else 0, best[2], str(ln["ev"]), ln["ids"]])
    # only our board's players; volume stats keep the books' main line, chance stats the low rungs we show
    ours = {pname(p.get("name") or p.get("n") or "") for p in bd.get("players", [])}
    keep = {}
    for who, st in out.items():
        if who not in ours:
            continue
        for stat, rows in st.items():
            rows.sort(key=lambda x: x[0])
            if sport == "soccer" and stat in ("T", "S"):       # soccer shots come as 1+, 2+, 3+ ladders
                keep.setdefault(who, {})[stat] = [x for x in rows if x[0] <= 4]
            elif stat in ("PYD", "CYD", "RYD", "PTS", "REB", "AST", "PRA", "PR", "PA", "RA", "REC", "3PM", "BLK", "STL", "S"):
                two = [x for x in rows if x[5]]
                keep.setdefault(who, {})[stat] = [max(two, key=lambda x: x[4])] if two else sorted(rows, key=lambda x: -x[4])[:5]
            else:
                keep.setdefault(who, {})[stat] = [x for x in rows if x[0] <= 3]
    bd["props"] = keep
    used = {x[7] for st in keep.values() for rows in st.values() for x in rows}
    bd["evlinks"] = {e: evlinks[e] for e in used if evlinks.get(e)}
    return len(keep)


def cover_at(sport, p, line, lam):
    """Our chance the home side covers `line` (home perspective, -1.5 = home gives 1.5)."""
    if sport in ("nhl", "soccer"):
        g = grid(p["lh"], p["la"]) if sport == "nhl" else grid(p["hs"], p["as"])
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


def save_lines(bd, path):
    """Every soccer game line we priced, saved before kickoff so the Results Dashboard can grade them after."""
    if path.resolve() != (ROOT / "soccer" / "board.json").resolve():
        return
    from zoneinfo import ZoneInfo
    ldir = ROOT / "soccer" / "history" / "lines"
    ldir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    files = {}
    for gm in bd["games"]:
        p = gm.get("proj") or {}
        b = p.get("book") or {}
        t = datetime.fromisoformat(gm["t"].replace("Z", "+00:00"))
        if not b or t <= now:
            continue
        H, A = gm["h"], gm["a"]
        rows = []
        def add(mk, side, ours, fair, q):
            if ours is not None and fair is not None and q:
                rows.append([mk, side, round(ours, 3), round(fair, 3), q[0], q[1]])
        if b.get("ml"):
            for i, lab in enumerate((H, "Draw", A)):
                add("Result", lab, p["win"][i], b["ml"][i], b["mlp"][i])
        if b.get("dnb") is not None:
            add("Draw no bet", H, p["dnb"], b["dnb"], b["dnbp"][0])
            add("Draw no bet", A, 1 - p["dnb"], 1 - b["dnb"], b["dnbp"][1])
        if b.get("dc"):
            for i, lab in enumerate((f"{H} or draw", f"{A} or draw", f"{H} or {A}")):
                add("Double chance", lab, p["dc"][i], b["dc"][i], b["dcp"][i])
        if b.get("ah") is not None:
            add("Handicap", f"{H} {b['ah']:+g}", p["ah_book"], b["ahc"], b["ahp"][0])
            add("Handicap", f"{A} {-b['ah']:+g}", 1 - p["ah_book"], 1 - b["ahc"], b["ahp"][1])
        if b.get("over") is not None:
            add("Total", f"Over {b['total']:g}", p.get("over_book"), b["over"], b["totp"][0])
            add("Total", f"Under {b['total']:g}", 1 - p["over_book"], 1 - b["over"], b["totp"][1])
        if b.get("btts") is not None:
            add("Both score", "Yes", p["btts"], b["btts"], b["bttsp"][0])
            add("Both score", "No", 1 - p["btts"], 1 - b["btts"], b["bttsp"][1])
        day = t.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
        if day not in files:
            f = ldir / f"{day}.json"
            files[day] = json.loads(f.read_text()) if f.exists() else {}
        files[day][str(gm["id"])] = {"t": gm["t"], "h": H, "a": A, "league": gm.get("league"), "ah": b.get("ah"), "rows": rows}
    for day, d in files.items():
        (ldir / f"{day}.json").write_text(json.dumps(d, separators=(",", ":"), ensure_ascii=False))


def main():
    sport = sys.argv[1]
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / sport / "board.json"
    bd = json.loads(path.read_text())
    if not bd.get("games"):
        print("no games")
        return
    {"nhl": nhl, "nba": nba, "nfl": nfl, "soccer": soccer}[sport](bd)
    n = sum(1 for g in bd["games"] if g.get("proj"))
    attach_cal(sport, bd)
    nb = attach_odds(sport, bd)
    if sport == "soccer" and nb:
        print("soccer: lean taken out per competition:", soccer_lean(bd))
        nb = attach_odds(sport, bd)
        save_lines(bd, path)
    print(f"{sport}: book lines on {nb} games, props for {attach_props(sport, bd)} players")
    path.write_text(json.dumps(bd, separators=(",", ":"), ensure_ascii=False))
    print(f"{sport}: {n} of {len(bd['games'])} games projected")


if __name__ == "__main__":
    main()
