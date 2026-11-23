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
from zoneinfo import ZoneInfo

REL = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
IDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
ET = ZoneInfo("America/New_York")
OUT = Path(__file__).resolve().parent.parent / "nfl" / "board.json"
LOCAL = os.environ.get("HQ_LOCAL")  # read files from a folder instead of downloading
REPLAY_WEEK = int(os.environ.get("REPLAY_WEEK") or 0)  # rebuild a past week's board from what was known before it

POS = ("QB", "RB", "WR", "TE")
K_PLAYER = 4   # TD rates lean on the league rate per opportunity until he has ~4 games
K_DEF = 4      # defenses lean on the league average early on
STAT = ("pyd", "ptd", "att", "car", "ryd", "rtd", "tgt", "rec", "cyd", "ctd")
HIST_SEASONS = 3  # head to head looks back this many seasons before this one
LOGCOLS = ["pyd", "ptd", "car", "ryd", "rtd", "tgt", "rec", "cyd", "ctd"]
LOGSRC = ["passing_yards", "passing_tds", "carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds"]
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


def pick_week(season_games, today):
    open_weeks = [int(g["week"]) for g in season_games if g["home_score"] == ""]
    if not open_weeks:
        return max(int(g["week"]) for g in season_games)
    week = min(open_weeks)
    # a finished week stays up until two days after its last game (Monday night -> Wednesday)
    done = [dt.date.fromisoformat(g["gameday"]) for g in season_games if int(g["week"]) == week - 1]
    if done and today < max(done) + dt.timedelta(days=2):
        return week - 1
    return week


def qb_depth(text, today):
    """team -> {gsis_id: rank} from the latest depth chart snapshot, if it is recent."""
    snaps = defaultdict(dict)
    if not text:
        return {}
    rd = csv.reader(io.StringIO(text))
    hdr = next(rd, None)
    if not hdr:
        return {}
    c = {h: i for i, h in enumerate(hdr)}
    for f in rd:
        if f[c["dt"]][:10] > today.isoformat():
            continue
        if f[c["pos_abb"]] == "QB" and f[c["gsis_id"]]:
            snaps[f[c["dt"]][:10]].setdefault(f[c["team"]], {})[f[c["gsis_id"]]] = int(f[c["pos_rank"]])
    if not snaps:
        return {}
    latest = max(snaps)
    if dt.date.fromisoformat(latest) < today - dt.timedelta(days=4):
        return {}
    return snaps[latest]


# ---------- play-by-play: red-zone usage and defense vs position ----------

