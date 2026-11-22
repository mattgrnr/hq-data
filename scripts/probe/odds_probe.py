#!/usr/bin/env python3
"""One-off check of PropLine: do links come back, and does asking per game return more FanDuel/DraftKings props?"""
import collections
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
    except Exception as e:
        print(f"  {path}: {type(e).__name__} {getattr(e, 'code', '')}")
        return None


def summarize(tag, evs):
    c, links = collections.Counter(), collections.Counter()
    sample = {}
    for ev in evs:
        for b in ev.get("bookmakers") or []:
            for m in b.get("markets") or []:
                if m["key"].startswith("player") or m["key"] in ("anytime_goal_scorer",):
                    c[b["key"]] += len(m.get("outcomes") or [])
                for o in m.get("outcomes") or []:
                    if o.get("link"):
                        links[b["key"]] += 1
                        sample.setdefault(b["key"], o["link"][:90])
            if b.get("link"):
                links[b["key"] + " (event)"] += 1
                sample.setdefault(b["key"] + " ev", str(b["link"])[:90])
    print(f"{tag}: prop outcomes by book {dict(c.most_common(10))}")
    print(f"{tag}: links {dict(links.most_common(12))}")
    for k, v in list(sample.items())[:8]:
        print(f"   sample {k}: {v}")


for sport, markets in (("basketball_nba", "player_points,player_rebounds"), ("hockey_nhl", "player_goals,player_shots_on_goal"),
                       ("soccer_la_liga", "anytime_goal_scorer")):
    print("==", sport)
    whole = get(f"sports/{sport}/odds", markets=markets, includeLinks="true")
    evs = whole if isinstance(whole, list) else (whole or {}).get("events") or (whole or {}).get("data") or []
    evs = [e for e in evs if isinstance(e, dict) and not e.get("live")]
    summarize("one call, includeLinks", evs)
    one = [e for e in evs if e.get("bookmakers")][:2]
    per = []
    for e in one:
        r = get(f"sports/{sport}/events/{e['id']}/odds", markets=markets, bookmakers="fanduel,draftkings", includeLinks="true")
        if isinstance(r, dict) and r.get("bookmakers") is not None:
            per.append(r)
        elif isinstance(r, list):
            per += r
    summarize("per game, FD+DK only", per)
    summarize("same games in the one call", one)
