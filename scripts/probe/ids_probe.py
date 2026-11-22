#!/usr/bin/env python3
"""One-off: what book ids and links come back for each book, to build add-to-betslip links."""
import json
import os
import urllib.parse
import urllib.request

API = "https://api.prop-line.com/v1"
BOOKS = ("fanduel", "draftkings", "betmgm", "betrivers", "hardrock", "fanatics", "williamhill_us", "caesars", "espnbet")


def get(path, **params):
    params["apiKey"] = os.environ["PROPLINE_KEY"]
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hq-data"}), timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  {path}: {type(e).__name__} {getattr(e, 'code', '')}")
        return None


for sport, markets in (("basketball_nba", "h2h,player_points"), ("hockey_nhl", "player_goals")):
    print("==", sport)
    d = get(f"sports/{sport}/odds", markets=markets, includeLinks="true", includeBookIds="true", bookmakers=",".join(BOOKS))
    evs = d if isinstance(d, list) else (d or {}).get("events") or (d or {}).get("data") or []
    seen = set()
    for ev in evs:
        if not isinstance(ev, dict) or ev.get("live"):
            continue
        for b in ev.get("bookmakers") or []:
            for m in b.get("markets") or []:
                key = (b["key"], m["key"])
                if key in seen or not m.get("outcomes"):
                    continue
                seen.add(key)
                o = m["outcomes"][0]
                print(f"  {b['key']:14} {m['key']:15} event_id={b.get('book_event_id')} link={str(b.get('link'))[:70]}")
                print(f"      outcome: name={o.get('name')!r} desc={o.get('description')!r} book_outcome_id={o.get('book_outcome_id')!r} "
                      f"outcome_id={o.get('outcome_id')!r} market_book_id={m.get('book_market_id')!r} link={str(o.get('link'))[:90]}")
                print(f"      market keys: {sorted(k for k in m if k != 'outcomes')}  outcome keys: {sorted(o)}")
