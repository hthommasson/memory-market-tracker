"""Contract-price track (added 2026-09-09): DRAMeXchange fixed contract prices, as quoted in
the footnote of MOTIE's monthly export release, -> level, month-over-month change,
acceleration (second derivative) and a descriptive state per series.

Why this exists:
- eBay ask-floors are retail, thin (k=3 books) and seller-concentrated. Contract price is the
  series supplier revenue is actually a function of, and it arrives monthly for free.
- The cycle-top tell in past DRAM cycles is not price falling; it is price still rising but
  rising more slowly. That is the acceleration column.
- retail_to_contract compares the eBay DDR5-desktop floor ($/GB, module, retail) with the
  contract chip price ($/GB, 16Gb = 2GB). A module normally costs MORE per GB than its chips
  (PCB, SPD, margin), so a ratio below 1 says retail asks are stale inventory priced below
  replacement cost -- i.e. retail has not caught up with contract yet.

Observational only: NOT wired into the composite cell until the signature is backtested on
prior cycles. States use their own MoM thresholds (contract prices are smooth; the eBay
ln-slope thresholds in settings were calibrated for noisy 30-day floors).

Reads : docs/data/monthly_series.csv   (metric in SERIES, plain YYYY-MM periods)
        docs/data/segment_daily.csv    (ddr5_desktop floor, for the ratio; optional)
Writes: docs/data/contract_regime.csv  (rebuilt each run; one row per month per series)
"""
import csv, math, os
import pandas as pd
from collectors.common import log, warn
from config.settings import DATA_DIR

MS = f"{DATA_DIR}/monthly_series.csv"
SEG = f"{DATA_DIR}/segment_daily.csv"
OUT = f"{DATA_DIR}/contract_regime.csv"

SERIES = {                       # monthly_series metric -> short name
    "dram_ddr5_16gb_fixed_usd": "ddr5_16gb",
    "nand_128gb_fixed_usd": "nand_128gb",
}
GB_PER_CHIP = {"ddr5_16gb": 2.0}  # 16 Gbit = 2 GByte; ratio only defined where known
RATIO_SEGMENT = "ddr5_desktop"    # eBay segment compared against the DRAM contract price

RISE_MOM, FALL_MOM = 1.0, -1.0    # MoM % : rising / falling / else flat   (tunable)
ACCEL_PP = 3.0                    # |MoM - prior MoM| in pct-points: accelerating / decelerating

COLS = ["month", "series", "price_usd", "mom_pct", "mom_prev_pct", "accel_pp",
        "mom_3m_avg_pct", "ann_3m", "state", "momentum",
        "retail_floor_usd_per_gb", "retail_to_contract"]


def mom_pct(cur, prev):
    return 100.0 * (cur / prev - 1.0) if prev else None


def ann_3m(values):
    """Annualized ln-slope over the last three monthly intervals (fewer if not available)."""
    v = [x for x in values[-4:] if x is not None]
    if len(v) < 2 or v[0] <= 0:
        return None
    return math.log(v[-1] / v[0]) * 12.0 / (len(v) - 1)


def state(mom):
    if mom is None:
        return "warming_up"
    return "rising" if mom > RISE_MOM else "falling" if mom < FALL_MOM else "flat"


def momentum(accel):
    if accel is None:
        return "warming_up"
    return "accelerating" if accel >= ACCEL_PP else "decelerating" if accel <= -ACCEL_PP else "steady"


def track(months, prices):
    """months: ['YYYY-MM', ...] ascending; prices: floats. -> list of dict rows (no ratio)."""
    rows, moms = [], []
    for i, (m, p) in enumerate(zip(months, prices)):
        cur = mom_pct(p, prices[i - 1]) if i else None
        prev = moms[-1] if moms else None
        moms.append(cur)
        accel = (cur - prev) if (cur is not None and prev is not None) else None
        recent = [x for x in moms[-3:] if x is not None]
        rows.append({
            "month": m, "price_usd": p,
            "mom_pct": None if cur is None else round(cur, 2),
            "mom_prev_pct": None if prev is None else round(prev, 2),
            "accel_pp": None if accel is None else round(accel, 2),
            "mom_3m_avg_pct": round(sum(recent) / len(recent), 2) if recent else None,
            "ann_3m": (lambda a: None if a is None else round(a, 4))(ann_3m(prices[: i + 1])),
            "state": state(cur), "momentum": momentum(accel),
        })
    return rows


def monthly_floor_by_month(seg_path=SEG, segment=RATIO_SEGMENT):
    """-> {'YYYY-MM': mean floor usd_per_gb} for one eBay segment; {} if unavailable."""
    if not os.path.exists(seg_path):
        return {}
    s = pd.read_csv(seg_path, dtype=str)
    f = s[(s["series"] == "floor") & (s["segment"] == segment)].copy()
    if f.empty:
        return {}
    f["usd_per_gb"] = pd.to_numeric(f["usd_per_gb"], errors="coerce")
    f = f.dropna(subset=["usd_per_gb"])
    f["m"] = f["date"].str[:7]
    return f.groupby("m")["usd_per_gb"].mean().round(3).to_dict()


def build(ms_path=MS, seg_path=SEG):
    df = pd.read_csv(ms_path, dtype=str)
    df = df[df["metric"].isin(SERIES) & ~df["period"].astype(str).str.contains("-P")]
    floors = monthly_floor_by_month(seg_path)
    out = []
    for metric, name in SERIES.items():
        d = df[df["metric"] == metric].copy()
        if d.empty:
            continue
        d["value"] = pd.to_numeric(d["value"], errors="coerce")
        d = d.dropna(subset=["value"]).drop_duplicates("period", keep="last").sort_values("period")
        rows = track(d["period"].tolist(), d["value"].astype(float).tolist())
        for r in rows:
            r["series"] = name
            gb = GB_PER_CHIP.get(name)
            fl = floors.get(r["month"])
            r["retail_floor_usd_per_gb"] = fl if (gb and fl is not None) else None
            r["retail_to_contract"] = (round(fl / (r["price_usd"] / gb), 3)
                                       if (gb and fl is not None and r["price_usd"]) else None)
            out.append(r)
    return out


def main():
    if not os.path.exists(MS):
        warn("no monthly_series.csv yet")
        return
    rows = build()
    if not rows:
        warn("no contract-price rows in monthly_series.csv (metrics: %s)" % ", ".join(SERIES))
        return
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLS})
    latest = {}
    for r in rows:
        latest[r["series"]] = r
    detail = "; ".join(f"{k}=${v['price_usd']} {v['state']}/{v['momentum']}"
                       f"(mom {v['mom_pct']}%, accel {v['accel_pp']}pp)" for k, v in latest.items())
    log(f"contract track: {len(rows)} rows -> {OUT} [{detail}]")


if __name__ == "__main__":
    main()
