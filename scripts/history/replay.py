#!/usr/bin/env python3
"""Rebuild past slates from what was known the morning before, then fold their picks into history.

usage: replay.py nfl 2-6
       replay.py <nhl|nba|soccer|mlb> 2026-10-07..2026-10-21
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SITE = {"nfl": "touchdown", "nhl": "slapshot", "nba": "slam", "soccer": "futbol", "mlb": "moonshot"}


def run(cmd, env=None):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, env={**os.environ, **(env or {})})


def score(sport, board, before):
    """Score a rebuilt board as of an hour before its first game."""
    run(["node", "scripts/history/score.cjs", SITE[sport], str(board), f"{sport}/history/picks", "--now", before])


def nfl(rng):
    a, b = (int(x) for x in rng.split("-"))
    for week in range(a, b + 1):
        run(["python", "scripts/build_nfl.py"], {"REPLAY_WEEK": str(week)})
        board = ROOT / "nfl" / "replay" / f"w{week:02d}.json"
        bd = json.loads(board.read_text())
        first = min(g["ko"] for g in bd["games"] if g.get("ko"))
        score("nfl", board, datetime.utcfromtimestamp(first - 3600).isoformat() + "Z")


def daily(sport, rng):
    """One rebuilt board per date; days that already have live picks are left alone."""
    a, b = (datetime.fromisoformat(x).date() for x in rng.split(".."))
    d = a
    while d <= b:
        day = d.isoformat()
        d += timedelta(days=1)
        have = ROOT / sport / "history" / "picks" / f"{day}.json"
        if have.exists() and not json.loads(have.read_text()).get("replay"):
            print(f"{day}: live picks on file, skipped")
            continue
        try:
            env = {"REPLAY_DATE": day} if sport == "soccer" else {"REPLAY": "1", "TODAY": day, "HQ_NO_ESPN": "1"}
            run(["python", f"scripts/build_{sport}.py"], env)
        except subprocess.CalledProcessError:
            print(f"{day}: couldn't build (no games played yet this season?), skipped")
            continue
        board = ROOT / sport / "replay" / f"{day}.json"
        if not board.exists():
            continue
        bd = json.loads(board.read_text())
        starts = [datetime.fromisoformat(str(g.get("start") or g.get("t")).replace("Z", "+00:00")) for g in bd.get("games", []) if g.get("start") or g.get("t")]
        if not starts or not bd.get("players"):
            print(f"{day}: no games")
            continue
        score(sport, board, (min(starts) - timedelta(hours=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def main():
    sport, rng = sys.argv[1], sys.argv[2]
    if sport == "nfl":
        nfl(rng)
    elif sport in ("nhl", "nba", "soccer"):
        daily(sport, rng)
    else:
        raise SystemExit(f"replay for {sport} is not built yet")


if __name__ == "__main__":
    main()
