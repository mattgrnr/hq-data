#!/usr/bin/env python3
"""Golazo board: per-player goal, shot and assist rates from FotMob match pages, and the day's slate.

Each run refreshes fixture lists, adds finished matches to the history (oldest gaps filled in
batches until the time budget runs out), then rebuilds soccer/board.json for today and tomorrow.
"""
import csv
import gzip
import io
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent.parent / "soccer"
HIST = OUT / "hist"
FIX = OUT / "fixtures"
CT = ZoneInfo("America/Chicago")
BASE = "https://www.fotmob.com"
UA = "Mozilla/5.0 (compatible; GolazoHQ/1.0)"
REPLAY = os.environ.get("REPLAY_DATE")  # rebuild one past CT day from matches before it, no lineups
BUDGET = float(os.environ.get("BUDGET_MIN", "30")) * 60
DELAY = 1.0
START = time.time()

# FotMob league ids, in backfill priority order. The board covers the big five leagues;
# the European and domestic cups are kept so their players' form counts every competition.
LEAGUES = [
    (47, "Premier League"), (87, "LaLiga"), (55, "Serie A"), (54, "Bundesliga"), (53, "Ligue 1"),
    (42, "Champions League"), (73, "Europa League"), (10216, "Conference League"),
    (132, "FA Cup"), (133, "EFL Cup"), (138, "Copa del Rey"), (141, "Coppa Italia"),
    (209, "DFB Pokal"), (134, "Coupe de France"),
]
SLATE = {47, 87, 55, 54, 53}
LNAME = dict(LEAGUES)
FIELDS = ["mid", "date", "lid", "pid", "team", "opp", "home", "start", "min", "g", "a",
          "xg", "npxg", "xa", "sh", "sot", "tib", "penw"]
STATKEY = {"minutes_played": "min", "goals": "g", "assists": "a", "expected_goals": "xg",
           "expected_goals_non_penalty": "npxg", "expected_assists": "xa", "total_shots": "sh",
           "ShotsOnTarget": "sot", "touches_opp_box": "tib", "penalties_won": "penw"}


def out_of_time():
    return time.time() - START > BUDGET


def page(path):
    """Fetch a FotMob page and return the data embedded in it (regular pages, not /api)."""
    time.sleep(DELAY)
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "text/html"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", "replace")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            return json.loads(m.group(1))["props"]["pageProps"] if m else None
        except Exception as e:
            print(f"  fetch failed ({attempt + 1}/3) {path}: {e}")
            time.sleep(5 * (attempt + 1))
    return None


