#!/usr/bin/env python3
"""Pull sportsbook odds from PropLine for one of our sports and save them next to its board.

Writes <sport>/odds.json: every event with its game lines (moneyline, spread, total) and the
player props we score, per book. The API key comes from the PROPLINE_KEY environment variable
(a GitHub secret) and is never written anywhere.
usage: odds.py <nhl|nba|nfl|soccer>
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.prop-line.com/v1"

GAME = ["h2h", "spreads", "totals"]
# US books people actually bet at, plus Pinnacle as the sharp reference
BOOKS = {"draftkings": "DK", "fanduel": "FD", "betmgm": "MGM", "williamhill_us": "CZR", "caesars": "CZR", "fanatics": "FAN",
         "espnbet": "ESPN", "betrivers": "BR", "hardrock": "HR", "bovada": "BOV", "pinnacle": "PIN"}
SPORTS = {
    "nhl": (["hockey_nhl"], GAME + ["player_goals", "player_points_1plus", "player_shots_on_goal"]),
    "nba": (["basketball_nba"], GAME + ["player_points", "player_rebounds", "player_assists", "player_points_rebounds_assists",
                                       "player_threes", "player_blocks", "player_steals"]),
    "nfl": (["football_nfl"], GAME + ["player_anytime_td", "player_pass_yds", "player_pass_tds", "player_rush_yds",
                                     "player_reception_yds", "player_receptions"]),
    "soccer": (["soccer_epl", "soccer_la_liga", "soccer_serie_a", "soccer_bundesliga", "soccer_ligue_1"],
               ["h2h", "totals", "both_teams_to_score", "anytime_goal_scorer", "player_assists", "goal_or_assist"]),
}


def get(path, **params):
    params["apiKey"] = os.environ["PROPLINE_KEY"]
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hq-data"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            # never echo the url: it carries the key
            print(f"{path}: try {i + 1} failed ({type(e).__name__}: {getattr(e, 'code', '')})", flush=True)
            time.sleep(3 * (i + 1))
    return None


def slim(ev, key):
    """One event, kept to the books above: market -> [[name, player, point, {book: price}]]."""
    rows = {}
    for b in ev.get("bookmakers") or []:
        bk = BOOKS.get(b.get("key"))
        if not bk:
            continue
        for m in b.get("markets") or []:
            if m.get("period") not in (None, "", "full_game", "ft") or m.get("team"):
                continue
            for o in m.get("outcomes") or []:
                if o.get("price") is None:
                    continue
                k = (m["key"], o.get("name"), o.get("description") or "", o.get("point"))
                rows.setdefault(k, {})[bk] = o["price"]
    mk = {}
    for (m, name, desc, point), prices in rows.items():
        mk.setdefault(m, []).append([name, desc, point, prices])
    def abbr(url):
        m = re.search(r"/([a-z]+)\.png", url or "")
        return m.group(1).upper() if m else None
    return {"id": ev.get("id"), "sk": key, "h": ev.get("home_team"), "a": ev.get("away_team"),
            "hk": abbr(ev.get("home_team_logo_url")), "ak": abbr(ev.get("away_team_logo_url")),
            "t": ev.get("commence_time"), "m": mk}


def main():
    sport = sys.argv[1]
    if not os.environ.get("PROPLINE_KEY"):
        print("PROPLINE_KEY is not set; skipped")
        return
    keys, markets = SPORTS[sport]
    events = []
    for key in keys:
        data = get(f"sports/{key}/odds", markets=",".join(markets))
        if data is None:
            continue
        evs = data if isinstance(data, list) else data.get("events") or data.get("data") or [data]
        for ev in evs:
            if isinstance(ev, dict) and not ev.get("live"):
                events.append(slim(ev, key))
    out = {"fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events": events}
    (ROOT / sport / "odds.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"{sport}: {len(events)} events with odds")


if __name__ == "__main__":
    main()
