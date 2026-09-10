import csv, os
import pandas as pd
from engine.contract import (track, state, momentum, ann_3m, build,
                             RISE_MOM, FALL_MOM, ACCEL_PP)


def test_mom_and_acceleration_on_motie_series():
    # DDR5 16Gb fixed price Apr..Aug 2026 as printed in MOTIE's August release footnote
    rows = track(["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
                 [35.0, 37.5, 40.0, 45.0, 46.5])
    assert rows[0]["mom_pct"] is None and rows[0]["state"] == "warming_up"
    assert rows[1]["momentum"] == "warming_up"          # needs two MoM readings
    assert abs(rows[3]["mom_pct"] - 12.5) < 1e-9
    assert rows[3]["momentum"] == "accelerating"        # 6.67 -> 12.5
    assert abs(rows[4]["mom_pct"] - 3.33) < 0.01
    assert rows[4]["accel_pp"] < -ACCEL_PP and rows[4]["momentum"] == "decelerating"
    assert rows[4]["state"] == "rising"                 # still rising, just slower


def test_state_thresholds():
    assert state(RISE_MOM + 0.1) == "rising"
    assert state(FALL_MOM - 0.1) == "falling"
    assert state(0.0) == "flat"
    assert state(None) == "warming_up"
    assert momentum(ACCEL_PP) == "accelerating"
    assert momentum(-ACCEL_PP) == "decelerating"
    assert momentum(ACCEL_PP - 0.01) == "steady"


def test_ann_3m_recovers_constant_growth():
    # +5%/month compounding -> ln(1.05)*12 annualized ln-slope, regardless of window length
    p = [100 * 1.05 ** i for i in range(6)]
    assert abs(ann_3m(p) - 12 * 0.04879) < 1e-3
    assert ann_3m([100.0]) is None


def test_build_ratio_and_dedup(tmp_path):
    ms = tmp_path / "monthly_series.csv"
    with open(ms, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "source", "metric", "value", "value_wda", "meta"])
        w.writerow(["2026-07", "motie", "dram_ddr5_16gb_fixed_usd", "40.0", "", ""])
        w.writerow(["2026-07", "motie", "dram_ddr5_16gb_fixed_usd", "45.0", "", "corrected"])  # dup: last wins
        w.writerow(["2026-08", "motie", "dram_ddr5_16gb_fixed_usd", "46.5", "", ""])
        w.writerow(["2026-08-P20", "kcs_flash", "dram_ddr5_16gb_fixed_usd", "99", "", ""])  # flash: ignored
        w.writerow(["2026-08", "motie", "kr_exports_total_usd", "98250000000", "", ""])     # other metric
    seg = tmp_path / "segment_daily.csv"
    pd.DataFrame({"date": ["2026-08-01", "2026-08-02"], "segment": ["ddr5_desktop"] * 2,
                  "series": ["floor"] * 2, "usd_per_gb": [15.0, 16.0], "n_obs": [3, 3],
                  "in_stock_rate": ["", ""]}).to_csv(seg, index=False)
    rows = build(str(ms), str(seg))
    assert [r["month"] for r in rows] == ["2026-07", "2026-08"]
    assert rows[0]["price_usd"] == 45.0                 # dedup kept the later row
    aug = rows[1]
    assert aug["retail_floor_usd_per_gb"] == 15.5       # mean of the two floor days
    assert abs(aug["retail_to_contract"] - 15.5 / (46.5 / 2.0)) < 1e-3
    assert rows[0]["retail_to_contract"] is None        # no July floors in this fixture
