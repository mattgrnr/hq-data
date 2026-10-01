#!/usr/bin/env python3
"""Builds nfl/board.json for Touchdown HQ from public nflverse data."""
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

REL = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
OUT = Path(__file__).resolve().parent.parent / "nfl" / "board.json"
LOCAL = os.environ.get("HQ_LOCAL")  # read files from a folder instead of downloading

POS = ("QB", "RB", "WR", "TE")
K_PLAYER = 4   # last season counts as this many games
K_DEF = 8      # defenses lean on last season longer
STAT = ("pyd", "ptd", "att", "car", "ryd", "rtd", "tgt", "rec", "cyd", "ctd")
EMIT = ("pyd", "ptd", "car", "ryd", "rtd", "tgt", "rec", "cyd", "ctd", "rz", "i5")
ROUND_LABELS = {19: "Wild Card", 20: "Divisional", 21: "Conference", 22: "Super Bowl"}


def fetch(url, tries=3):
    if LOCAL:
        p = Path(LOCAL) / url.rsplit("/", 1)[-1]
        return p.read_text() if p.exists() else ""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hq-data"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            last = e
        except Exception as e:
            last = e
        time.sleep(10 * (i + 1))
    raise last


def rows(text):
    return list(csv.DictReader(io.StringIO(text))) if text else []


def num(v):
    try:
        return float(v) if v not in ("", "NA", None) else 0.0
    except ValueError:
        return 0.0


def rel(path):
    return fetch(f"{REL}/{path}")


# ---------- schedule ----------

def pick_season(games, today):
    starts = {}
    for g in games:
        if g["game_type"] != "REG":
            continue
        s = int(g["season"])
        d = dt.date.fromisoformat(g["gameday"])
        if s not in starts or d < starts[s]:
            starts[s] = d
    live = [s for s, d in starts.items() if d <= today + dt.timedelta(days=14)]
    return max(live) if live else max(starts)


def pick_week(season_games):
    open_weeks = [int(g["week"]) for g in season_games if g["home_score"] == ""]
    if open_weeks:
        return min(open_weeks)
    return max(int(g["week"]) for g in season_games)


# ---------- play-by-play: red-zone usage and defense vs position ----------

def scan_pbp(text, pos_of):
    rz = defaultdict(lambda: [0, 0])                     # player -> [inside 20, inside 5]
    dvp = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))  # def -> pos -> [td, yds, rz plays, rz tds]
    def_games = defaultdict(set)
    if not text:
        return rz, dvp, def_games

    reader = csv.reader(io.StringIO(text))
    hdr = next(reader)
    c = {h: i for i, h in enumerate(hdr)}
    need = ("play_type", "yardline_100", "yards_gained", "defteam", "game_id", "rusher_player_id",
            "receiver_player_id", "passer_player_id", "rush_touchdown", "pass_touchdown", "two_point_attempt")
    ix = {k: c[k] for k in need}

    for f in reader:
        pt = f[ix["play_type"]]
        if pt not in ("run", "pass") or f[ix["two_point_attempt"]] == "1":
            continue
        d = f[ix["defteam"]]
        def_games[d].add(f[ix["game_id"]])
        yl = num(f[ix["yardline_100"]]) or 999
        yds = num(f[ix["yards_gained"]])
        in20, in5 = yl <= 20, yl <= 5

        if pt == "run":
            pid, scored = f[ix["rusher_player_id"]], f[ix["rush_touchdown"]] == "1"
        else:
            pid, scored = f[ix["receiver_player_id"]], f[ix["pass_touchdown"]] == "1"

        if pid:
            rz[pid][0] += in20
            rz[pid][1] += in5
            pos = pos_of.get(pid)
            if pos in POS:
                cell = dvp[d][pos]
                cell[0] += scored
                cell[1] += yds
                if in20:
                    cell[2] += 1
                    cell[3] += scored

        if pt == "pass":
            qb = f[ix["passer_player_id"]]
            if qb:
                rz["qb:" + qb][0] += in20
                rz["qb:" + qb][1] += in5
            cell = dvp[d]["QB"]
            cell[0] += f[ix["pass_touchdown"]] == "1"
            cell[1] += yds
            if in20:
                cell[2] += 1
                cell[3] += f[ix["pass_touchdown"]] == "1"
    return rz, dvp, def_games


def rz_for(rz, pid, pos):
    a, b = rz.get(pid, (0, 0))
    if pos == "QB":
        qa, qb = rz.get("qb:" + pid, (0, 0))
        a, b = a + qa, b + qb
    return a, b


