#!/usr/bin/env python3
"""Rebuild past slates from what was known the morning before, then fold their picks into history.

usage: replay.py nfl 2-6
       replay.py <nhl|nba|soccer|mlb> 2026-10-07..2026-10-21
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
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


def main():
    sport, rng = sys.argv[1], sys.argv[2]
    if sport == "nfl":
        nfl(rng)
    else:
        raise SystemExit(f"replay for {sport} is not built yet")


if __name__ == "__main__":
    main()
