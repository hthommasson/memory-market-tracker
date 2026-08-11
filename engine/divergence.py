"""Divergence flags (spec §4.3). D1 implemented; D2-D4 gated on their data feeds."""
import csv
import os
import pandas as pd
from collectors.common import log, warn
from config.settings import DATA_DIR

EQ = f"{DATA_DIR}/equity_daily.csv"
REG = f"{DATA_DIR}/regime_daily.csv"
OUT = f"{DATA_DIR}/divergence_flags.csv"
HEADER = ["date", "flag", "detail"]
D1_EQ_MAG, D1_PHYS_MAG = 0.05, 0.15  # thresholds: 20d equity return, composite m30 (annualized)

def d1():
    """Equity vs physical: signs disagree with both beyond magnitude thresholds."""
    if not (os.path.exists(EQ) and os.path.exists(REG)): return None
    eq = pd.read_csv(EQ)
    dram = eq[eq["ticker"] == "DRAM"].sort_values("date")
    if len(dram) < 21: return None
    r20 = dram["close"].iloc[-1] / dram["close"].iloc[-21] - 1
    reg = pd.read_csv(REG)
    comp = reg[reg["segment"] == "COMPOSITE"]
    if comp.empty: return None
    m30 = pd.to_numeric(comp["m30_annualized"], errors="coerce").iloc[-1]
    if pd.isna(m30): return None
    if abs(r20) >= D1_EQ_MAG and abs(m30) >= D1_PHYS_MAG and (r20 > 0) != (m30 > 0):
        return f"D1: DRAM 20d {r20:+.1%} vs physical m30 {m30:+.1%} — layers disagree"
    return None

def d2(): return None  # TODO: non-overlapping Korea flash increments (needs 2 flash cycles in monthly_series)
def d3(): return None  # TODO: MU inventory-days + gross-margin joint trend light (needs 2+ new quarters)
def d4(): return None  # TODO: chop-dominant trend-quality + flat regime notice (needs 60d equity history live)

def upsert_rows(path, header, rows):
    """Date-keyed ledger (v0.4.1): exactly one row per (date, flag); latest run wins.

    Replaces collectors.common.append_rows here. The append-only writer produced 2-4
    identical rows per firing day because both redundant crons (22:47/23:29 UTC), any
    manual Run-workflow, and post-midnight ghost runs each appended a fresh row. Because
    this rewrites the whole file keyed on (date, flag), the first run after this patch
    also collapses the dups already on disk — no manual cleanup needed. Output is sorted
    so the ledger is deterministic regardless of write history. append_rows is left alone:
    price_obs/dist_obs legitimately append many rows per day and must not be deduped.
    """
    keyed = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                keyed[(r.get("date", ""), r.get("flag", ""))] = [r.get(h, "") for h in header]
    for row in rows:
        keyed[(str(row[0]), str(row[1]))] = [str(c) for c in row]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for key in sorted(keyed):
            w.writerow(keyed[key])
    os.replace(tmp, path)
    log(f"upserted {len(rows)} row(s) -> {path} ({len(keyed)} total after dedup)")

def main():
    fired = [f for f in (d1(), d2(), d3(), d4()) if f]
    if fired:
        today = pd.Timestamp.now("UTC").date().isoformat()
        upsert_rows(OUT, HEADER, [[today, f.split(":")[0], f] for f in fired])
        for f in fired: log(f"FLAG {f}")
    else:
        log("no divergence flags today")

if __name__ == "__main__": main()
