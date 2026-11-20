#!/usr/bin/env python3
"""Grade saved picks against what actually happened, and roll the results into summary.json.

usage: grade.py nhl            grade any finished days that are not graded yet
       grade.py nhl --backfill also rebuild picks for past days from the board's git history first
"""
import io
import json
import math
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent.parent
REL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
ET = ZoneInfo("America/New_York")
TIERS = [("ELITE", 80), ("STRONG", 68), ("SOLID", 56), ("FRINGE", 44), ("LONGSHOT", 0)]
SPORT = {"nhl": {"site": "slapshot", "stats": ["G", "A", "P", "S"]}}


def tier(s):
    for name, cut in TIERS:
        if s >= cut:
            return name
    return "LONGSHOT"


def poisson_at_least(mean, k):
    if mean is None or mean <= 0:
        return 0.0
    return 1 - sum(math.exp(-mean) * mean ** i / math.factorial(i) for i in range(k))


# ---------- what counts as a hit ----------

def nhl_hit(stat, act):
    return {"G": act["g"] >= 1, "A": act["a"] >= 1, "P": act["g"] + act["a"] >= 1, "S": act["sog"] >= 3}[stat]


def nhl_expect(stat, pj):
    """Chance the model gave for a hit, from its projection."""
    if pj is None:
        return None
    return poisson_at_least(pj, 3) if stat == "S" else 1 - math.exp(-pj)


def nhl_season(d):
    return d.year + 1 if d.month >= 8 else d.year


def nhl_actuals(game_ids, season, cache={}):
    """Player lines for the given games, from the sportsdataverse box scores."""
    if season not in cache:
        url = f"{REL}/nhl_player_boxscores/player_box_{season}.parquet"
        req = urllib.request.Request(url, headers={"User-Agent": "hq-data"})
        with urllib.request.urlopen(req, timeout=300) as r:
            rows = pq.read_table(io.BytesIO(r.read()),
                                 columns=["game_id", "game_date", "player_id", "goals", "assists", "shots_on_goal"]).to_pylist()
        cache[season] = rows
    out = defaultdict(dict)
    for r in cache[season]:
        if int(r["game_id"]) in game_ids:
            out[int(r["game_id"])][int(r["player_id"])] = {"g": int(r["goals"] or 0), "a": int(r["assists"] or 0),
                                                           "sog": int(r["shots_on_goal"] or 0)}
    return out


# ---------- picks from git history ----------

def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def backfill_picks(sport):
    """For each past day, score the last board committed before the first game started."""
    cfg = SPORT[sport]
    pdir = ROOT / sport / "history" / "picks"
    pdir.mkdir(parents=True, exist_ok=True)
    best = {}
    for line in git("log", "--format=%H %cI", "--", f"{sport}/board.json").split("\n"):
        if not line.strip():
            continue
        sha, when = line.split()
        try:
            bd = json.loads(git("show", f"{sha}:{sport}/board.json"))
        except Exception:
            continue
        if not bd.get("games"):
            continue
        first = min(datetime.fromisoformat(g["start"].replace("Z", "+00:00")) for g in bd["games"] if g.get("start"))
        committed = datetime.fromisoformat(when)
        if committed > first:
            continue  # built after puck drop: not a fair pick
        d = bd["date"]
        if d not in best or committed > best[d][1]:
            best[d] = (sha, committed)
    tmp = ROOT / ".board.tmp.json"
    for d, (sha, _) in sorted(best.items()):
        out = pdir / f"{d}.json"
        if out.exists():
            continue
        tmp.write_text(git("show", f"{sha}:{sport}/board.json"))
        subprocess.run(["node", "scripts/history/score.cjs", cfg["site"], str(tmp), str(out)], cwd=ROOT, check=True)
    tmp.unlink(missing_ok=True)


# ---------- grading ----------

def grade(sport):
    cfg = SPORT[sport]
    hdir = ROOT / sport / "history"
    gdir = hdir / "graded"
    gdir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ET).date()
    for pf in sorted((hdir / "picks").glob("*.json")):
        d = pf.stem
        if (gdir / pf.name).exists() or date.fromisoformat(d) >= today:
            continue
        picks = json.loads(pf.read_text())
        game_ids = {g["id"] for g in picks["games"]}
        acts = nhl_actuals(game_ids, nhl_season(date.fromisoformat(d)))
        if not game_ids <= set(acts):
            print(f"{d}: box scores not in yet ({len(game_ids & set(acts))}/{len(game_ids)} games)")
            continue
        rows = []
        for p in picks["picks"]:
            act = acts.get(p["g"], {}).get(p["id"])
            if act is None:
                continue  # did not play
            rows.append({**p, "act": act})
        (gdir / pf.name).write_text(json.dumps({"date": d, "games": len(game_ids), "rows": rows}, separators=(",", ":")))
        print(f"{d}: graded {len(rows)} players")
    summarize(sport, cfg)


def summarize(sport, cfg):
    """Hit rates by stat and tier over several windows, plus each day's top picks."""
    hdir = ROOT / sport / "history"
    days = [json.loads(f.read_text()) for f in sorted((hdir / "graded").glob("*.json"))]
    if not days:
        return
    last = date.fromisoformat(days[-1]["date"])
    windows = {"7": last - timedelta(days=6), "30": last - timedelta(days=29), "season": date.min}
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "first": days[0]["date"],
           "last": days[-1]["date"], "days": len(days), "tiers": {}, "daily": []}
    for stat in cfg["stats"]:
        out["tiers"][stat] = {}
        for w, since in windows.items():
            agg = defaultdict(lambda: [0, 0, 0.0])  # picks, hits, expected hits
            for day in days:
                if date.fromisoformat(day["date"]) < since:
                    continue
                for r in day["rows"]:
                    t = tier(r["s"][stat])
                    a = agg[t]
                    a[0] += 1
                    a[1] += nhl_hit(stat, r["act"])
                    a[2] += nhl_expect(stat, r["pj"].get(stat)) or 0
            out["tiers"][stat][w] = {t: {"n": a[0], "hit": a[1], "exp": round(a[2], 1)} for t, a in agg.items()}
    for day in days[-30:]:
        entry = {"date": day["date"], "games": day["games"], "stats": {}}
        for stat in cfg["stats"]:
            ranked = sorted(day["rows"], key=lambda r: -r["s"][stat])
            top = [{"n": r["n"], "t": r["t"], "s": r["s"][stat], "hit": nhl_hit(stat, r["act"]),
                    "act": r["act"]} for r in ranked[:10]]
            elite = [r for r in day["rows"] if r["s"][stat] >= 80]
            entry["stats"][stat] = {"top": top, "elite": [len(elite), sum(nhl_hit(stat, r["act"]) for r in elite)]}
        out["daily"].append(entry)
    out["daily"].reverse()
    (hdir / "summary.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"summary: {len(days)} days, {out['first']} to {out['last']}")


if __name__ == "__main__":
    sport = sys.argv[1]
    if "--backfill" in sys.argv:
        backfill_picks(sport)
    grade(sport)
