"""Weekly basket health (spec §6): report SKUs missing/out-of-stock >= 7 days."""
import csv, os
import pandas as pd
from collectors.common import log
from config.settings import DATA_DIR

OBS = f"{DATA_DIR}/price_obs.csv"
REGISTRY = "config/sku_registry.csv"

def main():
    reg = pd.read_csv(REGISTRY)
    active = reg[reg["retired_on"].fillna("") == ""]["sku_id"].tolist()
    problems = []
    if not os.path.exists(OBS):
        print("no observations yet — collectors have not run"); return
    obs = pd.read_csv(OBS)
    if obs.empty: print("no observations yet"); return
    latest = obs["date"].max()
    ok = obs[(obs["in_stock"].astype(str) == "True")]
    last_ok = ok.groupby("sku_id")["date"].max()
    for sku in active:
        seen = last_ok.get(sku)
        if seen is None:
            problems.append(f"{sku}: never had >=k qualifying listings")
        else:
            gap = (pd.Timestamp(latest) - pd.Timestamp(seen)).days
            if gap >= 7: problems.append(f"{sku}: no qualifying listings for {gap} days (last {seen})")
    if problems:
        print("BASKET HEALTH ISSUES")
        for p in problems: print(f"- {p}")
    else:
        print("basket healthy")

if __name__ == "__main__": main()
