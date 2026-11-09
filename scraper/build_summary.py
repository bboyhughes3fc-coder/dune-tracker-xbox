#!/usr/bin/env python3
"""Aggregate the raw CSV snapshots into docs/data/summary.json for the dashboard.

All hour-of-day / day-of-week buckets are UK time (Europe/London).
"""
import csv
import glob
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "docs", "data", "summary.json")
TZ = ZoneInfo("Europe/London")
HOME = "Bled"
PRIME = range(19, 24)  # 19:00-23:59 UK


def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def r1(x):
    return None if x is None else round(x, 1)


class Acc:
    __slots__ = ("s", "n", "mx")

    def __init__(self):
        self.s, self.n, self.mx = 0, 0, None

    def add(self, v):
        self.s += v
        self.n += 1
        self.mx = v if self.mx is None or v > self.mx else self.mx

    @property
    def avg(self):
        return self.s / self.n if self.n else None


def build():
    from scrape import EU_XBOX_WORLDS  # noqa: E402

    worlds = EU_XBOX_WORLDS
    w_hour = {w: [Acc() for _ in range(24)] for w in worlds}
    w_dow = {w: [[Acc() for _ in range(24)] for _ in range(7)] for w in worlds}
    w_series = {w: defaultdict(Acc) for w in worlds}
    w_all = {w: Acc() for w in worlds}
    w_prime = {w: Acc() for w in worlds}
    w_peak = {w: (None, None) for w in worlds}
    w_low = {w: (None, None) for w in worlds}
    cap = {}
    snapshots = set()
    latest = {}

    for path in sorted(glob.glob(os.path.join(DATA, "raw", "worlds-*.csv"))):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                w = row["world"]
                if w not in w_hour:
                    continue
                t = parse(row["snapshot_utc"])
                p = int(row["players"])
                cap[w] = int(row["capacity"] or 0)
                snapshots.add(row["snapshot_utc"])
                lt = t.astimezone(TZ)
                w_hour[w][lt.hour].add(p)
                w_dow[w][lt.weekday()][lt.hour].add(p)
                hour_key = int(t.timestamp()) // 3600 * 3600
                w_series[w][hour_key].add(p)
                w_all[w].add(p)
                if lt.hour in PRIME:
                    w_prime[w].add(p)
                if w_peak[w][0] is None or p > w_peak[w][0]:
                    w_peak[w] = (p, row["snapshot_utc"])
                if w_low[w][0] is None or p < w_low[w][0]:
                    w_low[w] = (p, row["snapshot_utc"])
                if w not in latest or row["snapshot_utc"] >= latest[w]["t"]:
                    latest[w] = {"t": row["snapshot_utc"], "players": p, "capacity": cap[w]}

    last_snap = max(snapshots) if snapshots else None

    # sietches: hour-of-day averages + latest
    s_hour = defaultdict(lambda: defaultdict(lambda: [Acc() for _ in range(24)]))
    s_all = defaultdict(lambda: defaultdict(Acc))
    s_latest = defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(DATA, "raw", "sietches-*.csv"))):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                w, s = row["world"], row["sietch"]
                p = int(row["players"])
                lt = parse(row["snapshot_utc"]).astimezone(TZ)
                s_hour[w][s][lt.hour].add(p)
                s_all[w][s].add(p)
                if row["snapshot_utc"] == last_snap:
                    s_latest[w][s] = p

    # Europe-wide (all platforms) pattern from the site's own 30-day history
    region_hour = [Acc() for _ in range(24)]
    region_dow = [[Acc() for _ in range(24)] for _ in range(7)]
    region_path = os.path.join(DATA, "region_eu.json")
    region_span = None
    if os.path.exists(region_path):
        with open(region_path) as f:
            region = {int(k): v for k, v in json.load(f).items()}
        if region:
            cutoff = max(region) - 30 * 86400
            pts = [(k, v) for k, v in region.items() if k >= cutoff]
            for k, v in pts:
                lt = datetime.fromtimestamp(k, timezone.utc).astimezone(TZ)
                region_hour[lt.hour].add(v)
                region_dow[lt.weekday()][lt.hour].add(v)
            region_span = [min(k for k, _ in pts), max(k for k, _ in pts)]

    out = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "Europe/London",
        "home": HOME,
        "worlds": worlds,
        "snapshots": len(snapshots),
        "first_snapshot_utc": min(snapshots) if snapshots else None,
        "last_snapshot_utc": last_snap,
        "latest": latest,
        "world_stats": {
            w: {
                "avg": r1(w_all[w].avg),
                "prime_avg": r1(w_prime[w].avg),
                "peak": w_peak[w][0], "peak_utc": w_peak[w][1],
                "low": w_low[w][0], "low_utc": w_low[w][1],
                "capacity": cap.get(w),
                "busiest_hour": (max(range(24), key=lambda h: w_hour[w][h].avg or -1)
                                 if w_all[w].n else None),
                "quietest_hour": (min(range(24), key=lambda h: w_hour[w][h].avg if w_hour[w][h].n else 1e9)
                                  if w_all[w].n else None),
            } for w in worlds
        },
        "world_hour_avg": {w: [r1(a.avg) for a in w_hour[w]] for w in worlds},
        "world_hour_peak": {w: [a.mx for a in w_hour[w]] for w in worlds},
        "world_hour_n": {w: [a.n for a in w_hour[w]] for w in worlds},
        "world_dow_hour_avg": {w: [[r1(a.avg) for a in day] for day in w_dow[w]] for w in worlds},
        "world_series": {w: [[k, r1(a.avg)] for k, a in sorted(w_series[w].items())] for w in worlds},
        "sietch_hour_avg": {w: {s: [r1(a.avg) for a in hrs] for s, hrs in sorted(s_hour[w].items())} for w in worlds},
        "sietch_avg": {w: {s: r1(a.avg) for s, a in s_all[w].items()} for w in worlds},
        "sietch_latest": {w: s_latest.get(w, {}) for w in worlds},
        "region_eu": {
            "label": "Europe, all platforms (dunestatus 15-min history)",
            "span_utc": region_span,
            "hour_avg": [r1(a.avg) for a in region_hour],
            "dow_hour_avg": [[r1(a.avg) for a in day] for day in region_dow],
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"summary: {len(snapshots)} snapshots -> {OUT}")


if __name__ == "__main__":
    build()
