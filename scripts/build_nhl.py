#!/usr/bin/env python3
"""Builds nhl/board.json for Slapshot HQ from public sportsdataverse NHL data."""
import csv
import datetime as dt
import io
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

REL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
ROOT = Path(__file__).resolve().parent.parent / "nhl"
OUT = ROOT / "board.json"
LOCAL = os.environ.get("HQ_LOCAL")  # read files from a folder instead of downloading
ET = ZoneInfo("America/New_York")

K_PLAYER = 20   # last season counts as this many games
K_ROOKIE = 10   # no history: lean on the league average for the position group
K_TEAM = 20
K_GOALIE = 25   # in expected goals faced
SHOTS = ("SHOT", "MISSED_SHOT", "GOAL")
PP_STATES = ("5v4", "5v3", "4v3")
TOP6_TOI = 15.5


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


def toi_min(v):
    try:
        m, s = str(v).split(":")
        return int(m) + int(s) / 60
    except ValueError:
        return 0.0


def group(pos):
    return "D" if pos == "D" else "F"


# ---------- one season of raw totals ----------

PBP_COLS = ["event_type", "event_player_1_id", "event_player_1_name", "event_player_2_id", "event_player_2_name",
            "event_player_3_id", "event_player_3_name", "event_team_abbr", "xg", "strength_state",
            "empty_net", "event_goalie_id", "game_id", "season_type"]


def season_totals(season):
    box = [r for r in parquet(f"nhl_player_boxscores/player_box_{season}.parquet") if str(r["game_id"])[4:6] == "02"]
    pbp = [r for r in parquet(f"nhl_pbp_lite/play_by_play_lite_{season}.parquet", PBP_COLS) if r["season_type"] == "R"]

    sk = defaultdict(lambda: {"gp": 0, "g": 0, "a": 0, "sog": 0, "ppg": 0, "toi": 0.0, "ixg": 0.0, "att": 0, "ppx": 0.0})
    info, games_of = {}, defaultdict(list)
    team = defaultdict(lambda: {"gp": 0, "gf": 0, "ga": 0, "sf": 0, "sa": 0, "xgf": 0.0, "xga": 0.0})
    goalie = defaultdict(lambda: {"starts": 0, "sa": 0, "ga": 0, "xga": 0.0})
    game_teams, team_goals, team_shots, starters = defaultdict(set), defaultdict(int), defaultdict(int), {}

    for r in box:
        gid, tm, pid = int(r["game_id"]), r["team_abbrev"], int(r["player_id"])
        game_teams[gid].add(tm)
        if not r["position"]:
            if r["starter"] in (True, "True", "true"):
                starters[(gid, tm)] = pid
                goalie[pid]["starts"] += 1
            goalie[pid]["sa"] += int(num(r["shots_against"]))
            goalie[pid]["ga"] += int(num(r["goals_against"]))
            info.setdefault(pid, {"name": r["player_name"], "pos": "G"})
            info[pid]["team"] = tm
            continue
        t = toi_min(r["toi"])
        if t <= 0:
            continue
        s = sk[pid]
        s["gp"] += 1
        s["g"] += int(num(r["goals"]))
        s["a"] += int(num(r["assists"]))
        s["sog"] += int(num(r["shots_on_goal"]))
        s["ppg"] += int(num(r["power_play_goals"]))
        s["toi"] += t
        info.setdefault(pid, {"name": r["player_name"], "pos": r["position"]})
        info[pid]["team"], info[pid]["pos"] = tm, r["position"]
        games_of[pid].append((r["game_date"], gid, tm))
        team_goals[(gid, tm)] += int(num(r["goals"]))
        team_shots[(gid, tm)] += int(num(r["shots_on_goal"]))

    for gid, tms in game_teams.items():
        if len(tms) != 2:
            continue
        a, b = sorted(tms)
        for me, op in ((a, b), (b, a)):
            t = team[me]
            t["gp"] += 1
            t["gf"] += team_goals[(gid, me)]
            t["ga"] += team_goals[(gid, op)]
            t["sf"] += team_shots[(gid, me)]
            t["sa"] += team_shots[(gid, op)]

    full = {}
    for r in pbp:
        for i in (1, 2, 3):
            pid, nm = r[f"event_player_{i}_id"], r[f"event_player_{i}_name"]
            if pid and nm:
                full[int(pid)] = nm
        if r["event_type"] not in SHOTS or r["empty_net"] or r["xg"] is None:
            continue
        x, tm = float(r["xg"]), r["event_team_abbr"]
        shooter = int(r["event_player_1_id"]) if r["event_player_1_id"] else None
        if shooter:
            s = sk[shooter]
            s["ixg"] += x
            s["att"] += 1
            if r["strength_state"] in PP_STATES:
                s["ppx"] += x
        team[tm]["xgf"] += x
        gid = int(r["game_id"])
        opp = [o for o in game_teams.get(gid, ()) if o != tm]
        if opp:
            team[opp[0]]["xga"] += x
        if r["event_goalie_id"]:
            goalie[int(r["event_goalie_id"])]["xga"] += x

    for pid, nm in full.items():
        if pid in info:
            info[pid]["name"] = nm
    return {"sk": sk, "info": info, "games_of": games_of, "team": team, "goalie": goalie, "starters": starters,
            "game_teams": game_teams}