def load_json(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


# ---------- fixtures ----------

def season_param(label):
    # "2025/2026" -> "2025-2026"; split seasons like "2026/2027 - Apertura" pass through encoded
    return urllib.parse.quote(label.replace("/", "-"))


def refresh_fixtures(lid, state):
    """Current season every 3 hours, previous season once."""
    f = FIX / f"{lid}.json"
    fx = load_json(f, {"seasons": [], "matches": {}, "at": 0})
    fresh = time.time() - fx.get("at", 0) < 3 * 3600
    want = []
    if not fresh or not fx["seasons"]:
        want.append(None)
    if len(fx["seasons"]) > 1 and fx["seasons"][1] not in fx["matches"]:
        want.append(fx["seasons"][1])
    done = set()
    for season in want:
        if season in done:
            continue
        done.add(season)
        q = f"?season={season_param(season)}" if season else ""
        d = page(f"/leagues/{lid}/fixtures/x{q}")
        if not d or "fixtures" not in d:
            print(f"  no fixtures for {lid} {season or 'current'}")
            continue
        seasons = d.get("allAvailableSeasons") or []
        if season is None:
            fx["seasons"] = seasons[:2]
            fx["at"] = time.time()
        label = season or (seasons[0] if seasons else "current")
        rows = []
        for m in d["fixtures"].get("allMatches", []):
            st = m.get("status", {})
            if st.get("cancelled"):
                continue
            rows.append({"id": int(m["id"]), "t": st.get("utcTime"), "h": int(m["home"]["id"]),
                         "a": int(m["away"]["id"]), "hn": m["home"].get("shortName") or m["home"]["name"],
                         "an": m["away"].get("shortName") or m["away"]["name"],
                         "fin": bool(st.get("finished")), "aw": bool(st.get("awarded"))})
        fx["matches"][label] = rows
        if season is None and len(seasons) > 1 and seasons[1] not in fx["matches"] and not out_of_time():
            want.append(seasons[1])
    f.write_text(json.dumps(fx, separators=(",", ":")))
    state["fixtures"][lid] = fx


# ---------- history ----------

def hist_path(lid, label):
    return HIST / f"{lid}_{re.sub(r'[^0-9A-Za-z]+', '-', label).strip('-')}.csv.gz"


def read_hist(p):
    if not p.exists():
        return []
    with gzip.open(p, "rt", newline="") as fh:
        return list(csv.DictReader(fh))


def write_hist(p, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    for r in sorted(rows, key=lambda r: (int(r["date"]), int(r["mid"]), int(r["pid"]))):
        w.writerow(r)
    with gzip.GzipFile(p, "wb", mtime=0) as fh:
        fh.write(buf.getvalue().encode())


def stat_values(p):
    out = {}
    for block in p.get("stats") or []:
        for v in (block.get("stats") or {}).values():
            k = STATKEY.get(v.get("key"))
            if k and k not in out:
                val = (v.get("stat") or {}).get("value")
                out[k] = "" if val is None else val
    return out


def match_rows(d, lid, mid):
    """Player rows for one finished match, or [] if FotMob has no player stats for it."""
    content = d.get("content") or {}
    ps = content.get("playerStats") or {}
    if not ps:
        return []
    gen = d.get("general") or {}
    hid, aid = int(gen["homeTeam"]["id"]), int(gen["awayTeam"]["id"])
    t = (d.get("header") or {}).get("status", {}).get("utcTime") or ""
    date = t[:10].replace("-", "")
    starters = set()
    lu = content.get("lineup") or {}
    for side in ("homeTeam", "awayTeam"):
        for s in (lu.get(side) or {}).get("starters") or []:
            if s.get("id"):
                starters.add(int(s["id"]))
    names = {}
    rows = []
    for pid, p in ps.items():
        if p.get("isGoalkeeper"):
            continue
        sv = stat_values(p)
        if not sv.get("min"):
            continue
        team = int(p["teamId"])
        names[int(pid)] = [p.get("name"), p.get("usualPosition")]
        row = {k: sv.get(k, "") for k in FIELDS}
        row.update(mid=mid, date=date, lid=lid, pid=int(pid), team=team,
                   opp=aid if team == hid else hid, home=1 if team == hid else 0,
                   start=1 if int(pid) in starters else 0)
        rows.append(row)
    return rows, names


def backfill(state):
    players = state["players"]
    skip = set(load_json(HIST / "skip.json", []))
    now = datetime.now(timezone.utc)
    # current seasons first, then last season, in league priority order
    for which in (0, 1):
        for lid, _ in LEAGUES:
            fx = state["fixtures"].get(lid)
            if not fx or len(fx["seasons"]) <= which:
                continue
            label = fx["seasons"][which]
            todo = [m for m in fx["matches"].get(label, []) if m["fin"] and not m["aw"]]
            if not todo:
                continue
            p = hist_path(lid, label)
            rows = read_hist(p)
            have = {int(r["mid"]) for r in rows} | skip
            todo = [m for m in todo if m["id"] not in have
                    and m["t"] and datetime.fromisoformat(m["t"].replace("Z", "+00:00")) < now - timedelta(hours=3)]
            if not todo:
                continue
            added = 0
            for m in todo:
                if out_of_time():
                    break
                d = page(f"/match/{m['id']}")
                if not d:
                    continue
                got = match_rows(d, lid, m["id"])
                if not got:
                    skip.add(m["id"])
                    continue
                r, names = got
                rows.extend(r)
                for pid, nm in names.items():
                    players[str(pid)] = nm
                added += 1
            if added:
                write_hist(p, rows)
                print(f"  {LNAME[lid]} {label}: +{added} matches ({len(todo) - added} left)")
            if out_of_time():
                break
        if out_of_time():
            break
    (HIST / "skip.json").write_text(json.dumps(sorted(skip)))


# ---------- model inputs ----------

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_all_history(state):
    """Every stored row, tagged with whether it belongs to the current or previous season."""
    rows = []
    for lid, _ in LEAGUES:
        fx = state["fixtures"].get(lid)
        if not fx:
            continue
        for i, label in enumerate(fx["seasons"][:2]):
            for r in read_hist(hist_path(lid, label)):
                r["cur"] = i == 0
                rows.append(r)
    return rows


def build_profiles(rows):
    """Per-player rates (this season and last), per-team attack/defense and penalty duty."""
    pl = defaultdict(lambda: {"cur": defaultdict(float), "prev": defaultdict(float), "log": []})
    team_games = defaultdict(dict)  # team -> mid -> {date, xgf, gf, shf, sotf, pen}
    for r in rows:
        mins = num(r["min"]) or 0
        if mins <= 0:
            continue
        pid, team, mid = int(r["pid"]), int(r["team"]), int(r["mid"])
        xg, npxg = num(r["xg"]), num(r["npxg"])
        sh, sot = num(r["sh"]) or 0, num(r["sot"]) or 0
        if xg is None:  # no xG coverage: estimate from shots
            xg = npxg = 0.06 * sh + 0.10 * sot
        if npxg is None:
            npxg = xg
        pen = max(0.0, xg - npxg)
        bucket = pl[pid]["cur" if r["cur"] else "prev"]
        for k, v in (("min", mins), ("g", num(r["g"]) or 0), ("a", num(r["a"]) or 0), ("xg", xg),
                     ("npxg", npxg), ("xa", num(r["xa"]) or 0), ("sh", sh), ("sot", sot), ("pen", pen)):
            bucket[k] += v
        pl[pid]["log"].append((int(r["date"]), mid, team, mins, int(r["start"] or 0),
                               num(r["g"]) or 0, sot, sh, num(r["a"]) or 0, pen))
        tg = team_games[team].setdefault(mid, {"date": int(r["date"]), "opp": int(r["opp"]), "lid": int(r["lid"]),
                                               "xgf": 0.0, "npf": 0.0, "gf": 0.0, "shf": 0.0, "sotf": 0.0, "pen": 0.0})
        tg["xgf"] += xg
        tg["npf"] += npxg
        tg["gf"] += num(r["g"]) or 0
        tg["shf"] += sh
        tg["sotf"] += sot
        tg["pen"] += pen
    for p in pl.values():
        p["log"].sort(reverse=True)
    return pl, team_games


def team_form(team_games, n=14):
    """Recent attack and defense per team, from both sides of each match."""
    out = {}
    for team, games in team_games.items():
        recent = sorted(games.items(), key=lambda kv: kv[1]["date"], reverse=True)[:n]
        if not recent:
            continue
        f = {"n": len(recent), "npf": 0.0, "npa": 0.0, "shf": 0.0, "sha": 0.0, "sotf": 0.0, "sota": 0.0,
             "gf": 0.0, "ga": 0.0, "pen": 0.0}
        for mid, g in recent:
            o = team_games.get(g["opp"], {}).get(mid)
            f["npf"] += g["npf"]
            f["shf"] += g["shf"]
            f["sotf"] += g["sotf"]
            f["gf"] += g["gf"]
            f["pen"] += g["pen"]
            if o:
                f["npa"] += o["npf"]
                f["sha"] += o["shf"]
                f["sota"] += o["sotf"]
                f["ga"] += o["gf"]
        for k in list(f):
            if k != "n":
                f[k] /= f["n"]
        out[team] = f
    return out


def league_avgs(team_games):
    by = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])
    for games in team_games.values():
        for g in games.values():
            b = by[g["lid"]]
            b[0] += 1
            b[1] += g["npf"]
            b[2] += g["shf"]
            b[3] += g["sotf"]
            b[4] += g["pen"]
    return {lid: {"np": b[1] / b[0], "sh": b[2] / b[0], "sot": b[3] / b[0], "pen": b[4] / b[0]}
            for lid, b in by.items() if b[0] >= 10}


