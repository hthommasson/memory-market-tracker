"""Macro context collector — official US series via FRED (added 2026-07-07).

Feeds monthly_series.csv with BLS producer-price indices for semiconductor
manufacturing, industrial production, and a monthly-average KRW/USD rate that
doubles as the FX fallback. This is the third independent price lens (producer
prices, alongside retail asks and distributor books) — official, revised, and
~2 weeks lagged: context for the dashboard, never an input to the momentum engine.

Append-only by (period, metric): existing rows — including every manual entry —
are never touched. Series that FRED reports as missing or stale are skipped with
a warning (several BLS product lines died in Sep 2025; assume it can happen again).
Graceful activation: no FRED_API_KEY -> polite skip, collector ships before the key.
"""
import csv, os, sys
import requests
from collectors.common import append_rows, log, warn
from config.settings import DATA_DIR, FRED_SERIES, FRED_OBS_START

PATH = f"{DATA_DIR}/monthly_series.csv"
HEADER = ["period", "source", "metric", "value", "value_wda", "meta"]
OBS_URL = "https://api.stlouisfed.org/fred/series/observations"


def existing_keys():
    if not os.path.exists(PATH): return set()
    with open(PATH) as f:
        return {(r["period"], r["metric"]) for r in csv.DictReader(f)}


def fetch(series_id, key):
    r = requests.get(OBS_URL, timeout=30, params={
        "series_id": series_id, "api_key": key, "file_type": "json",
        "observation_start": FRED_OBS_START,
        "frequency": "m", "aggregation_method": "avg"})
    r.raise_for_status()
    obs = r.json().get("observations", [])
    out = []
    for o in obs:
        if o.get("value") in (".", "", None): continue
        out.append((o["date"][:7], float(o["value"])))
    return out


def main():
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        log("FRED_API_KEY not set — skipping FRED (add the secret to activate)"); return
    have = existing_keys()
    new = []
    for sid, metric in FRED_SERIES.items():
        try:
            obs = fetch(sid, key)
            if not obs:
                warn(f"{sid}: no observations returned — series stale or renamed?"); continue
            added = 0
            for period, val in obs:
                if (period, metric) not in have:
                    new.append([period, "fred", metric, val, "", f"fred:{sid}"])
                    have.add((period, metric)); added += 1
            log(f"{sid} -> {metric}: {added} new rows (through {obs[-1][0]})")
        except Exception as e:
            warn(f"{sid}: {e} — other series unaffected")
    if new:
        append_rows(PATH, HEADER, new)
        log(f"monthly_series: +{len(new)} FRED rows appended")
    else:
        log("FRED: nothing new")


if __name__ == "__main__": main()
