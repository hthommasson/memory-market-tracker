"""Composite price x volume matrix (spec §4.2). The headline regime badge."""
import csv, os, os
import pandas as pd
from collectors.common import log, warn
from config.settings import DATA_DIR

REG = f"{DATA_DIR}/regime_daily.csv"
VOL = f"{DATA_DIR}/volume_regime.csv"
OUT = f"{DATA_DIR}/composite_regime.csv"

MATRIX = {  # (price, volume) -> cell label (spec §4.2, v0.2 relabel of the cycle-top cell)
    ("rising", "rising"):  "Accelerating (broad boom)",
    ("rising", "flat"):    "Scarcity-led (supply-constrained)",
    ("rising", "falling"): "Late-cycle squeeze (watch)",
    ("flat",   "rising"):  "Rationed squeeze (enterprise pull, consumer plateau)",
    ("flat",   "flat"):    "Stagnating",
    ("flat",   "falling"): "Early weakening (volume leads)",
    ("falling","rising"):  "CYCLE-TOP PATTERN (highest alert): bits flowing, ASPs cracking",
    ("falling","flat"):    "Softening",
    ("falling","falling"): "Weakening (broad)",
}

def latest_price_label():
    if not os.path.exists(REG): return "warming_up"
    reg = pd.read_csv(REG)
    comp = reg[reg["segment"] == "COMPOSITE"]
    return comp["label_committed"].iloc[-1] if len(comp) else "warming_up"

def latest_volume_label():
    if not os.path.exists(VOL): return "no_data"
    vol = pd.read_csv(VOL)
    return vol["label"].iloc[-1] if len(vol) else "no_data"

def main():
    p, v = latest_price_label(), latest_volume_label()
    cell = MATRIX.get((p, v))
    if cell is None:
        cell = f"pending — price:{p}, volume:{v}"
    today = pd.Timestamp.now("UTC").date().isoformat()
    # v2 (2026-07-12): ledger, not latest-state — the matrix's trajectory is the
    # instrument's memory (dwell times, transitions -> Monte Carlo priors later).
    # Idempotent per date: a re-run replaces today's row, never duplicates it.
    hist = []
    if os.path.exists(OUT):
        with open(OUT) as f:
            hist = [r for r in csv.DictReader(f) if r["computed_date"] != today]
    hist.append({"computed_date": today, "price_label": p, "volume_label": v, "cell": cell})
    hist.sort(key=lambda r: r["computed_date"])
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["computed_date", "price_label", "volume_label", "cell"])
        w.writeheader()
        w.writerows(hist)
    log(f"composite matrix: price={p} x volume={v} -> {cell} (ledger: {len(hist)} days)")

if __name__ == "__main__": main()
