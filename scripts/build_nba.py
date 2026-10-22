#!/usr/bin/env python3
"""Builds nba/board.json for Slam HQ from public sportsdataverse NBA data, topped up from ESPN."""
import datetime as dt
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

REL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ROOT = Path(__file__).resolve().parent.parent / "nba"
OUT = ROOT / "board.json"
LOCAL = os.environ.get("HQ_LOCAL")  # read files from a folder instead of downloading
NO_ESPN = os.environ.get("HQ_NO_ESPN")
ET = ZoneInfo("America/New_York")

K_PLAYER = 20   # last season counts as this many games
K_ROOKIE = 10   # no history: lean on the league average for the position group
K_MIN = 10      # minutes follow this season's role faster than scoring rates do
K_TEAM = 20
MIN_MPG = 10    # below this a player isn't in the rotation
STATS = ("pts", "reb", "ast", "fg3m")
GROUPS = ("G", "F", "C")


def fetch(path, tries=3):
    if LOCAL:
        p = Path(LOCAL) / path.rsplit("/", 1)[-1]
        return p.read_bytes() if p.exists() else b""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(f"{REL}/{path}", headers={"User-Agent": "hq-data"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            last = e
        except Exception as e:
            last = e
        time.sleep(10 * (i + 1))
    raise last


def espn(path, tries=2):
    if NO_ESPN:
        return None
    for i in range(tries):
        try:
            req = urllib.request.Request(f"{ESPN}/{path}", headers={"User-Agent": "hq-data"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(3 * (i + 1))
    return None


def parquet(path, columns=None):
    data = fetch(path)
    if not data:
        return []
    return pq.read_table(io.BytesIO(data), columns=columns).to_pylist()


def num(v):
    try:
        return float(v) if v not in ("", None) else 0.0
    except (TypeError, ValueError):
        return 0.0


def group(pos):
    pos = (pos or "").upper()
    if pos in ("G", "PG", "SG"):
        return "G"
    if pos == "C":
        return "C"
    return "F"


# ---------- player-game rows ----------

BOX_COLS = ["game_id", "season_type", "game_date", "athlete_id", "athlete_display_name", "athlete_position_abbreviation",
            "team_abbreviation", "minutes", "points", "rebounds", "assists", "three_point_field_goals_made",
            "field_goals_attempted", "free_throws_attempted", "offensive_rebounds", "turnovers", "did_not_play"]


def box_rows(season, teams):
    out = []
    for r in parquet(f"espn_nba_player_boxscores/player_box_{season}.parquet", BOX_COLS):
        if r["season_type"] != 2 or r["did_not_play"] or num(r["minutes"]) <= 0 or r["team_abbreviation"] not in teams:
            continue
        out.append({
            "gid": int(r["game_id"]), "date": str(r["game_date"])[:10], "pid": int(r["athlete_id"]),
            "name": r["athlete_display_name"], "pos": r["athlete_position_abbreviation"], "team": r["team_abbreviation"],
            "min": num(r["minutes"]), "pts": num(r["points"]), "reb": num(r["rebounds"]), "ast": num(r["assists"]),
            "fg3m": num(r["three_point_field_goals_made"]), "fga": num(r["field_goals_attempted"]),
            "fta": num(r["free_throws_attempted"]), "oreb": num(r["offensive_rebounds"]), "tov": num(r["turnovers"]),
        })
    return out


def summary_rows(gid, date):
    """Box score for one finished game straight from ESPN, for nights the parquet hasn't caught up on."""
    d = espn(f"summary?event={gid}")
    if not d:
        return []
    try:
        if not d["header"]["competitions"][0]["status"]["type"]["completed"]:
            return []
    except (KeyError, IndexError, TypeError):
        return []
    out = []
    for t in (d.get("boxscore") or {}).get("players") or []:
        tm = t["team"]["abbreviation"]
        st = (t.get("statistics") or [{}])[0]
        keys = st.get("keys") or []
        for a in st.get("athletes") or []:
            if a.get("didNotPlay") or not a.get("stats"):
                continue
            v = dict(zip(keys, a["stats"]))
            mins = num(v.get("minutes"))
            if mins <= 0:
                continue
            fg = str(v.get("fieldGoalsMade-fieldGoalsAttempted", "0-0")).split("-")
            ft = str(v.get("freeThrowsMade-freeThrowsAttempted", "0-0")).split("-")
            tp = str(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "0-0")).split("-")
            ath = a["athlete"]
            out.append({
                "gid": int(gid), "date": date, "pid": int(ath["id"]), "name": ath["displayName"],
                "pos": (ath.get("position") or {}).get("abbreviation", ""), "team": tm,
                "min": mins, "pts": num(v.get("points")), "reb": num(v.get("rebounds")), "ast": num(v.get("assists")),
                "fg3m": num(tp[0]), "fga": num(fg[-1]), "fta": num(ft[-1]),
                "oreb": num(v.get("offensiveRebounds")), "tov": num(v.get("turnovers")),
            })
    return out


# ---------- one season of raw totals ----------

def season_totals(rows):
    pl = defaultdict(lambda: {"gp": 0, "min": 0.0, **{s: 0.0 for s in STATS}})
    info, games_of = {}, defaultdict(list)
    tg = defaultdict(lambda: {"poss": 0.0, "min": 0.0, "grp": defaultdict(lambda: defaultdict(float))})
    game_teams = defaultdict(set)

    for r in sorted(rows, key=lambda r: (r["date"], r["gid"])):
        pid, tm, gid = r["pid"], r["team"], r["gid"]
        s = pl[pid]
        s["gp"] += 1
        s["min"] += r["min"]
        for k in STATS:
            s[k] += r[k]
        info[pid] = {"name": r["name"], "pos": group(r["pos"]) if r["pos"] else info.get(pid, {}).get("pos", "F"), "team": tm}
        games_of[pid].append((r["date"], gid, tm, r["min"], r["pts"], r["reb"], r["ast"]))
        t = tg[(gid, tm)]
        t["poss"] += r["fga"] + 0.44 * r["fta"] - r["oreb"] + r["tov"]
        t["min"] += r["min"]
        g = t["grp"][group(r["pos"])]
        for k in ("pts", "reb", "ast"):
            g[k] += r[k]
        game_teams[gid].add(tm)

    team = defaultdict(lambda: {"gp": 0, "pace": 0.0, "allow": {g: {k: 0.0 for k in ("pts", "reb", "ast")} for g in GROUPS}})
    for gid, tms in game_teams.items():
        if len(tms) != 2:
            continue
        a, b = sorted(tms)
        ta, tb = tg[(gid, a)], tg[(gid, b)]
        if ta["min"] <= 0 or tb["min"] <= 0:
            continue
        pace = (ta["poss"] * 240 / ta["min"] + tb["poss"] * 240 / tb["min"]) / 2
        for me, op in ((a, b), (b, a)):
            t = team[me]
            t["gp"] += 1
            t["pace"] += pace
            for g in GROUPS:
                for k in ("pts", "reb", "ast"):
                    t["allow"][g][k] += tg[(gid, op)]["grp"][g][k]
    return {"pl": pl, "info": info, "games_of": games_of, "team": team}


def prior_profile(season, teams):
    """Season totals from a finished season, cached in the repo since they never change."""
    path = ROOT / f"prior_{season}.json"
    if path.exists():
        return json.loads(path.read_text())
    t = season_totals(box_rows(season, teams))
    if not t["pl"]:
        return {"pl": {}, "team": {}}
    out = {
        "pl": {str(pid): {**{k: round(v, 1) for k, v in s.items()}, "pos": t["info"][pid]["pos"], "team": t["info"][pid]["team"],
                               "name": t["info"][pid]["name"]}
               for pid, s in t["pl"].items() if s["gp"]},
        "team": {tm: {"gp": s["gp"], "pace": round(s["pace"], 1),
                      "allow": {g: {k: round(v, 1) for k, v in s["allow"][g].items()} for g in GROUPS}}
                 for tm, s in t["team"].items()},
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":")))
    return out


# ---------- board ----------

def main():
    now = dt.datetime.now(ET)
    today = dt.date.fromisoformat(os.environ["TODAY"]) if os.environ.get("TODAY") else now.date()
    season = today.year + 1 if today.month >= 8 else today.year

    sched = [g for g in parquet(f"espn_nba_schedules/nba_schedule_{season}.parquet") if g["season_type"] == 2]
    nba = {g["home_abbreviation"] for g in sched} | {g["away_abbreviation"] for g in sched}
    nba.discard("TBD")   # the 30 real teams; keeps All-Star and other exhibition sides out
    prior = prior_profile(season - 1, nba)
    slate = sorted((g for g in sched if str(g["game_date"])[:10] == today.isoformat()),
                   key=lambda g: (g["start_date"], g["home_abbreviation"]))

    # this season: the parquet, plus any finished game it hasn't picked up yet
    rows = box_rows(season, nba)
    have = {r["gid"] for r in rows}
    for g in sched:
        d = str(g["game_date"])[:10]
        if d < today.isoformat() and int(g["game_id"]) not in have:
            rows += summary_rows(int(g["game_id"]), d)
    cur = season_totals(rows)
    pl, info, team = cur["pl"], cur["info"], cur["team"]

    # league baselines from last season and this one together
    star, nstar = defaultdict(float), 0
    by_group = {g: defaultdict(float) for g in GROUPS}
    for src in (prior["pl"].values(), [{**s, "pos": info[pid]["pos"]} for pid, s in pl.items()]):
        for s in src:
            for k in ("gp", "min", *STATS):
                by_group[s["pos"]][k] += s[k]
            if s["gp"] >= 10 and s["min"] / s["gp"] >= 30:
                nstar += s["gp"]
                for k in ("min", *STATS):
                    star[k] += s[k]
    tt = {"gp": 0, "pace": 0.0, "allow": {g: defaultdict(float) for g in GROUPS}}
    for src in (prior["team"].values(), team.values()):
        for t in src:
            tt["gp"] += t["gp"]
            tt["pace"] += t["pace"]
            for g in GROUPS:
                for k in ("pts", "reb", "ast"):
                    tt["allow"][g][k] += t["allow"][g][k]
    lg = {
        "pace": tt["pace"] / tt["gp"],
        "star": {k: star[k] / nstar for k in ("min", *STATS)},
        "allow": {g: {k: tt["allow"][g][k] / tt["gp"] for k in ("pts", "reb", "ast")} for g in GROUPS},
    }
    lg["star"]["pra"] = lg["star"]["pts"] + lg["star"]["reb"] + lg["star"]["ast"]

    # tonight's rosters, with ESPN's injury status; fall back to whoever played for the team last
    playing = {}
    for g in slate:
        playing[g["home_abbreviation"]] = g["home_id"]
        playing[g["away_abbreviation"]] = g["away_id"]
    roster = {}
    for tm, tid in playing.items():
        d = espn(f"teams/{tid}/roster")
        if not d or not d.get("athletes"):
            continue
        for a in d["athletes"]:
            inj = (a.get("injuries") or [{}])[0].get("status", "") if a.get("injuries") else ""
            roster[int(a["id"])] = {"team": tm, "name": a.get("displayName"), "pos": group((a.get("position") or {}).get("abbreviation")),
                                    "inj": inj}
    rostered = {r["team"] for r in roster.values()}
    for pid, i in info.items():
        if pid not in roster and i["team"] in playing and i["team"] not in rostered:
            roster[pid] = {"team": i["team"], "name": i["name"], "pos": i["pos"], "inj": ""}
    for spid, s in prior["pl"].items():
        pid = int(spid)
        if pid not in roster and pid not in info and s["team"] in playing and s["team"] not in rostered:
            roster[pid] = {"team": s["team"], "name": s["name"], "pos": s["pos"], "inj": ""}

    players = []
    for pid, ro in roster.items():
        c = pl.get(pid, {"gp": 0, "min": 0.0, **{s: 0.0 for s in STATS}})
        pr = prior["pl"].get(str(pid))
        pos = info.get(pid, {}).get("pos") or ro["pos"] or (pr or {}).get("pos") or "F"
        if pr and pr["gp"] >= 10:
            k = K_PLAYER
            base = {f: pr[f] / pr["gp"] for f in ("min", *STATS)}
            mpg = (c["min"] + K_MIN * base["min"]) / (c["gp"] + K_MIN)
        elif c["gp"]:
            k = K_ROOKIE
            b = by_group[pos]
            base = {f: b[f] / b["gp"] for f in ("min", *STATS)}
            mpg = (c["min"] + 3 * 18) / (c["gp"] + 3)
        else:
            continue
        if mpg < MIN_MPG:
            continue
        rate = {f: round((c[f] + k * base[f]) / (c["min"] + k * base["min"]), 4) for f in STATS}
        played = cur["games_of"].get(pid, [])
        gl = played[-5:]
        n5 = len(gl)
        p = {
            "id": pid, "name": ro["name"] or info.get(pid, {}).get("name", ""), "pos": pos, "team": ro["team"],
            "mpg": round(mpg, 1), "r": rate, "sg": c["gp"], "w": round(c["gp"] / (c["gp"] + k), 2),
            "s": {f: round(c[f], 1) for f in ("min", *STATS)},
            "l5": {"n": n5, **{f: round(sum(x[j] for x in gl) / n5, 1) for f, j in (("min", 3), ("pts", 4), ("reb", 5), ("ast", 6))}} if n5 else None,
            "last": played[-1][0] if played else "",
            "inj": ro["inj"],
        }
        if not p["name"]:
            continue
        players.append(p)

    teams = {}
    for tm in sorted(set(team) | set(prior["team"])):
        c, pr = team.get(tm), prior["team"].get(tm)
        cg = c["gp"] if c else 0
        pace_base = pr["pace"] / pr["gp"] if pr and pr["gp"] else lg["pace"]
        out = {"gp": cg, "pace": round(((c["pace"] if c else 0) + K_TEAM * pace_base) / (cg + K_TEAM), 2), "allow": {}}
        for g in GROUPS:
            out["allow"][g] = {}
            for k in ("pts", "reb", "ast"):
                base = pr["allow"][g][k] / pr["gp"] if pr and pr["gp"] else lg["allow"][g][k]
                out["allow"][g][k] = round(((c["allow"][g][k] if c else 0) + K_TEAM * base) / (cg + K_TEAM), 2)
        teams[tm] = out

    games = []
    for g in slate:
        t = dt.datetime.fromisoformat(g["start_date"].replace("Z", "+00:00"))
        games.append({
            "id": int(g["game_id"]), "away": g["away_abbreviation"], "home": g["home_abbreviation"],
            "start": t.strftime("%Y-%m-%dT%H:%MZ"), "gametime": t.astimezone(ET).strftime("%H:%M"),
            "final": bool(g["status_type_completed"]),
        })

    payload = {
        "season": f"{season - 1}-{str(season)[2:]}",
        "date": today.isoformat(),
        "label": today.strftime("%a %b ") + str(today.day),
        "lg": {"pace": round(lg["pace"], 2), "star": {k: round(v, 3) for k, v in lg["star"].items()},
               "allow": {g: {k: round(v, 3) for k, v in lg["allow"][g].items()} for g in GROUPS}},
        "players": sorted(players, key=lambda p: (p["team"], p["pos"], p["name"])),
        "teams": teams,
        "games": games,
    }

    if OUT.exists():
        old = json.loads(OUT.read_text())
        old.pop("built", None)
        if old == json.loads(json.dumps(payload)):
            print("no change")
            return

    payload = {"built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), **payload}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"{payload['label']}: {len(players)} players, {len(games)} games, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