def prior_profile(season):
    """Per-game rates from a finished season, cached in the repo since they never change."""
    path = ROOT / f"prior_{season}.json"
    if path.exists():
        return json.loads(path.read_text())
    t = season_totals(season)
    if not t["sk"]:
        return {"sk": {}, "team": {}, "goalie": {}}
    out = {
        "sk": {str(pid): {**{k: round(v, 3) for k, v in s.items()}, "pos": t["info"].get(pid, {}).get("pos", "")}
               for pid, s in t["sk"].items() if s["gp"]},
        "team": {tm: {k: round(v, 2) for k, v in s.items()} for tm, s in t["team"].items()},
        "goalie": {str(pid): {k: round(v, 2) for k, v in s.items()} for pid, s in t["goalie"].items()},
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":")))
    return out


# ---------- board ----------

def main():
    now = dt.datetime.now(ET)
    today = dt.date.fromisoformat(os.environ["TODAY"]) if os.environ.get("TODAY") else now.date()
    season = today.year + 1 if today.month >= 8 else today.year
    prior = prior_profile(season - 1)

    sched = list(csv.DictReader(io.StringIO(fetch(f"nhl_schedules/nhl_schedule_{season}.csv").decode("utf-8"))))
    sched = [g for g in sched if g["game_type"] == "R"]
    slate = sorted((g for g in sched if g["game_date"] == today.isoformat()), key=lambda g: (g["game_time"], g["home_team_abbr"]))

    cur = season_totals(season)
    sk, info, team, goalie = cur["sk"], cur["info"], cur["team"], cur["goalie"]

    # skater baselines: a typical top-six forward (15.5+ minutes a night), last season and this one together
    tot = defaultdict(float)
    for src in (prior["sk"].values(), [{**s, "pos": info.get(pid, {}).get("pos", "")} for pid, s in sk.items()]):
        for s in src:
            if group(s.get("pos", "")) == "F" and s["gp"] >= 5 and s["toi"] / s["gp"] >= TOP6_TOI:
                for k in ("gp", "g", "sog", "ixg", "att", "ppx", "toi"):
                    tot[k] += s[k]
    by_group = defaultdict(lambda: defaultdict(float))
    for src in (prior["sk"].values(), [{**s, "pos": info.get(pid, {}).get("pos", "")} for pid, s in sk.items()]):
        for s in src:
            gr = group(s.get("pos", ""))
            for k in ("gp", "g", "sog", "ixg", "att", "ppx", "toi"):
                by_group[gr][k] += s[k]
    tt = defaultdict(float)
    for src in (prior["team"].values(), team.values()):
        for t in src:
            for k in ("gp", "gf", "xgf", "sf"):
                tt[k] += t[k]
    lg = {
        "sog": tot["sog"] / tot["gp"], "ixg": tot["ixg"] / tot["gp"], "gl": tot["g"] / tot["gp"],
        "ppx": tot["ppx"] / tot["gp"], "xpa": tot["ixg"] / tot["att"], "toi": tot["toi"] / tot["gp"],
        "gf": tt["gf"] / tt["gp"], "xg": tt["xgf"] / tt["gp"], "sf": tt["sf"] / tt["gp"],
    }

    # who dressed in each team's latest game
    last_game = {}
    for pid, gl in cur["games_of"].items():
        for date, gid, tm in gl:
            if tm not in last_game or (date, gid) > last_game[tm]:
                last_game[tm] = (date, gid)
    dressed = defaultdict(set)
    for pid, gl in cur["games_of"].items():
        for date, gid, tm in gl:
            if last_game.get(tm) == (date, gid) and info[pid]["team"] == tm:
                dressed[tm].add(pid)

    playing = {g["home_team_abbr"] for g in slate} | {g["away_team_abbr"] for g in slate}

    players = []
    for tm in sorted(playing):
        for pid in dressed.get(tm, ()):
            c, i = sk[pid], info[pid]
            gc = c["gp"]
            pr = prior["sk"].get(str(pid))
            p = {"id": pid, "name": i["name"], "pos": i["pos"], "team": tm}
            if pr and pr["gp"] >= 10:
                k = K_PLAYER
                base = {f: pr[f] / pr["gp"] for f in ("g", "sog", "ixg", "att", "ppx", "toi")}
            else:
                k = K_ROOKIE
                b = by_group[group(i["pos"])]
                base = {f: b[f] / b["gp"] for f in ("g", "sog", "ixg", "att", "ppx", "toi")}
            for f in ("g", "sog", "ixg", "att", "ppx", "toi"):
                p[f] = round(c[f] + k * base[f], 3)
            p["gp"] = gc + k
            p["sg"] = gc
            p["w"] = round(gc / (gc + k), 2)
            p["s"] = {"g": c["g"], "a": c["a"], "sog": c["sog"], "ppg": c["ppg"], "toi": round(c["toi"], 1)}
            players.append(p)

    teams = {}
    for tm in sorted(set(team) | set(prior["team"])):
        c, pr = team.get(tm, {"gp": 0, "gf": 0, "ga": 0, "sf": 0, "sa": 0, "xgf": 0.0, "xga": 0.0}), prior["team"].get(tm)
        out = {}
        for f in ("gf", "ga", "sf", "sa", "xgf", "xga"):
            base = pr[f] / pr["gp"] if pr and pr["gp"] else {"gf": lg["gf"], "ga": lg["gf"], "sf": lg["sf"], "sa": lg["sf"], "xgf": lg["xg"], "xga": lg["xg"]}[f]
            out[f] = round((c[f] + K_TEAM * base) / (c["gp"] + K_TEAM), 3)
        out["gp"] = c["gp"]
        teams[tm] = out

    # likely starting goalie: most starts in the last five, unless he started yesterday
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    team_games = defaultdict(list)
    for (gid, tm), pid in cur["starters"].items():
        team_games[tm].append((gid, pid))
    game_date = {int(g["game_id"]): g["game_date"] for g in sched}
    gsum = defaultdict(float)
    for src in (prior["goalie"].values(), goalie.values()):
        for g in src:
            gsum["ga"] += g["ga"]
            gsum["xga"] += g["xga"]
    lgr = gsum["ga"] / gsum["xga"] if gsum["xga"] else 1.0
    goalies = {}
    for tm in sorted(playing):
        recent = sorted(team_games.get(tm, []), reverse=True)[:5]
        if not recent:
            continue
        counts = defaultdict(int)
        for _, pid in recent:
            counts[pid] += 1
        order = sorted(counts, key=lambda pid: (-counts[pid], -max(g for g, q in recent if q == pid)))
        pick = order[0]
        b2b = game_date.get(recent[0][0]) == yesterday
        if b2b and recent[0][1] == pick:
            others = [q for q in order if q != pick]
            if others:
                pick = others[0]
        c = goalie.get(pick, {"starts": 0, "sa": 0, "ga": 0, "xga": 0.0})
        pr = prior["goalie"].get(str(pick), {"starts": 0, "sa": 0, "ga": 0, "xga": 0.0})
        ga, xga, sa = c["ga"] + pr["ga"], c["xga"] + pr["xga"], c["sa"] + pr["sa"]
        goalies[tm] = {
            "id": pick, "name": info.get(pick, {}).get("name", ""),
            "starts": c["starts"],
            "sv": round(1 - c["ga"] / c["sa"], 3) if c["sa"] else None,
            "ratio": round((ga + K_GOALIE * lgr) / (xga + K_GOALIE) / lgr, 3),
            "b2b": b2b,
        }

    games = []
    for g in slate:
        t = dt.datetime.fromisoformat(g["game_time"].replace("Z", "+00:00"))
        games.append({
            "id": int(g["game_id"]), "away": g["away_team_abbr"], "home": g["home_team_abbr"],
            "start": t.strftime("%Y-%m-%dT%H:%MZ"), "gametime": t.astimezone(ET).strftime("%H:%M"),
            "final": g["game_state"] in ("OFF", "FINAL"),
        })

    payload = {
        "season": f"{season - 1}-{str(season)[2:]}",
        "date": today.isoformat(),
        "label": today.strftime("%a %b ") + str(today.day),
        "lg": {k: round(v, 4) for k, v in lg.items()},
        "players": sorted(players, key=lambda p: (p["team"], p["pos"], p["name"])),
        "teams": teams,
        "goalies": goalies,
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
    print(f"{payload['label']}: {len(players)} skaters, {len(games)} games, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