def scan_pbp(text, pos_of, max_week=99):
    rz = defaultdict(lambda: [0, 0])                     # player -> [inside 20, inside 5]
    # def -> pos -> [td, yds, rz plays, rz tds, rush yds, rec yds, receptions]
    dvp = defaultdict(lambda: defaultdict(lambda: [0.0] * 7))
    def_games = defaultdict(set)
    if not text:
        return rz, dvp, def_games

    reader = csv.reader(io.StringIO(text))
    hdr = next(reader)
    c = {h: i for i, h in enumerate(hdr)}
    need = ("play_type", "yardline_100", "yards_gained", "defteam", "game_id", "rusher_player_id",
            "receiver_player_id", "passer_player_id", "rush_touchdown", "pass_touchdown", "two_point_attempt",
            "complete_pass")
    ix = {k: c[k] for k in need}

    for f in reader:
        if int(f[ix["game_id"]].split("_")[1]) > max_week:
            continue
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
                if pt == "run":
                    cell[4] += yds
                elif f[ix["complete_pass"]] == "1":
                    cell[5] += yds
                    cell[6] += 1

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

    season_games = [g for g in games if int(g["season"]) == season]
    week = pick_week(season_games, today)
    dest = OUT
    if REPLAY_WEEK:
        # as of the day before the week's first game: later results are blanked and later stats dropped
        week = REPLAY_WEEK
        today = min(dt.date.fromisoformat(g["gameday"]) for g in season_games if int(g["week"]) == week) - dt.timedelta(days=1)
        for g in season_games:
            if int(g["week"]) >= week:
                g["home_score"] = g["away_score"] = ""
        dest = OUT.parent / "replay" / f"w{week:02d}.json"
    week_games = [g for g in season_games if int(g["week"]) == week]

    played = defaultdict(int)
    for g in season_games:
        if g["home_score"] != "":
            played[g["home_team"]] += 1
            played[g["away_team"]] += 1

    # this season, per player per week
    cur_weekly = rows(rel(f"stats_player/stats_player_week_{season}.csv"))
    roster_rows = rows(rel(f"weekly_rosters/roster_weekly_{season}.csv"))
    injury_rows = rows(rel(f"injuries/injuries_{season}.csv"))
    if REPLAY_WEEK:
        cur_weekly = [r for r in cur_weekly if int(r["week"]) < week]
        roster_rows = [r for r in roster_rows if int(r["week"]) <= week]
        injury_rows = [r for r in injury_rows if int(r["week"]) <= week]
    depth = qb_depth(rel(f"depth_charts/depth_charts_{season}.csv"), today)

    # sleeper ids let the site match live in-game stats; the board still builds without them
    sleeper = {}
    try:
        for r in rows(fetch(IDS_URL)):
            if r["gsis_id"] and r["sleeper_id"] not in ("", "NA"):
                sleeper[r["gsis_id"]] = r["sleeper_id"]
    except Exception as e:
        print("player ids unavailable:", e)

    pos_of = {}
    for r in cur_weekly:
        pos_of[r["player_id"]] = r["position"]
    for r in roster_rows:
        if r["gsis_id"]:
            pos_of[r["gsis_id"]] = r["position"]

    rz_cur, dvp_cur, dg_cur = scan_pbp(rel(f"pbp/play_by_play_{season}.csv"), pos_of, week - 1 if REPLAY_WEEK else 99)

    # league TD rates per opportunity this season, used to steady small samples
    lg = defaultdict(lambda: defaultdict(float))
    for r in cur_weekly:
        if r["position"] in POS:
            t = lg[r["position"]]
            t["ptd"] += num(r["passing_tds"]); t["att"] += num(r["attempts"])
            t["rtd"] += num(r["rushing_tds"]); t["car"] += num(r["carries"])
            t["ctd"] += num(r["receiving_tds"]); t["tgt"] += num(r["targets"])

    def lg_rate(pos, td, opp):
        t = lg[pos]
        return t[td] / t[opp] if t[opp] else 0.0

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

    # one QB per team: highest on the depth chart among those not ruled out,
    # then whoever threw the most in the team's latest game
    def starting_qb(team, candidates):
        lw = team_last_week.get(team)
        recent = qb_att_by_week.get((team, lw), {}) if lw else {}
        ranks = depth.get(team, {})
        def key(pid):
            return (-ranks.get(pid, 99), recent.get(pid, 0), cur[pid]["att"])
        return max(candidates, key=key) if candidates else None

    built = []
    qb_pool = defaultdict(list)
    for pid, ro in roster.items():
        if ro["status"] != "ACT":
            continue
        pos, team = ro["pos"], ro["team"]
        gc = len(cur_weeks.get(pid, ()))
        if gc == 0:
            continue
        status = injury(pid, team)
        if status == "Out":
            continue

        c = cur[pid]
        a, b = rz_for(rz_cur, pid, pos)
        c["rz"], c["i5"] = a, b

        p = {"id": pid, "name": ro["name"], "pos": pos, "team": team}
        ge = gc
        for k in STAT + ("rz", "i5"):
            p[k] = c[k]
        # TD rates lean on the league rate for his opportunities until the sample builds
        exp = {
            "ptd": c["att"] / gc * lg_rate(pos, "ptd", "att"),
            "rtd": c["car"] / gc * lg_rate(pos, "rtd", "car"),
            "ctd": c["tgt"] / gc * lg_rate(pos, "ctd", "tgt"),
        }
        for k, e in exp.items():
            p[k] = (c[k] + K_PLAYER * e) / (gc + K_PLAYER) * gc
        p["w"] = round(gc / (gc + K_PLAYER), 2)
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
        if p["id"] in sleeper:
            out["sl"] = sleeper[p["id"]]
        for k in ("newteam", "st", "td"):
            if p.get(k):
                out[k] = p[k]
        players.append(out)

    # last five games and every game against this week's opponent, newest first: [season-week, opp, *LOGCOLS]
    opp_of = {}
    for g in week_games:
        opp_of[g["home_team"]] = g["away_team"]
        opp_of[g["away_team"]] = g["home_team"]
    want = {p["id"]: opp_of.get(p["team"]) for p in players}
    def log(r):
        return [f'{r["season"]}-W{int(r["week"]):02d}', r["opponent_team"], *[int(num(r[k])) for k in LOGSRC]]
    hist = [r for r in cur_weekly if r["player_id"] in want and int(r["week"]) < week]
    for yr in range(season - HIST_SEASONS, season):
        try:
            hist += [r for r in rows(rel(f"stats_player/stats_player_week_{yr}.csv")) if r["player_id"] in want]
        except Exception as e:
            print(f"h2h {yr}: {type(e).__name__}")
    gl, vs = defaultdict(list), defaultdict(list)
    for r in hist:
        x = log(r)
        if r["season"] == str(season):
            gl[r["player_id"]].append(x)
        if want[r["player_id"]] and r["opponent_team"] == want[r["player_id"]]:
            vs[r["player_id"]].append([x[0], *x[2:]])
    for p in players:
        p["gl"] = sorted(gl.get(p["id"], []), reverse=True)[:5]
        g = sorted(vs.get(p["id"], []), reverse=True)
        p["vs"] = {"opp": want[p["id"]], "gp": len(g), "g": g}

    # defense vs position this season, leaning on the league average early, expressed per 17 games
    lg_def = {pos: [0.0] * 7 for pos in POS}
    lg_games = sum(len(v) for v in dg_cur.values())
    for d in dvp_cur:
        for pos in POS:
            for i in range(7):
                lg_def[pos][i] += dvp_cur[d][pos][i]
    dvp = {}
    for d in sorted(dg_cur):
        pg = len(dg_cur[d])
        dvp[d] = {}
        for pos in POS:
            cv = dvp_cur[d][pos]
            vals = [(cv[i] + K_DEF * (lg_def[pos][i] / lg_games if lg_games else 0.0)) / (pg + K_DEF) * 17 for i in range(7)]
            # [td, yds, 17, rz plays, rz tds, rush yds, rec yds, receptions], all per 17 games
            dvp[d][pos] = [round(vals[0], 2), int(round(vals[1])), 17, round(vals[2], 1), round(vals[3], 1),
                           int(round(vals[4])), int(round(vals[5])), round(vals[6], 1)]

    def line(v):
        return None if v in ("", "NA") else float(v)

    def kickoff(g):
        try:
            t = dt.datetime.fromisoformat(f"{g['gameday']}T{g['gametime']}").replace(tzinfo=ET)
            return int(t.timestamp())
        except ValueError:
            return None

    slate = []
    for g in sorted(week_games, key=lambda x: (x["gameday"], x["gametime"], x["home_team"])):
        final = g["home_score"] != ""
        slate.append({
            "away": g["away_team"], "home": g["home_team"],
            "gameday": g["gameday"], "gametime": g["gametime"],
            "spread": line(g["spread_line"]), "total": line(g["total_line"]),
            "roof": g["roof"] or "",
            "ko": kickoff(g),
            "final": final,
            "statsIn": final and g["home_team"] in stats_in and g["away_team"] in stats_in,
        })

    # points for and against per team from this season's finished games before this week (for the game projections)
    tpts = defaultdict(lambda: [0, 0, 0])
    for g in season_games:
        if g["game_type"] != "REG" or g["home_score"] in ("", "NA") or int(g["week"]) >= week:
            continue
        hs, as_ = int(g["home_score"]), int(g["away_score"])
        for me, pf, pa in ((g["home_team"], hs, as_), (g["away_team"], as_, hs)):
            t = tpts[me]
            t[0] += 1
            t[1] += pf
            t[2] += pa
    gp_all = sum(t[0] for t in tpts.values())
    lg_ppg = sum(t[1] for t in tpts.values()) / gp_all if gp_all else 22.5
    teams = {tm: {"gp": t[0], "pf": round((t[1] + 4 * lg_ppg) / (t[0] + 4), 2), "pa": round((t[2] + 4 * lg_ppg) / (t[0] + 4), 2)}
             for tm, t in sorted(tpts.items())}

    payload = {
        "season": season,
        "week": week,
        "teams": teams,
        "lg": {"ppg": round(lg_ppg, 2)},
        "label": ROUND_LABELS.get(week, f"Week {week}"),
        "players": players,
        "dvp": dvp,
        "games": slate,
        "logcols": LOGCOLS,
    }

    if dest.exists():
        old = json.loads(dest.read_text())
        old.pop("built", None)
        for g in old.get("games", []):
            g.pop("proj", None)   # game projections are added afterward by build_games.py
        if old == json.loads(json.dumps(payload)):
            print("no change")
            return

    payload = {"built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), **payload}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"{payload['label']} {season}: {len(players)} players, {len(slate)} games, {dest.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