# ---------- build ----------

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    games = rows(fetch(GAMES_URL))
    season = pick_season(games, today)
    prior = season - 1

    season_games = [g for g in games if int(g["season"]) == season]
    week = pick_week(season_games)
    week_games = [g for g in season_games if int(g["week"]) == week]

    played = defaultdict(int)
    for g in season_games:
        if g["home_score"] != "":
            played[g["home_team"]] += 1
            played[g["away_team"]] += 1

    # last season, per player
    prior_stats = rows(rel(f"stats_player/stats_player_reg_{prior}.csv"))
    # this season, per player per week
    cur_weekly = rows(rel(f"stats_player/stats_player_week_{season}.csv"))
    roster_rows = rows(rel(f"weekly_rosters/roster_weekly_{season}.csv"))
    injury_rows = rows(rel(f"injuries/injuries_{season}.csv"))

    pos_of = {}
    for r in prior_stats:
        pos_of[r["player_id"]] = r["position"]
    for r in cur_weekly:
        pos_of[r["player_id"]] = r["position"]
    for r in roster_rows:
        if r["gsis_id"]:
            pos_of[r["gsis_id"]] = r["position"]

    rz_prior, dvp_prior, dg_prior = scan_pbp(rel(f"pbp/play_by_play_{prior}.csv"), pos_of)
    rz_cur, dvp_cur, dg_cur = scan_pbp(rel(f"pbp/play_by_play_{season}.csv"), pos_of)

    # league TD rates, used to steady players with no prior season
    lg = defaultdict(lambda: defaultdict(float))
    for r in prior_stats:
        if r["position"] in POS:
            t = lg[r["position"]]
            t["ptd"] += num(r["passing_tds"]); t["att"] += num(r["attempts"])
            t["rtd"] += num(r["rushing_tds"]); t["car"] += num(r["carries"])
            t["ctd"] += num(r["receiving_tds"]); t["tgt"] += num(r["targets"])

    def lg_rate(pos, td, opp):
        t = lg[pos]
        return t[td] / t[opp] if t[opp] else 0.0

    priors = {}
    for r in prior_stats:
        if r["position"] not in POS:
            continue
        g = num(r["games"])
        if g < 4:
            continue
        if num(r["carries"]) + num(r["targets"]) < 25 and num(r["passing_yards"]) < 800:
            continue
        a, b = rz_for(rz_prior, r["player_id"], r["position"])
        priors[r["player_id"]] = {
            "g": g, "team": r["recent_team"],
            "pyd": num(r["passing_yards"]), "ptd": num(r["passing_tds"]), "att": num(r["attempts"]),
            "car": num(r["carries"]), "ryd": num(r["rushing_yards"]), "rtd": num(r["rushing_tds"]),
            "tgt": num(r["targets"]), "rec": num(r["receptions"]), "cyd": num(r["receiving_yards"]),
            "ctd": num(r["receiving_tds"]), "rz": a, "i5": b,
        }

    cur = defaultdict(lambda: defaultdict(float))
    cur_weeks = defaultdict(set)
    td_week = defaultdict(int)
    stats_in = set()
    team_last_week = {}
    qb_att_by_week = defaultdict(lambda: defaultdict(float))  # (team, week) -> qb -> attempts
    for r in cur_weekly:
        pid, wk, tm = r["player_id"], int(r["week"]), r["team"]
        if wk == week:
            stats_in.add(tm)
            td_week[pid] = int(num(r["rushing_tds"]) + num(r["receiving_tds"]))
        if r["position"] not in POS:
            continue
        cur_weeks[pid].add(wk)
        c = cur[pid]
        c["pyd"] += num(r["passing_yards"]); c["ptd"] += num(r["passing_tds"]); c["att"] += num(r["attempts"])
        c["car"] += num(r["carries"]); c["ryd"] += num(r["rushing_yards"]); c["rtd"] += num(r["rushing_tds"])
        c["tgt"] += num(r["targets"]); c["rec"] += num(r["receptions"]); c["cyd"] += num(r["receiving_yards"])
        c["ctd"] += num(r["receiving_tds"])
        team_last_week[tm] = max(team_last_week.get(tm, 0), wk)
        if r["position"] == "QB":
            qb_att_by_week[(tm, wk)][pid] += num(r["attempts"])

    # current roster: latest week each player appears
    roster = {}
    for r in roster_rows:
        pid = r["gsis_id"]
        if not pid or r["position"] not in POS:
            continue
        wk = int(r["week"])
        if pid not in roster or wk >= roster[pid]["week"]:
            roster[pid] = {"week": wk, "team": r["team"], "status": r["status"], "name": r["full_name"], "pos": r["position"]}

    # injury designations for this week; carry last week's Out until this week's report is final
    inj_now, inj_prev = {}, {}
    for r in injury_rows:
        wk = int(r["week"])
        if wk == week and r["report_status"]:
            inj_now[r["gsis_id"]] = r["report_status"]
        elif wk == week - 1 and r["report_status"]:
            inj_prev[r["gsis_id"]] = r["report_status"]

    game_day = {}
    for g in week_games:
        d = dt.date.fromisoformat(g["gameday"])
        game_day[g["home_team"]] = d
        game_day[g["away_team"]] = d

    # game-status reports are final two days before kickoff; earlier Outs still count
    def injury(pid, team):
        now = inj_now.get(pid, "")
        if team in game_day and today >= game_day[team] - dt.timedelta(days=2):
            return now
        if now:
            return now
        return "Out" if inj_prev.get(pid) == "Out" else ""

    # one QB per team: whoever threw the most in the team's latest game
    def starting_qb(team, candidates):
        lw = team_last_week.get(team)
        recent = qb_att_by_week.get((team, lw), {}) if lw else {}
        def key(pid):
            return (recent.get(pid, 0), cur[pid]["att"], priors.get(pid, {}).get("pyd", 0))
        return max(candidates, key=key) if candidates else None

    built = []
    qb_pool = defaultdict(list)
    for pid, ro in roster.items():
        if ro["status"] != "ACT":
            continue
        pos, team = ro["pos"], ro["team"]
        pr = priors.get(pid)
        gc = len(cur_weeks.get(pid, ()))
        if not pr and gc == 0:
            continue
        if played.get(team, 0) >= 2 and gc == 0:
            continue
        status = injury(pid, team)
        if status == "Out":
            continue

        c = cur[pid]
        a, b = rz_for(rz_cur, pid, pos)
        c["rz"], c["i5"] = a, b

        p = {"id": pid, "name": ro["name"], "pos": pos, "team": team}
        if pr:
            ge = gc + K_PLAYER
            for k in STAT + ("rz", "i5"):
                p[k] = c[k] + K_PLAYER * pr[k] / pr["g"]
            p["w"] = round(gc / ge, 2)
            p["newteam"] = pr["team"] != team
        else:
            ge = gc
            for k in STAT + ("rz", "i5"):
                p[k] = c[k]
            exp = {
                "ptd": c["att"] / gc * lg_rate(pos, "ptd", "att"),
                "rtd": c["car"] / gc * lg_rate(pos, "rtd", "car"),
                "ctd": c["tgt"] / gc * lg_rate(pos, "ctd", "tgt"),
            }
            for k, e in exp.items():
                p[k] = (c[k] + K_PLAYER * e) / (gc + K_PLAYER) * gc
            p["w"] = 1
        p["g"] = ge
        p["sg"] = gc
        p["s"] = {k: int(round(c[k])) for k in EMIT}
        if status in ("Doubtful", "Questionable"):
            p["st"] = status[0]
        if gc and td_week.get(pid):
            p["td"] = td_week[pid]

        if pos == "QB":
            qb_pool[team].append(p)
            continue
        if (p["car"] + p["tgt"]) / ge < 2.0:
            continue
        built.append(p)

    for team, qbs in qb_pool.items():
        best = starting_qb(team, [q["id"] for q in qbs])
        built.extend(q for q in qbs if q["id"] == best)

    players = []
    for p in sorted(built, key=lambda x: (x["team"], x["pos"], x["name"])):
        out = {k: p[k] for k in ("id", "name", "pos", "team")}
        out["g"] = round(p["g"], 2)
        for k in EMIT:
            out[k] = round(p[k], 2)
        out["sg"] = p["sg"]
        out["s"] = p["s"]
        out["w"] = p["w"]
        for k in ("newteam", "st", "td"):
            if p.get(k):
                out[k] = p[k]
        players.append(out)

    # defense vs position, blended per game, expressed per 17 games
    dvp = {}
    for d in sorted(set(dg_prior) | set(dg_cur)):
        pg_prior, pg_cur = len(dg_prior.get(d, ())), len(dg_cur.get(d, ()))
        dvp[d] = {}
        for pos in POS:
            pv = dvp_prior[d][pos] if d in dvp_prior else [0.0] * 4
            cv = dvp_cur[d][pos] if d in dvp_cur else [0.0] * 4
            vals = []
            for i in range(4):
                base = pv[i] / pg_prior if pg_prior else 0.0
                rate = (cv[i] + K_DEF * base) / (pg_cur + K_DEF) if (pg_cur or pg_prior) else 0.0
                vals.append(rate * 17)
            dvp[d][pos] = [round(vals[0], 2), int(round(vals[1])), 17, round(vals[2], 1), round(vals[3], 1)]

    def line(v):
        return None if v in ("", "NA") else float(v)

    slate = []
    for g in sorted(week_games, key=lambda x: (x["gameday"], x["gametime"], x["home_team"])):
        final = g["home_score"] != ""
        slate.append({
            "away": g["away_team"], "home": g["home_team"],
            "gameday": g["gameday"], "gametime": g["gametime"],
            "spread": line(g["spread_line"]), "total": line(g["total_line"]),
            "roof": g["roof"] or "",
            "final": final,
            "statsIn": final and g["home_team"] in stats_in and g["away_team"] in stats_in,
        })

    payload = {
        "season": season,
        "week": week,
        "label": ROUND_LABELS.get(week, f"Week {week}"),
        "players": players,
        "dvp": dvp,
        "games": slate,
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
    print(f"{payload['label']} {season}: {len(players)} players, {len(slate)} games, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