def rate(p, k, prior, K=5.0):
    """Per-90 rate: this season only, leaning on the position average until he has a handful of full games."""
    c = p["cur"]
    return (c[k] + prior * K) / (c["min"] / 90 + K)


# ---------- today's slate ----------

def lineup_info(d):
    """Starters, bench and unavailable players for each side, plus whether the lineup is confirmed."""
    lu = ((d or {}).get("content") or {}).get("lineup") or {}
    kind = lu.get("lineupType") or "unavailable"
    out = {"kind": kind}
    for side in ("homeTeam", "awayTeam"):
        t = lu.get(side) or {}
        out[side] = {
            "start": [int(s["id"]) for s in t.get("starters") or [] if s.get("id")],
            "bench": [int(s["id"]) for s in t.get("subs") or [] if s.get("id")],
            "out": {int(s["id"]): (s.get("unavailability") or {}).get("type", "out")
                    for s in t.get("unavailable") or [] if s.get("id")},
        }
    return out


def exp_minutes(p, team, lu_side, kind):
    """Expected minutes: from the confirmed lineup when there is one, otherwise from recent usage."""
    log = [x for x in p["log"] if x[2] == team][:6]
    starts = [x[3] for x in log if x[4]]
    avg_start = sum(starts) / len(starts) if starts else 78.0
    subs = [x[3] for x in log if not x[4]]
    avg_sub = sum(subs) / len(subs) if subs else 18.0
    pid = p["id"]
    if lu_side and pid in lu_side["out"]:
        return 0.0, "out"
    if kind == "standard" and lu_side and lu_side["start"]:
        if pid in lu_side["start"]:
            return min(90.0, avg_start), "starting"
        if pid in lu_side["bench"]:
            used = len(subs) / max(1, len(log) - len(starts)) if log else 0.3
            return clamp(used, 0.15, 0.8) * avg_sub, "bench"
        return 0.0, "not in squad"
    if lu_side and lu_side["start"]:
        # a predicted XI is a decent guess; last match's XI is a weaker one
        sure, tag = (0.88, "predicted") if kind == "predicted" else (0.75, "last11")
        if pid in lu_side["start"]:
            return sure * min(90.0, avg_start), tag
    recent = [x for x in p["log"] if x[2] == team][:5]
    if not recent:
        return 0.0, ""
    return sum(x[3] for x in recent) / 5, "likely" if len(starts) >= 3 else ""


