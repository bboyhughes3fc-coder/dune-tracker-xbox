#!/usr/bin/env python3
"""Scrape dunestatus.com for the EU Xbox official worlds and record player counts.

Run every 15 minutes (GitHub Actions). Standard library only.

Writes:
  data/raw/worlds-YYYY-MM-DD.csv    one row per world per snapshot
  data/raw/sietches-YYYY-MM-DD.csv  one row per sietch per snapshot
  data/region_eu.json               Europe-wide (all platforms) 15-min history from the site
  data/state.json                   last snapshot timestamp (to skip duplicates)
Then rebuilds docs/data/summary.json for the dashboard (see build_summary.py).
"""
import csv
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
URL = "https://dunestatus.com/"
UA = "dune-eu-xbox-tracker/1.0 (+personal hourly population log; github actions)"

# Official EU Xbox worlds, from duneawakening.com/news/here-is-the-server-list-for-consoles/
EU_XBOX_WORLDS = [
    "Bled", "Noukkers",                                   # head start
    "Akarso", "Sigma Draconis", "Caid", "Enfeil", "Ghadhean",
    "Theta Shalish", "Korba", "Mektub", "Yali",           # launch
]


def fetch(url, attempts=4):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # network hiccup: back off and retry
            last = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"fetch failed after {attempts} attempts: {last}")


def decode_payload(html):
    """Join the Next.js RSC chunks (self.__next_f.push([1,"..."])) into one string."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, flags=re.S)
    if not chunks:
        raise RuntimeError("no Next.js payload found - site layout may have changed")
    return "".join(json.loads('"' + c + '"') for c in chunks)


def extract(payload, key):
    i = payload.find(f'"{key}":')
    if i < 0:
        raise RuntimeError(f'"{key}" not found in payload - site layout may have changed')
    val, _ = json.JSONDecoder().raw_decode(payload[i + len(key) + 3:])
    return val


def main():
    os.makedirs(RAW, exist_ok=True)
    html = fetch(URL)
    payload = decode_payload(html)
    battlegroups = extract(payload, "battlegroups")
    stats = extract(payload, "stats")

    wanted = set(EU_XBOX_WORLDS)
    found = {}
    for bg in battlegroups:
        if (bg.get("DisplayName") in wanted and bg.get("DatacenterId") == "Europe"
                and not bg.get("IsPrivate") and bg.get("Provider") == "funcom"):
            found[bg["DisplayName"]] = bg
    missing = wanted - set(found)
    if missing:
        print(f"WARNING: worlds not found this run: {sorted(missing)}", file=sys.stderr)
    if not found:
        raise RuntimeError("none of the EU Xbox worlds were found")

    source_ts = max(int(bg.get("LastSeen") or 0) for bg in found.values())
    state_path = os.path.join(DATA, "state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)

    # Europe-wide 15-minute history (all platforms) - merge so it keeps growing
    region_path = os.path.join(DATA, "region_eu.json")
    region = {}
    if os.path.exists(region_path):
        with open(region_path) as f:
            region = {int(k): v for k, v in json.load(f).items()}
    for row in (stats.get("m15_30d") or []):
        if "Europe" in row:
            region[int(row["timestamp"]) // 1000] = row["Europe"]
    with open(region_path, "w") as f:
        json.dump({str(k): region[k] for k in sorted(region)}, f, separators=(",", ":"))

    if state.get("last_source_ts") == source_ts:
        print(f"snapshot {source_ts} already recorded; nothing new")
        return False

    now = datetime.now(timezone.utc)
    snap = datetime.fromtimestamp(source_ts, timezone.utc)
    day = snap.strftime("%Y-%m-%d")
    snap_iso = snap.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    wpath = os.path.join(RAW, f"worlds-{day}.csv")
    spath = os.path.join(RAW, f"sietches-{day}.csv")
    wnew, snew = not os.path.exists(wpath), not os.path.exists(spath)
    with open(wpath, "a", newline="") as wf, open(spath, "a", newline="") as sf:
        ww, sw = csv.writer(wf), csv.writer(sf)
        if wnew:
            ww.writerow(["snapshot_utc", "fetched_utc", "world", "players", "capacity", "status", "activity"])
        if snew:
            sw.writerow(["snapshot_utc", "world", "sietch", "players", "capacity", "status"])
        for name in EU_XBOX_WORLDS:
            bg = found.get(name)
            if not bg:
                continue
            ww.writerow([snap_iso, fetched_iso, name, bg.get("BattlegroupCurrentActive", 0),
                         bg.get("BattlegroupMaxPlayerCapacity", 0), bg.get("BattlegroupStatus"),
                         bg.get("Activity", "")])
            for s in bg.get("ActiveInitialServers") or []:
                sw.writerow([snap_iso, name, s.get("DisplayName", ""), s.get("CurrentConcurrentPlayerCount", 0),
                             s.get("MaxConcurrentPlayerCapacity", 0), s.get("ServerStatus")])

    state["last_source_ts"] = source_ts
    state["last_snapshot_utc"] = snap_iso
    with open(state_path, "w") as f:
        json.dump(state, f, indent=1)
    total = sum(found[n].get("BattlegroupCurrentActive", 0) for n in found)
    print(f"recorded snapshot {snap_iso}: {len(found)} worlds, {total} players")
    return True


if __name__ == "__main__":
    main()
    from build_summary import build  # noqa: E402  (same folder)
    build()
