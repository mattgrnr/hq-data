#!/usr/bin/env python3
"""One-off: ask PropLine for parlay bet links at FanDuel, DraftKings and Fanatics, and compare their ids with ours."""
import json
import os
import urllib.parse
import urllib.request

API = "https://api.prop-line.com/v1"


def get(path, **params):
    params["apiKey"] = os.environ["PROPLINE_KEY"]
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hq-data"}), timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  {path}: HTTP {e.code} {e.read()[:300]!r}")
    except Exception as e:
        print(f"  {path}: {type(e).__name__}")
    return None


d = get("sports/basketball_nba/odds", markets="h2h,player_points", includeBookIds="true",
        bookmakers="fanduel,draftkings,fanatics")
evs = [e for e in (d if isinstance(d, list) else (d or {}).get("events") or []) if isinstance(e, dict) and not e.get("live")]
for bk in ("fanduel", "draftkings", "fanatics"):
    picks = []
    for ev in evs:
        for b in ev.get("bookmakers") or []:
            if b["key"] != bk:
                continue
            for m in b.get("markets") or []:
                if m["key"] == "h2h" and m.get("outcomes"):
                    o = m["outcomes"][0]
                    picks.append((ev.get("home_team"), o["name"], o.get("outcome_id"), o.get("book_outcome_id")))
                    break
        if len(picks) >= 2:
            break
    print("==", bk, picks)
    if len(picks) < 2:
        continue
    r = get("bet-links/parlay", outcome_ids=",".join(str(p[2]) for p in picks))
    if r:
        print("  bet_link:", r.get("bet_link"))
        print("  note:", r.get("note"))
        for leg in r.get("legs") or []:
            print("  leg:", {k: leg.get(k) for k in ("name", "book_event_id", "book_market_id", "book_outcome_id")})