def clamp(x, a, b):
    return max(a, min(b, x))


def attach_logs(players, games, pl, team_games, state):
    """Last five matches and every match against tonight's opponent (this season and last), newest first.
    gl: [date, opp, min, g, a, sot, sh]; vs.g: [date, min, g, a, sot, sh]"""
    tname = {}
    for fx in state["fixtures"].values():
        for ms in (fx or {}).get("matches", {}).values():
            for m in ms:
                tname[m["h"]], tname[m["a"]] = m["hn"], m["an"]
    day = lambda d: f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}"
    for o in players:
        g = games[o["g"]]
        opp = g["aid"] if o["home"] else g["hid"]
        rows = []
        for x in pl[o["id"]]["log"]:
            tg = team_games.get(x[2], {}).get(x[1])
            rows.append((x, tg["opp"] if tg else None))
        o["gl"] = [[day(x[0]), tname.get(op, ""), round(x[3]), int(x[5]), int(x[8]), int(x[6]), int(x[7])] for x, op in rows[:5]]
        vs = [[day(x[0]), round(x[3]), int(x[5]), int(x[8]), int(x[6]), int(x[7])] for x, op in rows if op == opp]
        o["vs"] = {"opp": g["a"] if o["home"] else g["h"], "gp": len(vs), "g": vs}


