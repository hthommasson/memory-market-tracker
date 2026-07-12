"""Lead-lag statistics module (spec §4.4). Descriptive only — no regressions, no backtests.

Builds monthly-aligned series from whatever data exists, transforms levels to changes
(log-diff) and rates to differences, then scans hypothesis-directional pairs at lags
0..6 months: corr(x_t, y_{t+lag}) answers "does X lead Y by `lag` months?".

Guardrails:
- Levels are NEVER correlated directly (trending levels correlate spuriously).
- Pairs with < MIN_PAIRS overlapping months report status=insufficient_n, corr blank.
- Quarterly fundamentals are placed at their period-end month, NOT interpolated to
  monthly — interpolation manufactures observations and inflates n. (Deliberately
  more conservative than the spec's wording; n shown is real.)
Output: docs/data/stats_lagged_corr.csv, rebuilt each run.
"""
import os
import numpy as np
import pandas as pd
from collectors.common import log, warn
from config.settings import DATA_DIR

MIN_PAIRS = 6
MAX_LAG = 6

# (series_name, transform) — transform: "logdiff" for levels, "diff" for rates/ratios
SERIES_SPEC = {
    "phys_ddr5":         ("segment", "ddr5_desktop", "logdiff"),
    "phys_ddr4":         ("segment", "ddr4_desktop", "logdiff"),
    "kr_semis":          ("monthly", "kr_exports_semis_usd", "logdiff"),
    "tw_orders":         ("monthly", "tw_export_orders_electronics_usd", "logdiff"),
    "nanya_rev":         ("monthly", "nanya_2408_monthly_revenue_twd", "logdiff"),
    "mu_revenue":        ("filing", "revenue", "logdiff"),
    "mu_gross_margin":   ("filing", "gross_margin_pct", "diff"),
    "mu_inventory_days": ("filing", "inventory_days", "diff"),
    "equity_mu":         ("equity", "MU", "logdiff"),
    "equity_dram":       ("equity", "DRAM", "logdiff"),
}

# Hypothesis-directional pairs: X (candidate leader) -> Y (candidate follower)
PAIRS = [
    ("tw_orders", "kr_semis"),           # orders precede shipments
    ("kr_semis", "mu_revenue"),          # exports precede reported revenue
    ("kr_semis", "equity_mu"),           # volume pulse vs the stock
    ("phys_ddr5", "mu_gross_margin"),    # retail momentum precedes margins
    ("phys_ddr5", "equity_dram"),        # physical vs basket (D1's monthly cousin)
    ("nanya_rev", "phys_ddr4"),          # pure-play DRAM revenue vs legacy retail
    ("mu_inventory_days", "phys_ddr5"),  # channel inventory precedes price turns
]


def month_index(s):
    """Series indexed by 'YYYY-MM' strings -> continuous monthly PeriodIndex (gaps=NaN)."""
    s = s[~s.index.duplicated(keep="last")].sort_index()
    idx = pd.PeriodIndex(s.index, freq="M")
    s.index = idx
    full = pd.period_range(idx.min(), idx.max(), freq="M")
    return s.reindex(full)


def load_series():
    out = {}
    seg_p = f"{DATA_DIR}/segment_daily.csv"
    seg = pd.read_csv(seg_p) if os.path.exists(seg_p) else pd.DataFrame()
    ms_p = f"{DATA_DIR}/monthly_series.csv"
    ms = pd.read_csv(ms_p, dtype=str) if os.path.exists(ms_p) else pd.DataFrame()
    ff_p = f"{DATA_DIR}/filings_facts.csv"
    ff = pd.read_csv(ff_p) if os.path.exists(ff_p) else pd.DataFrame()
    eq_p = f"{DATA_DIR}/equity_daily.csv"
    eq = pd.read_csv(eq_p) if os.path.exists(eq_p) else pd.DataFrame()

    for name, (kind, key, transform) in SERIES_SPEC.items():
        s = None
        if kind == "segment" and len(seg):
            rows = seg[(seg["segment"] == key) & (seg["series"] == "floor")].copy()
            if len(rows):
                rows["month"] = rows["date"].str[:7]
                s = rows.groupby("month")["usd_per_gb"].median()
        elif kind == "monthly" and len(ms):
            rows = ms[(ms["metric"] == key)
                      & (~ms["period"].str.contains("-P"))].copy()
            if len(rows):
                s = rows.set_index("period")["value"].astype(float)
        elif kind == "filing" and len(ff):
            rows = ff[ff["concept"] == key].copy()
            if len(rows):
                rows["month"] = rows["period_end"].astype(str).str[:7]
                s = rows.groupby("month")["value"].last().astype(float)
        elif kind == "equity" and len(eq):
            rows = eq[eq["ticker"] == key].copy()
            if len(rows):
                rows["month"] = rows["date"].str[:7]
                s = rows.sort_values("date").groupby("month")["close"].last()
        if s is None or len(s) < 2:
            out[name] = None
            continue
        s = month_index(s.astype(float))
        if transform == "logdiff":
            s = np.log(s).diff()
        else:
            s = s.diff()
        out[name] = s
    return out


def lag_corr(x, y, lag):
    """corr(x_t, y_{t+lag}) on overlapping non-NaN months; returns (n, spearman, pearson)."""
    pair = pd.concat({"x": x, "y": y.shift(-lag)}, axis=1).dropna()
    n = len(pair)
    if n < MIN_PAIRS:
        return n, None, None
    return (n,
            # Spearman = Pearson on ranks; avoids the scipy dependency pandas would otherwise
            # import here (never in requirements.txt — caught by CI run #1, 2026-07-12)
            round(pair["x"].rank().corr(pair["y"].rank()), 3),
            round(pair["x"].corr(pair["y"], method="pearson"), 3))


def main():
    series = load_series()
    rows = []
    for x_name, y_name in PAIRS:
        x, y = series.get(x_name), series.get(y_name)
        if x is None or y is None:
            rows.append([f"{x_name}->{y_name}", "", 0, "", "",
                         "missing_series", ""])
            continue
        best = None
        for lag in range(0, MAX_LAG + 1):
            n, sp, pe = lag_corr(x, y, lag)
            status = "ok" if sp is not None else "insufficient_n"
            rows.append([f"{x_name}->{y_name}", lag, n,
                         sp if sp is not None else "",
                         pe if pe is not None else "", status, ""])
            if sp is not None and (best is None or abs(sp) > abs(best[1])):
                best = (lag, sp)
        if best:
            rows.append([f"{x_name}->{y_name}", best[0], "", best[1], "",
                         "ok", "BEST_LAG"])
    out = pd.DataFrame(rows, columns=["pair", "lag_months", "n", "spearman",
                                      "pearson", "status", "note"])
    out.to_csv(f"{DATA_DIR}/stats_lagged_corr.csv", index=False)
    ok = (out["note"] == "BEST_LAG").sum()
    log(f"stats: {len(PAIRS)} pairs scanned, {ok} with sufficient data "
        f"(min {MIN_PAIRS} overlapping months; descriptive only)")


if __name__ == "__main__":
    main()
