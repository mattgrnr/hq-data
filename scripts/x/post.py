#!/usr/bin/env python3
"""Builds today's post for one sport: reads the live board, draws the card, writes the text, and posts it.
usage: post.py <nba|nhl|nfl>     DRY_RUN=1 skips the post itself."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ET = ZoneInfo("America/New_York")
COUNT = {"nba": 5, "nhl": 5, "nfl": 10}
FOLDER = {"nba": "nba", "nhl": "nhl", "nfl": "nfl"}
NICK = {"Shai Gilgeous-Alexander": "SGA"}
SUFFIX = re.compile(r"\s+(Jr\.?|Sr\.?|II|III|IV)$")


def short(name, taken):
    if name in NICK:
        return NICK[name]
    base = SUFFIX.sub("", name)
    last = base.split(" ", 1)[-1] if " " in base else base
    return base if taken.count(last) > 1 else last


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def board(sport):
    out = subprocess.run(["node", str(HERE / "top.cjs"), sport, str(COUNT[sport])],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def prepare(b, today):
    rows = []
    for r in b["rows"]:
        p = num(r["proj"])
        if b["sport"] == "nba":
            proj = f"{p:.1f}" if p is not None else ""
        elif b["sport"] == "nhl":
            proj = f"{p:.1f}" if p is not None else ""
        else:
            proj = f"{p:.0f}" if p is not None else ""
        where = ("vs " if r["home"] else "at ") + r["opp"] if r["opp"] else ""
        rows.append({**r, "proj": proj, "sub": f'{r["team"]} {where}'.strip(), "tier": r["tier"].upper()})
    day = today.strftime("%a %b ").upper() + str(today.day)
    week = b["label"].split("·")[0].strip().upper()
    line = {"nba": f"{day}  ·  POINTS BOARD", "nhl": f"{day}  ·  GOAL BOARD",
            "nfl": f"{week}  ·  TD BOARD  ·  AS OF {today.strftime('%a').upper()}"}[b["sport"]]
    return {**b, "rows": rows, "line": line}


def text(data, link, today):
    lasts = [SUFFIX.sub("", r["name"]).split(" ", 1)[-1] for r in data["rows"]]
    lines = []
    for r in data["rows"][:5]:
        who = short(r["name"], lasts)
        tier = r["tier"].title()
        if data["sport"] == "nba":
            lines.append(f'{who} · {tier} · {r["proj"]} pts')
        elif data["sport"] == "nhl":
            lines.append(f'{who} · {tier} · {r["sub"].split(" ", 1)[-1]}')
        else:
            lines.append(f'{who} · {tier} · {r["proj"]} yds')
    md = f"{today.month}/{today.day}"
    week = data["label"].split("·")[0].strip().title()
    head = {"nba": f"NBA points board, {today.strftime('%a')} {md} 🏀",
            "nhl": f"NHL goal board, {today.strftime('%a')} {md} 🏒",
            "nfl": f"{week} TD board 🏈"}[data["sport"]]
    tail = {"nba": "rest of the slate", "nhl": "every skater",
            "nfl": "6–10 on the board, updated through Sunday"}[data["sport"]]
    return f"{head}\n\n" + "\n".join(lines) + f"\n\n{tail} 👇\n{link}"


def sane(data):
    rows = data["rows"]
    if data.get("games", 0) < 1 or len(rows) < 5:
        return "no slate"
    if any(not r["name"] or not r["tier"] or not r["score"] for r in rows):
        return "board looks incomplete"
    return ""


def push_card(sport, path, body):
    dest = ROOT / FOLDER[sport] / "card.png"
    dest.write_bytes(Path(path).read_bytes())
    (ROOT / FOLDER[sport] / "post.txt").write_text(body + "\n")
    subprocess.run(["git", "add", str(dest), str(dest.with_name("post.txt"))], cwd=ROOT, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    subprocess.run(["git", "commit", "-m", f"{sport.upper()} share card"], cwd=ROOT, check=True)
    subprocess.run(["git", "pull", "--rebase", "-X", "theirs"], cwd=ROOT, check=True)
    subprocess.run(["git", "push"], cwd=ROOT, check=True)


def wait_for_card(link, path, tries=20):
    """The post's preview has to show today's card, so wait until the site serves it."""
    want = Path(path).read_bytes()
    img = link.split("?")[0].rstrip("/") + "/og.png?" + link.split("?")[1]
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(img, headers={"User-Agent": "hq-data"}), timeout=20) as r:
                if r.read() == want:
                    return True
        except Exception:
            pass
        time.sleep(15)
    return False


def post(body):
    from requests_oauthlib import OAuth1Session
    keys = [os.environ.get(k, "") for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
    if not all(keys):
        sys.exit("::error::Missing X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET repository secrets")
    s = OAuth1Session(*keys)
    r = s.post("https://api.x.com/2/tweets", json={"text": body}, timeout=30)
    if r.status_code >= 300:
        sys.exit(f"::error::X said {r.status_code}: {r.text[:300]}")
    return r.json()["data"]["id"]


def main():
    sport = sys.argv[1]
    today = dt.datetime.now(ET).date()
    data = prepare(board(sport), today)
    why = sane(data)
    if why:
        print(f"skipping {sport}: {why}")
        return
    card = f"/tmp/{sport}-card.png"
    subprocess.run([sys.executable, str(HERE / "card.py"), "/dev/stdin", card],
                   input=json.dumps(data), text=True, check=True)
    link = f'{data["url"].rstrip("/")}/?d={today.strftime("%m%d")}'
    body = text(data, link, today)
    print(body)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"### {sport.upper()}\n\n```\n{body}\n```\n\n")
    push_card(sport, card, body)
    if not wait_for_card(link, card):
        sys.exit("::error::The site never served today's card, so the preview would be stale. Not posting.")
    if os.environ.get("DRY_RUN") == "1":
        print("dry run: card is live on the site, nothing posted")
        return
    print("posted:", post(body))


if __name__ == "__main__":
    main()