def build_board(state, rows):
    pl, team_games = build_profiles(rows)
    form = team_form(team_games)
    lg = league_avgs(team_games)
    allavg = {"np": 1.25, "sh": 12.0, "sot": 4.2, "pen": 0.09}
    pos_prior = defaultdict(lambda: {"npxg": 0.10, "xa": 0.08, "sh": 1.0, "sot": 0.35, "g": 0.10, "a": 0.08})
    pos_prior[3] = {"npxg": 0.30, "xa": 0.10, "sh": 2.2, "sot": 0.85, "g": 0.30, "a": 0.10}
    pos_prior[2] = {"npxg": 0.12, "xa": 0.14, "sh": 1.3, "sot": 0.45, "g": 0.11, "a": 0.13}
    pos_prior[1] = {"npxg": 0.05, "xa": 0.05, "sh": 0.6, "sot": 0.18, "g": 0.04, "a": 0.05}
    names = state["players"]

    now_ct = datetime.fromisoformat(REPLAY + "T06:00:00").replace(tzinfo=CT) if REPLAY else datetime.now(CT)
    # each player's current team (his latest appearance, if recent) and who has been taking penalties
    cutoff = int((now_ct - timedelta(days=150)).strftime("%Y%m%d"))
    roster = defaultdict(list)
    team_pens = defaultdict(lambda: defaultdict(float))
    for pid, p in pl.items():
        if p["log"] and p["log"][0][0] >= cutoff:
            roster[p["log"][0][2]].append(pid)
        for x in p["log"][:40]:
            if x[9] > 0:
                team_pens[x[2]][pid] += x[9]
    days = [now_ct.date()] if REPLAY else [now_ct.date(), now_ct.date() + timedelta(days=1)]
    games = []
    for lid, _ in LEAGUES:
        if lid not in SLATE:
            continue
        fx = state["fixtures"].get(lid)
        if not fx or not fx["seasons"]:
            continue
        for m in fx["matches"].get(fx["seasons"][0], []):
            if not m["t"]:
                continue
            k = datetime.fromisoformat(m["t"].replace("Z", "+00:00")).astimezone(CT)
            if k.date() in days and (REPLAY or not m["fin"]):
                games.append((k, lid, m))
    games.sort(key=lambda g: g[0])
    print(f"slate: {len(games)} matches")

    lineups = load_json(OUT / "lineups.json", {})
    out_games, out_players = [], []
    for k, lid, m in games:
        key = str(m["id"])
        old = lineups.get(key)
        hrs = (k - now_ct).total_seconds() / 3600
        stale = not REPLAY and (not old or (old["kind"] != "standard" and (hrs < 3 or time.time() - old.get("at", 0) > 6 * 3600)))
        if stale and not out_of_time():
            d = page(f"/match/{m['id']}")
            if d:
                old = lineup_info(d)
                old["at"] = time.time()
                lineups[key] = old
        lu = (None if REPLAY else old) or {"kind": "unavailable"}
        gi = len(out_games)
        la = lg.get(lid, allavg)
        out_games.append({"id": m["id"], "lid": lid, "league": LNAME[lid], "t": k.isoformat(),
                          "day": 0 if k.date() == days[0] else 1, "h": m["hn"], "a": m["an"], "hid": m["h"], "aid": m["a"],
                          "lu": lu.get("kind", "unavailable")})
        for side, team, opp, home in (("homeTeam", m["h"], m["a"], 1), ("awayTeam", m["a"], m["h"], 0)):
            tf, of = form.get(team), form.get(opp)
            # attack: this team's chance creation; defense: what the opponent allows (both vs league average)
            att = clamp((tf["npf"] * tf["n"] + la["np"] * 5) / (tf["n"] + 5) / la["np"], 0.5, 1.9) if tf else 1.0
            dfn = clamp((of["npa"] * of["n"] + la["np"] * 5) / (of["n"] + 5) / la["np"], 0.5, 1.9) if of else 1.0
            sdf = clamp((of["sota"] * of["n"] + la["sot"] * 5) / (of["n"] + 5) / la["sot"], 0.5, 1.9) if of else 1.0
            shf = clamp((of["sha"] * of["n"] + la["sh"] * 5) / (of["n"] + 5) / la["sh"], 0.5, 1.9) if of else 1.0
            team_pen = (tf["pen"] if tf else la["pen"])
            pens = team_pens.get(team, {})
            tot_pen = sum(pens.values())
            lu_side = lu.get(side)
            cands = list(roster.get(team, []))
            if lu_side:
                cands = list(set(cands) | set(lu_side["start"]) | set(lu_side["bench"]))
            for pid in cands:
                p = pl.get(pid)
                if not p:
                    continue
                p["id"] = pid
                mins, status = exp_minutes(p, team, lu_side, lu.get("kind"))
                if mins < 12:
                    continue
                nm = names.get(str(pid), [None, None])
                pos = nm[1] if nm[1] is not None else 2
                pr = pos_prior[pos]
                r = {s: rate(p, s, pr[s]) for s in ("npxg", "xa", "sh", "sot", "g", "a")}
                f90 = mins / 90
                ha = 1.06 if home else 0.94
                # finishing: goals vs xG over a decent sample, pulled hard toward 1
                xgs = p["cur"]["xg"]
                gs = p["cur"]["g"]
                fin = clamp((gs + 8) / (xgs + 8), 0.85, 1.2)
                share = pens[pid] / tot_pen if tot_pen > 0.5 else 0.0
                pen_g = share * team_pen * 0.78 * (min(mins, 90) / 90)
                np_g = r["npxg"] * f90 * (att ** 0.35) * (dfn ** 0.65) * ha
                proj_g = np_g * fin + pen_g
                proj_sot = r["sot"] * f90 * (att ** 0.3) * (sdf ** 0.6) * ha
                proj_sh = r["sh"] * f90 * (att ** 0.3) * (shf ** 0.6) * ha
                proj_a = (0.6 * r["xa"] + 0.4 * r["a"]) * f90 * (att ** 0.6) * (dfn ** 0.4) * ha
                last = [x for x in p["log"]][:5]
                out_players.append({
                    "id": pid, "n": nm[0] or str(pid), "pos": pos, "g": gi, "home": home, "st": status,
                    "min": round(mins), "pg": round(proj_g, 3), "psot": round(proj_sot, 2),
                    "psh": round(proj_sh, 2), "pa": round(proj_a, 3), "pen": round(share, 2),
                    "r": {k2: round(v, 3) for k2, v in r.items()},
                    "szn": {k2: round(p["cur"][k2], 2) for k2 in ("min", "g", "a", "npxg", "sh", "sot")},
                    "l5": [[x[0], round(x[3]), int(x[5]), int(x[6]), int(x[8])] for x in last],
                    "att": round(att, 2), "dfn": round(dfn, 2), "sdf": round(sdf, 2),
                })
    attach_logs(out_players, out_games, pl, team_games, state)
    if not REPLAY:
        (OUT / "lineups.json").write_text(json.dumps({k: v for k, v in lineups.items()
                                                      if any(str(g["id"]) == k for g in out_games)},
                                                     separators=(",", ":")))
    board = {"date": days[0].isoformat(), "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "leagues": [{"id": lid, "name": n} for lid, n in LEAGUES if lid in SLATE], "games": out_games,
             "players": out_players, "logcols": ["min", "g", "a", "sot", "sh"]}
    dest = OUT / "replay" / f"{REPLAY}.json" if REPLAY else OUT / "board.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(board, separators=(",", ":"), ensure_ascii=False))
    print(f"board: {len(out_games)} matches, {len(out_players)} players")


