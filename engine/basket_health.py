"""Weekly basket health (spec §6): report SKUs missing/out-of-stock >= 7 days.

Two lanes (2026-08-20):
  "- " problem lines  -> drive the weekly issue (the workflow counts lines starting "- ")
  "~ " acknowledged   -> registry rows with status=ack_dark: books whose dark state is a
                         standing, human-acknowledged signal (e.g. a sold-out-but-alive
                         Samsung server listing whose absence IS the allocation story).
                         Reported for visibility, never alerted on.
Flip an ack'd book's status back to blank to resume alerting for it.
"""
import csv, os
import pandas as pd
from collectors.common import log
from config.settings import DATA_DIR

OBS = f"{DATA_DIR}/price_obs.csv"
REGISTRY = "config/sku_registry.csv"

def main():
    reg = pd.read_csv(REGISTRY)
    active = reg[reg["retired_on"].fillna("") == ""]["sku_id"].tolist()
    acked = set(reg[reg["status"].fillna("") == "ack_dark"]["sku_id"])
    problems, watching = [], []
    if not os.path.exists(OBS):
        print("no observations yet — collectors have not run"); return
    obs = pd.read_csv(OBS)
    if obs.empty: print("no observations yet"); return
    latest = obs["date"].max()
    ok = obs[(obs["in_stock"].astype(str) == "True")]
    last_ok = ok.groupby("sku_id")["date"].max()
    first = dict(zip(reg["sku_id"], reg["first_seen"].fillna(latest)))
    for sku in active:
        seen = last_ok.get(sku)
        if seen is None:
            age = (pd.Timestamp(latest) - pd.Timestamp(first.get(sku, latest))).days
            if age >= 7:   # grace period: new candidates get a week before being flagged
                (watching if sku in acked else problems).append(
                    f"{sku}: no qualifying listings in the {age} days since added")
        else:
            gap = (pd.Timestamp(latest) - pd.Timestamp(seen)).days
            if gap >= 7:
                (watching if sku in acked else problems).append(
                    f"{sku}: no qualifying listings for {gap} days (last {seen})")
    if problems:
        print("BASKET HEALTH ISSUES")
        for p in problems: print(f"- {p}")
    else:
        print("basket healthy"
              + (f" ({len(watching)} acknowledged dark books watching)" if watching else ""))
    if watching:
        print("ACKNOWLEDGED DARK (watching, not alerting)")
        for w in watching: print(f"~ {w}")

if __name__ == "__main__": main()
