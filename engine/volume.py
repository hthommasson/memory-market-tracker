"""Volume regime (spec §3.4, §4.2): Korea semis exports + Taiwan orders + Nanya revenue
-> Rising / Flat / Falling, plus derivation of non-overlapping Korea flash increments.

Method notes:
- Component state v1 is level-based on YoY growth (rising > +10%, falling < -10%), majority
  vote across available components, Korea breaking ties (tier-one feed). Tunable.
- Flash increments (P10, P11-20 = P20-P10, P21-END = month - P20) are derived per month.
  IMPORTANT: increments are only comparable to the SAME window type in other months —
  Korean exporters load shipments into month-end, so sequential within-month comparison
  is structurally biased. D2 consumes these window-over-same-window (spec §4.3, build note).
"""
import csv, os, re
import pandas as pd
from collectors.common import append_rows, log, warn
from config.settings import DATA_DIR

MS = f"{DATA_DIR}/monthly_series.csv"
OUT = f"{DATA_DIR}/volume_regime.csv"
RISE, FALL = 10.0, -10.0  # YoY % thresholds, tunable

COMPONENTS = {
    "korea": "kr_exports_semis_usd",
    "taiwan": "tw_export_orders_electronics_usd",
    "nanya": "nanya_2408_monthly_revenue_twd",
}


def parse_meta(meta):
    out = {}
    for part in str(meta or "").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def yoy_from(row):
    m = parse_meta(row.get("meta"))
    for key in ("yoy", "headline_yoy"):
        if key in m:
            match = re.search(r"[-+]?\d+(\.\d+)?", m[key])
            if match:
                return float(match.group())
    v = row.get("value_wda")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def state(yoy):
    if yoy is None:
        return "no_data"
    if yoy > RISE:
        return "rising"
    if yoy < FALL:
        return "falling"
    return "flat"


def monthly_rows(df, metric):
    """Plain YYYY-MM rows for a metric (excludes flash P-periods), newest last."""
    rows = df[(df["metric"] == metric) & (~df["period"].astype(str).str.contains("-P"))]
    return rows.sort_values("period")


def derive_increments(df):
    """Emit derived Korea total increments per month where inputs exist; idempotent."""
    existing = set(zip(df["period"], df["metric"]))
    new = []
    totals = df[df["metric"] == "kr_exports_total_usd"]
    months = sorted(set(p.split("-P")[0] for p in totals["period"].astype(str)))
    for month in months:
        get = lambda per: totals[totals["period"] == per]
        p10 = get(f"{month}-P10")
        p20 = get(f"{month}-P20")
        mon = get(month)
        v10 = float(p10["value"].iloc[0]) if len(p10) else None
        v20 = float(p20["value"].iloc[0]) if len(p20) else None
        vm = float(mon["value"].iloc[0]) if len(mon) else None
        wd20 = parse_meta(p20["meta"].iloc[0]).get("working_days", "") if len(p20) else ""
        wd20 = re.match(r"\d+", wd20)
        wd20 = int(wd20.group()) if wd20 else None
        cands = []
        if v10 is not None:
            cands.append((f"{month}-P10", "kr_inc_p10_usd", v10, ""))
        if v10 is not None and v20 is not None:
            cands.append((f"{month}-P20", "kr_inc_p11_20_usd", v20 - v10, ""))
        if v20 is not None and vm is not None:
            meta = f"per_wd_flash={round(v20/wd20/1e9,3)}bn" if wd20 else "per_wd_unavailable"
            cands.append((month, "kr_inc_p21_end_usd", vm - v20,
                          f"compare_same_window_only|{meta}"))
        for period, metric, val, meta in cands:
            if (period, metric) not in existing:
                new.append([period, "derived", metric, round(val, 2), "", meta])
    if new:
        append_rows(MS, ["period", "source", "metric", "value", "value_wda", "meta"], new)
    return len(new)


def main():
    if not os.path.exists(MS):
        warn("no monthly_series.csv yet")
        return
    df = pd.read_csv(MS, dtype=str)
    n_inc = derive_increments(df)

    states, detail = {}, []
    for name, metric in COMPONENTS.items():
        rows = monthly_rows(df, metric)
        yoy = yoy_from(rows.iloc[-1]) if len(rows) else None
        states[name] = state(yoy)
        detail.append(f"{name}={states[name]}({yoy if yoy is not None else '-'})")

    votes = [s for s in states.values() if s != "no_data"]
    if not votes:
        label = "no_data"
    else:
        counts = {v: votes.count(v) for v in set(votes)}
        top = sorted(counts.items(), key=lambda kv: -kv[1])
        label = states["korea"] if (len(top) > 1 and top[0][1] == top[1][1]
                                    and states["korea"] != "no_data") else top[0][0]

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["computed_date", "label", "korea", "taiwan", "nanya", "detail"])
        w.writerow([pd.Timestamp.now("UTC").date().isoformat(), label,
                    states["korea"], states["taiwan"], states["nanya"], "; ".join(detail)])
    log(f"volume regime: {label} [{'; '.join(detail)}] (+{n_inc} derived increment rows)")


if __name__ == "__main__":
    main()
