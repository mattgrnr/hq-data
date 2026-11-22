#!/usr/bin/env python3
"""Pull one MLB regular season into compact files the Moonshot replay can read.

mlb/raw/games.json      every game: date, start, teams, venue, starting pitchers and lineups
mlb/raw/pa.csv.gz       every plate appearance: batter, pitcher, hands, result
mlb/raw/pitch.csv.gz    every pitcher's line per game: innings, homers, started
mlb/raw/people.json     bats / throws / name for everyone who appeared
mlb/raw/wx/<team>.json  hourly weather at each open-air park for the season

usage: mlb_season.py 2026
"""
import csv
import gzip
import io
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://statsapi.mlb.com/api/v1"
WX = "https://archive-api.open-meteo.com/v1/archive"
OUT = Path(__file__).resolve().parent.parent.parent / "mlb" / "raw"

# open-air parks (lat, lng); domes and retractable roofs are scored as neutral weather
PARKS = {
    108: (33.800, -117.883), 110: (39.284, -76.622), 111: (42.346, -71.097), 112: (41.948, -87.655),
    113: (39.097, -84.507), 114: (41.496, -81.685), 115: (39.756, -104.994), 116: (42.339, -83.049),
    118: (39.051, -94.480), 119: (34.074, -118.240), 120: (38.873, -77.007), 121: (40.757, -73.846),
    133: (38.580, -121.513), 134: (40.447, -80.006), 135: (32.707, -117.157), 136: (47.591, -122.332),
    137: (37.778, -122.389), 138: (38.622, -90.193), 139: (27.980, -82.507), 142: (44.982, -93.278),
    143: (39.906, -75.166), 144: (33.891, -84.468), 145: (41.830, -87.634), 147: (40.829, -73.926),
}
NOT_AB = {"walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt", "catcher_interf",
          "sac_fly_double_play", "sac_bunt_double_play"}
HITS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hq-data"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                print("failed", url, e, flush=True)
                return None
            time.sleep(2 * (i + 1))


def one_game(g):
    pk = g["gamePk"]
    box = get(f"{API}/game/{pk}/boxscore")
    pbp = get(f"{API}/game/{pk}/playByPlay")
    if not box or not pbp:
        return None
    info = {"pk": pk, "date": g["officialDate"], "t": g["gameDate"], "gn": g.get("gameNumber", 1),
            "dh": g.get("doubleHeader", "N"), "venue": (g.get("venue") or {}).get("id")}
    pitch, people = [], {}
    for side in ("home", "away"):
        t = box["teams"][side]
        info[side] = {"id": t["team"]["id"], "abbr": t["team"].get("abbreviation") or str(t["team"]["id"])}
        lineup = []
        for p in t["players"].values():
            pid = p["person"]["id"]
            people.setdefault(pid, {"n": p["person"].get("fullName")})
            bo = str(p.get("battingOrder") or "")
            if bo.endswith("00"):
                lineup.append((int(bo), pid))
            st = (p.get("stats") or {}).get("pitching") or {}
            if st.get("inningsPitched") is not None and (st.get("battersFaced") or st.get("outs") is not None):
                pitch.append([g["officialDate"], pk, pid, st.get("inningsPitched"), st.get("homeRuns", 0),
                              1 if st.get("gamesStarted") else 0])
        info[side]["lineup"] = [pid for _, pid in sorted(lineup)]
        info[side]["sp"] = t["pitchers"][0] if t.get("pitchers") else None
    pa = []
    for play in pbp.get("allPlays", []):
        r, m = play.get("result") or {}, play.get("matchup") or {}
        if r.get("type") != "atBat" or not (play.get("about") or {}).get("isComplete"):
            continue
        ev = r.get("eventType") or ""
        b, p = m.get("batter", {}).get("id"), m.get("pitcher", {}).get("id")
        if not b or not p:
            continue
        bs, ph = (m.get("batSide") or {}).get("code", "R"), (m.get("pitchHand") or {}).get("code", "R")
        people.setdefault(b, {})["b"] = bs if people.get(b, {}).get("b") in (None, bs) else "S"
        people.setdefault(p, {})["p"] = ph
        pa.append([g["officialDate"], pk, b, p, ph, bs, HITS.get(ev, 0), 0 if ev in NOT_AB else 1])
    return info, pa, pitch, people


def main():
    year = sys.argv[1]
    OUT.mkdir(parents=True, exist_ok=True)
    sched = get(f"{API}/schedule?sportId=1&season={year}&gameType=R&hydrate=probablePitcher")
    games = [g for d in sched["dates"] for g in d["games"]
             if (g.get("status") or {}).get("abstractGameState") == "Final" and g.get("status", {}).get("detailedState") != "Postponed"]
    seen, uniq = set(), []
    for g in games:
        if g["gamePk"] not in seen:
            seen.add(g["gamePk"])
            uniq.append(g)
    print(f"{len(uniq)} finished games", flush=True)
    infos, pas, pitches, people = [], [], [], {}
    with ThreadPoolExecutor(12) as ex:
        for i, res in enumerate(ex.map(one_game, uniq)):
            if res:
                info, pa, pitch, ppl = res
                infos.append(info)
                pas += pa
                pitches += pitch
                for k, v in ppl.items():
                    cur = people.setdefault(k, {})
                    for kk, vv in v.items():
                        if kk == "b" and cur.get("b") not in (None, vv):
                            cur["b"] = "S"
                        elif vv is not None:
                            cur.setdefault(kk, vv)
            if i % 200 == 0:
                print(f"  {i} games", flush=True)
    infos.sort(key=lambda x: (x["t"], x["pk"]))
    (OUT / "games.json").write_text(json.dumps(infos, separators=(",", ":")))
    (OUT / "people.json").write_text(json.dumps(people, separators=(",", ":")))
    for name, rows, head in (("pa", pas, ["date", "pk", "b", "p", "ph", "bs", "hit", "ab"]),
                             ("pitch", pitches, ["date", "pk", "p", "ip", "hr", "gs"])):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(sorted(rows, key=lambda r: (r[0], r[1])))
        with gzip.GzipFile(OUT / f"{name}.csv.gz", "wb", mtime=0) as fh:
            fh.write(buf.getvalue().encode())
    print(f"{len(infos)} games, {len(pas)} plate appearances, {len(pitches)} pitching lines", flush=True)

    first, last = infos[0]["date"], infos[-1]["date"]
    (OUT / "wx").mkdir(exist_ok=True)
    for team, (lat, lng) in PARKS.items():
        d = get(f"{WX}?latitude={lat}&longitude={lng}&start_date={first}&end_date={last}"
                "&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,relative_humidity_2m,cloud_cover,precipitation"
                "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=UTC")
        if d:
            (OUT / "wx" / f"{team}.json").write_text(json.dumps(d["hourly"], separators=(",", ":")))
        time.sleep(1)
    print("weather done", flush=True)


if __name__ == "__main__":
    main()