def main():
    OUT.mkdir(exist_ok=True)
    HIST.mkdir(exist_ok=True)
    FIX.mkdir(exist_ok=True)
    state = {"fixtures": {}, "players": load_json(OUT / "players.json", {})}
    if REPLAY:
        for lid, _ in LEAGUES:
            state["fixtures"][lid] = load_json(FIX / f"{lid}.json", None)
        cut = REPLAY.replace("-", "")
        rows = [r for r in load_all_history(state) if r["date"] < cut]
        print(f"replay {REPLAY}: {len(rows)} history rows before it")
        build_board(state, rows)
        return
    for lid, name in LEAGUES:
        f = FIX / f"{lid}.json"
        state["fixtures"][lid] = load_json(f, None)
        if out_of_time():
            continue
        print(f"fixtures: {name}")
        refresh_fixtures(lid, state)
    print("history")
    # leave time for the slate
    global BUDGET
    full = BUDGET
    BUDGET = max(60, full - 8 * 60)
    backfill(state)
    BUDGET = full
    (OUT / "players.json").write_text(json.dumps(state["players"], separators=(",", ":"), ensure_ascii=False))
    rows = load_all_history(state)
    print(f"history rows: {len(rows)}")
    build_board(state, rows)


if __name__ == "__main__":
    sys.exit(main())
