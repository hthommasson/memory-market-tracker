"""Regime engine (spec §4.1): segment $/GB series -> momentum, acceleration,
hysteresis-committed labels, quality-gated weighted composite.

Reads  docs/data/price_obs.csv  (from collectors.ebay_prices)
Writes docs/data/segment_daily.csv  and  docs/data/regime_daily.csv
"""
import csv, math, os
import numpy as np
import pandas as pd
from collectors.common import log, warn
from config.settings import (DATA_DIR, WEIGHTS, THRESH_UP, THRESH_DOWN,
                             MOMENTUM_WINDOW, ACCEL_LAG, HYSTERESIS_DAYS,
                             MIN_OBS_FOR_LABEL, QUALITY_GATE_MIN_OBS,
                             QUALITY_GATE_MAX_GAP)

REGISTRY = "config/sku_registry.csv"
OBS = f"{DATA_DIR}/price_obs.csv"
SEG_OUT = f"{DATA_DIR}/segment_daily.csv"
REG_OUT = f"{DATA_DIR}/regime_daily.csv"


def build_segment_daily():
    """price_obs -> per-segment daily basket (median of sku floors, per-GB) + floor (min)."""
    reg = pd.read_csv(REGISTRY).set_index("sku_id")
    obs = pd.read_csv(OBS)
    obs = obs[(obs["in_stock"] == True) | (obs["in_stock"] == "True")]
    obs = obs[pd.to_numeric(obs["price"], errors="coerce").notna()].copy()
    obs["price"] = obs["price"].astype(float)
    obs["segment"] = obs["sku_id"].map(reg["segment"])
    obs["gb"] = obs["sku_id"].map(reg["capacity_gb"]).astype(float)
    obs["usd_per_gb"] = obs["price"] / obs["gb"]
    rows = []
    for (date, seg), g in obs.groupby(["date", "segment"]):
        rows.append([date, seg, "basket", round(g["usd_per_gb"].median(), 4),
                     len(g), round(len(g) / max(1, (reg["segment"] == seg).sum()), 3)])
        rows.append([date, seg, "floor", round(g["usd_per_gb"].min(), 4), len(g), ""])
    out = pd.DataFrame(rows, columns=["date", "segment", "series", "usd_per_gb",
                                      "n_obs", "in_stock_rate"])
    out.sort_values(["date", "segment", "series"]).to_csv(SEG_OUT, index=False)
    log(f"segment_daily rebuilt: {len(out)} rows")
    return out


def ann_slope(series):
    """Annualized OLS slope of ln(price) over the window; None if insufficient."""
    s = series.dropna()
    if len(s) < MIN_OBS_FOR_LABEL:
        return None
    y = np.log(s.values[-MOMENTUM_WINDOW:])
    x = np.arange(len(y), dtype=float)
    slope = np.polyfit(x, y, 1)[0]          # per observed day
    return slope * 365.0


def raw_label(m30):
    if m30 is None:
        return "warming_up"
    if m30 > THRESH_UP:
        return "rising"
    if m30 < THRESH_DOWN:
        return "falling"
    return "flat"


def committed(labels):
    """Hysteresis: a state change requires HYSTERESIS_DAYS consecutive identical raw labels."""
    state = None
    out = []
    run_label, run_len = None, 0
    for lab in labels:
        if lab == run_label:
            run_len += 1
        else:
            run_label, run_len = lab, 1
        if state is None and lab not in ("warming_up",):
            state = lab
        elif run_label != state and run_len >= HYSTERESIS_DAYS and run_label != "warming_up":
            state = run_label
        out.append(state if state else "warming_up")
    return out


def quality_ok(dates):
    if len(dates) < QUALITY_GATE_MIN_OBS:
        return False
    d = pd.to_datetime(pd.Series(sorted(set(dates))))
    return d.diff().dt.days.fillna(1).max() <= QUALITY_GATE_MAX_GAP + 1


def main():
    if not os.path.exists(OBS):
        warn("no price_obs.csv yet — run a collector first")
        return
    seg = build_segment_daily()
    floor = seg[seg["series"] == "floor"].pivot(index="date", columns="segment",
                                                values="usd_per_gb").sort_index()
    rows = []
    seg_state = {}
    m30_by_segment = {}
    for segment in floor.columns:
        s = floor[segment].dropna()
        m30s, raws = [], []
        for i in range(len(s)):
            window = s.iloc[: i + 1]
            m30 = ann_slope(window)
            m30s.append(m30)
            raws.append(raw_label(m30))
        comm = committed(raws)
        for i, date in enumerate(s.index):
            lag_i = i - ACCEL_LAG
            a30 = (m30s[i] - m30s[lag_i]) if (m30s[i] is not None and lag_i >= 0
                                              and m30s[lag_i] is not None) else ""
            rows.append([date, segment,
                         round(m30s[i], 4) if m30s[i] is not None else "",
                         round(a30, 4) if a30 != "" else "",
                         raws[i], comm[i]])
        seg_state[segment] = {"label": comm[-1] if comm else "warming_up",
                              "m30": m30s[-1],
                              "quality": quality_ok(list(s.index))}
        m30_by_segment[segment] = pd.Series(m30s, index=s.index, dtype=float)

    # Quality-gated composite as a full per-date series WITH hysteresis (v0.4 build fix:
    # a latest-day-only composite flapped on noise; the headline badge must not flap).
    live = sorted(k for k, v in seg_state.items() if v["quality"])
    gated_note = ",".join(sorted(set(seg_state) - set(live))) or "none"
    m30_df = pd.DataFrame(m30_by_segment)  # date-indexed, one column per segment
    comp_m30s, comp_raws, comp_dates = [], [], []
    for date, r in m30_df.iterrows():
        avail = {k: r[k] for k in live if k in r and pd.notna(r[k])}
        wsum = sum(WEIGHTS.get(k, 0) for k in avail)
        cm = sum(WEIGHTS.get(k, 0) / wsum * v for k, v in avail.items()) if wsum else None
        comp_dates.append(date)
        comp_m30s.append(cm)
        comp_raws.append(raw_label(cm))
    comp_comm = committed(comp_raws)
    for i, date in enumerate(comp_dates):
        rows.append([date, "COMPOSITE",
                     round(comp_m30s[i], 4) if comp_m30s[i] is not None else "",
                     f"gated:{gated_note}", comp_raws[i], comp_comm[i]])
    comp_label = comp_comm[-1] if comp_comm else "warming_up"
    comp_m30 = comp_m30s[-1] if comp_m30s else None

    with open(REG_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "segment", "m30_annualized", "a30", "label_raw", "label_committed"])
        w.writerows(rows)
    log(f"regime_daily rebuilt: {len(rows)} rows; composite={comp_label} "
        f"(m30={comp_m30 if comp_m30 is None else round(comp_m30, 3)})")


if __name__ == "__main__":
    main()
