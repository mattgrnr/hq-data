#!/usr/bin/env python3
"""Grade saved picks against what actually happened and roll the results into summary.json.

A pick is Over when the player's actual number for that tab's stat reached our projection, Under otherwise.

usage: grade.py <nhl|nba|nfl|soccer|mlb>              grade finished slates that are not graded yet
       grade.py <sport> --backfill               first rebuild picks from the board's git history
"""
import csv
import gzip
import io
import json
import math
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SDV = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
NFLV = "https://github.com/nflverse/nflverse-data/releases/download"
TIERS = [("ELITE", 80), ("STRONG", 68), ("SOLID", 56), ("FRINGE", 44), ("LONGSHOT", 0)]
GIVE_UP_DAYS = 4   # a game with no box score after this long (postponed) is dropped


def tier(s):
    for name, cut in TIERS:
        if s >= cut:
            return name
    return "LONGSHOT"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "hq-data"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def parquet(url, columns):
    import pyarrow.parquet as pq
    try:
        return pq.read_table(io.BytesIO(get(url)), columns=columns).to_pylist()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


def n(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def season_of(day):
    return day.year + 1 if day.month >= 8 else day.year


# ---------- actual numbers, per sport: {game key: {player id: {stat: value}}} ----------

def nhl_actuals(slate, cache={}):
    season = season_of(date.fromisoformat(slate["key"]))
    if season not in cache:
        cache[season] = parquet(f"{SDV}/nhl_player_boxscores/player_box_{season}.parquet",
                                ["game_id", "player_id", "goals", "assists", "shots_on_goal"])
    keys, out = set(slate["games"]), defaultdict(dict)
    for r in cache[season]:
        k = str(r["game_id"])
        if k in keys:
            g, a = n(r["goals"]), n(r["assists"])
            out[k][int(r["player_id"])] = {"G": g, "A": a, "P": g + a, "S": n(r["shots_on_goal"])}
    return out


def nba_actuals(slate, cache={}):
    season = season_of(date.fromisoformat(slate["key"]))
    if season not in cache:
        cache[season] = parquet(f"{SDV}/espn_nba_player_boxscores/player_box_{season}.parquet",
                                ["game_id", "athlete_id", "did_not_play", "minutes", "points", "rebounds", "assists",
                                 "three_point_field_goals_made", "steals", "blocks"])
    keys, out = set(slate["games"]), defaultdict(dict)
    for r in cache[season]:
        k = str(r["game_id"])
        if k not in keys:
            continue
        out[k]  # a game whose rows are all did-not-plays still counts as played
        if r["did_not_play"] or n(r["minutes"]) <= 0:
            continue
        pts, reb, ast = n(r["points"]), n(r["rebounds"]), n(r["assists"])
        out[k][int(r["athlete_id"])] = {"PTS": pts, "REB": reb, "AST": ast, "PRA": pts + reb + ast,
                                        "PR": pts + reb, "PA": pts + ast, "RA": reb + ast,
                                        "3PM": n(r["three_point_field_goals_made"]), "STL": n(r["steals"]), "BLK": n(r["blocks"])}
    return out


def nfl_actuals(slate, cache={}):
    season, week = slate["key"].split("-w")
    if season not in cache:
        text = get(f"{NFLV}/stats_player/stats_player_week_{season}.csv").decode("utf-8")
        cache[season] = list(csv.DictReader(io.StringIO(text)))
    by_team = defaultdict(dict)
    for r in cache[season]:
        if int(r["week"]) == int(week):
            by_team[r["team"]][r["player_id"]] = {
                "TD": n(r["rushing_tds"]) + n(r["receiving_tds"]), "CYD": n(r["receiving_yards"]),
                "RYD": n(r["rushing_yards"]), "REC": n(r["receptions"]), "PYD": n(r["passing_yards"]),
                "PTD": n(r["passing_tds"])}
    out = {}
    for k in slate["games"]:
        away, home = k.split("@")
        if by_team.get(away) and by_team.get(home):
            out[k] = {**by_team[away], **by_team[home]}
    return out


def soccer_actuals(slate, cache={}):
    if "rows" not in cache:
        idx = defaultdict(dict)
        for f in (ROOT / "soccer" / "hist").glob("*.csv.gz"):
            with gzip.open(f, "rt", newline="") as fh:
                for r in csv.DictReader(fh):
                    idx[r["mid"]][int(r["pid"])] = {"G": n(r["g"]), "A": n(r["a"]), "T": n(r["sot"]), "S": n(r["sh"]),
                                                     "GA": n(r["g"]) + n(r["a"])}
        cache["rows"] = idx
    return {k: cache["rows"][k] for k in slate["games"] if k in cache["rows"]}


def mlb_actuals(slate, cache={}):
    if "hr" not in cache:
        idx = defaultdict(lambda: defaultdict(lambda: {"HR": 0.0}))
        with gzip.open(ROOT / "mlb" / "raw" / "pa.csv.gz", "rt", newline="") as fh:
            for r in csv.DictReader(fh):
                idx[r["pk"]][int(r["b"])]["HR"] += r["hit"] == "4"
        cache["hr"] = idx
    return {k: cache["hr"][k] for k in slate["games"] if k in cache["hr"]}


SPORT = {
    "nhl": {"site": "slapshot", "actuals": nhl_actuals},
    "nba": {"site": "slam", "actuals": nba_actuals},
    "nfl": {"site": "touchdown", "actuals": nfl_actuals},
    "soccer": {"site": "futbol", "actuals": soccer_actuals},
    "mlb": {"site": "moonshot", "actuals": mlb_actuals},
}


# ---------- Over / Under ----------

def is_over(actual, proj):
    return actual >= proj - 1e-9


def chance_over(proj):
    """What the model implied: the chance a count with this average reaches it (Poisson)."""
    if not proj or proj <= 0:
        return None
    need = math.ceil(proj - 1e-9)
    if need > 400:
        return 0.5
    term, below = math.exp(-proj), 0.0
    for k in range(need):
        below += term
        term *= proj / (k + 1)
    return max(0.0, 1 - below)


# ---------- picks from git history ----------

def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def backfill_picks(sport):
    """Replay every committed board in order; each game keeps the last snapshot from before it started."""
    cfg = SPORT[sport]
    hdir = ROOT / sport / "history" / "picks"
    tmp = ROOT / ".board.tmp.json"
    commits = [l.split() for l in git("log", "--reverse", "--format=%H %cI", "--", f"{sport}/board.json").split("\n") if l.strip()]
    for sha, when in commits:
        try:
            tmp.write_text(git("show", f"{sha}:{sport}/board.json"))
        except subprocess.CalledProcessError:
            continue
        r = subprocess.run(["node", "scripts/history/score.cjs", cfg["site"], str(tmp), str(hdir), "--now", when],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            err = r.stderr.strip().splitlines()
            print(f"  {sha[:7]}: skipped ({err[0][:120] if err else 'error'})")
    tmp.unlink(missing_ok=True)


# ---------- grading ----------

def grade(sport):
    cfg = SPORT[sport]
    hdir = ROOT / sport / "history"
    gdir = hdir / "graded"
    gdir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    for pf in sorted((hdir / "picks").glob("*.json")):
        if (gdir / pf.name).exists():
            continue
        slate = json.loads(pf.read_text())
        starts = [datetime.fromisoformat(g["start"].replace("Z", "+00:00")) for g in slate["games"].values()]
        if not starts or now < max(starts) + timedelta(hours=6):
            continue
        acts = cfg["actuals"](slate)
        missing = [k for k in slate["games"] if k not in acts]
        if missing and now < max(starts) + timedelta(days=GIVE_UP_DAYS):
            print(f"{pf.stem}: waiting on {len(missing)} of {len(slate['games'])} games")
            continue
        rows = []
        for k, plist in slate["picks"].items():
            for p in plist:
                act = acts.get(k, {}).get(p["id"])
                if act is None:
                    continue  # did not play
                rows.append({**p, "act": {s: act[s] for s in p["pj"] if s in act}})
        games = len(slate["games"]) - len(missing)
        (gdir / pf.name).write_text(json.dumps({"key": pf.stem, "games": games, "stats": slate["stats"], "rows": rows,
                                                "replay": bool(slate.get("replay"))},
                                               separators=(",", ":"), ensure_ascii=False))
        print(f"{pf.stem}: graded {len(rows)} players in {games} games")
    summarize(sport)


# yes/no bets: (label, stat, at least k). Our chance is the Poisson chance of k or more from the saved projection.
CALIB = {
    "nhl": [("1+ point", "P", 1), ("2+ points", "P", 2), ("Goal", "G", 1), ("Assist", "A", 1)],
    "nfl": [("Anytime TD", "TD", 1)],
    "soccer": [("Goal", "G", 1), ("Assist", "A", 1), ("Goal or assist", "GA", 1)],
}


def calibration(sport, days):
    """Every priced player grouped by the chance we gave him, against how often it happened: [[lo, n, our avg, happened]]."""
    out = {}
    for label, stat, k in CALIB.get(sport, []):
        b = {}
        for d in days:
            for r in d["rows"]:
                lam, act = r["pj"].get(stat), r["act"].get(stat)
                if lam is None or act is None:
                    continue
                c = 1 - math.exp(-lam) * sum(lam ** i / math.factorial(i) for i in range(k))
                x = b.setdefault(min(int(c * 10), 9), [0, 0.0, 0])
                x[0] += 1
                x[1] += c
                x[2] += act >= k
        out[label] = [[i * 10, n, round(100 * c / n, 1), round(100 * h / n, 1)] for i, (n, c, h) in sorted(b.items()) if n >= 20]
    return out


CAL_K = 150   # a range's record counts in full only once it has well over this many players; until then it leans on our own number


def calmap(sport, cal):
    """Our chance -> the chance our record says it really is, as points to draw a line through: {"P1": [[ours, real], ...]}.
    Small ranges are pulled toward our own number, and the line never goes down as our chance goes up."""
    out = {}
    for label, stat, k in CALIB.get(sport, []):
        pts, top = [], 0.0
        for lo, n, ours, hap in cal.get(label, []):
            real = (n * hap + CAL_K * ours) / (n + CAL_K)
            top = max(top, real)
            pts.append([round(ours / 100, 4), round(top / 100, 4)])
        if len(pts) >= 3:
            out[f"{stat}{k}"] = pts
    return out


def label_of(key):
    return "Week " + str(int(key.split("-w")[1])) if "-w" in key else key


BIG_FIVE = {"Premier League", "LaLiga", "Serie A", "Bundesliga", "Ligue 1"}


def home_teams(days):
    """The team each player suits up for most, so a national-team week doesn't relabel him."""
    seen = defaultdict(Counter)
    for day in days:
        for r in day["rows"]:
            seen[r["id"]][r["t"]] += 1
    return {pid: c.most_common(1)[0][0] for pid, c in seen.items()}


def summarize(sport):
    """Over rates by stat and tier over several windows, per-slate splits, and the most-backed players."""
    hdir = ROOT / sport / "history"
    days = [json.loads(f.read_text()) for f in sorted((hdir / "graded").glob("*.json"))]
    if sport == "soccer":
        # Futbol covers the big five leagues only; older picks from other competitions stay on file but out of the results
        for d in days:
            pf = hdir / "picks" / f"{d['key']}.json"
            games = json.loads(pf.read_text())["games"] if pf.exists() else {}
            keep = {k for k, g in games.items() if g.get("league") in BIG_FIVE}
            d["rows"] = [r for r in d["rows"] if r["g"] in keep]
            d["games"] = len({r["g"] for r in d["rows"]})
    days = [d for d in days if d["rows"]]
    if not days:
        return
    stats = days[-1]["stats"]
    weekly = "-w" in days[-1]["key"]
    if weekly:
        keep = {"7": days[-1:], "30": days[-4:], "season": days}
    else:
        last = date.fromisoformat(days[-1]["key"])
        keep = {w: [d for d in days if date.fromisoformat(d["key"]) > last - timedelta(days=int(w))] for w in ("7", "30")}
        keep["season"] = days

    clubs = home_teams(days)

    def graded(day, stat):
        out = []
        for r in day["rows"]:
            pj, a = r["pj"].get(stat), r["act"].get(stat)
            if pj and a is not None:
                out.append((r, is_over(a, pj), chance_over(pj) or 0))
        return sorted(out, key=lambda x: -x[0]["s"][stat])

    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "weekly": weekly,
           "first": days[0]["key"], "last": days[-1]["key"], "days": len(days), "stats": stats,
           "tiers": {}, "players": {}, "daily": []}
    for stat in stats:
        out["tiers"][stat], out["players"][stat] = {}, {}
        for w, ds in keep.items():
            agg = defaultdict(lambda: [0, 0, 0.0])
            seen = {}
            for day in ds:
                g = graded(day, stat)
                for r, over, e in g:
                    a = agg[tier(r["s"][stat])]
                    a[0] += 1
                    a[1] += over
                    a[2] += e
                for r, over, e in g[:10]:
                    p = seen.setdefault(r["id"], {"n": r["n"], "t": r["t"], "picks": 0, "hits": 0})
                    p["picks"] += 1
                    p["hits"] += over
                    p["t"] = clubs.get(r["id"], r["t"])
            out["tiers"][stat][w] = {t: {"n": a[0], "hit": a[1], "exp": round(a[2], 1)} for t, a in agg.items()}
            ranked = sorted(seen.values(), key=lambda p: (-p["picks"], -p["hits"]))
            out["players"][stat][w] = [p for p in ranked if p["picks"] >= 2][:8]
    for day in days:
        entry = {"date": day["key"], "label": label_of(day["key"]), "games": day["games"], "stats": {}}
        if day.get("replay"):
            entry["replay"] = True
        for stat in stats:
            g = graded(day, stat)
            tiers = {}
            for r, over, e in g:
                t = tiers.setdefault(tier(r["s"][stat]), [0, 0, 0.0])
                t[0] += 1
                t[1] += over
                t[2] = round(t[2] + e, 2)
            elite = [x for x in g if x[0]["s"][stat] >= 80]
            entry["stats"][stat] = {
                "top": [{"n": r["n"], "t": r["t"], "s": r["s"][stat], "pj": r["pj"][stat], "a": r["act"][stat], "hit": over}
                        for r, over, e in g[:10]],
                "elite": [len(elite), sum(x[1] for x in elite)],
                "t10": [len(g[:10]), sum(x[1] for x in g[:10]), round(sum(x[2] for x in g[:10]), 2)],
                "tiers": tiers,
            }
        out["daily"].append(entry)
    out["daily"].reverse()
    cal = calibration(sport, days)
    if cal:
        out["calib"] = cal
        out["calmap"] = calmap(sport, cal)
    (hdir / "summary.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))

    # every graded player, for the starred-players panel: season over count and his last five per stat
    pl = {}
    for day in days:
        for stat in stats:
            for r, over, e in graded(day, stat):
                p = pl.setdefault(str(r["id"]), {"n": r["n"], "t": r["t"], "s": {}, "l": {}})
                p["t"] = clubs.get(r["id"], r["t"])
                t = p["s"].setdefault(stat, [0, 0])
                t[0] += 1
                t[1] += over
                p["l"].setdefault(stat, []).append([day["key"], r["act"][stat], r["pj"][stat], int(over)])
    for p in pl.values():
        for stat in p["l"]:
            p["l"][stat] = p["l"][stat][-5:][::-1]
    (hdir / "players.json").write_text(json.dumps(pl, separators=(",", ":"), ensure_ascii=False))
    print(f"summary: {len(days)} slates, {out['first']} to {out['last']}")


if __name__ == "__main__":
    sport = sys.argv[1]
    if "--backfill" in sys.argv:
        backfill_picks(sport)
    grade(sport)
