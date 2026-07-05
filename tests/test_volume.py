import pandas as pd
from engine.volume import parse_meta, yoy_from, state, derive_increments
from engine.composite import MATRIX

def test_meta_and_yoy():
    row = {"meta": "yoy=+199.5%|record", "value_wda": ""}
    assert yoy_from(row) == 199.5
    assert state(199.5) == "rising" and state(-30) == "falling" and state(3) == "flat"

def test_june_increment_derivation(tmp_path, monkeypatch):
    import engine.volume as V
    ms = tmp_path / "monthly_series.csv"
    pd.DataFrame([
        ["2026-06", "motie", "kr_exports_total_usd", 102250000000, "", "yoy=+70.9%"],
        ["2026-06-P20", "kcs", "kr_exports_total_usd", 61990000000, "49.7", "working_days=15v14"],
    ], columns=["period","source","metric","value","value_wda","meta"]).to_csv(ms, index=False)
    monkeypatch.setattr(V, "MS", str(ms))
    df = pd.read_csv(ms, dtype=str)
    n = derive_increments(df)
    assert n == 1
    out = pd.read_csv(ms)
    inc = out[out["metric"] == "kr_inc_p21_end_usd"]
    assert len(inc) == 1 and abs(float(inc["value"].iloc[0]) - 40260000000) < 1
    assert "compare_same_window_only" in inc["meta"].iloc[0]

def test_matrix_cells():
    assert "CYCLE-TOP" in MATRIX[("falling", "rising")]
    assert "Rationed squeeze" in MATRIX[("flat", "rising")]
    assert MATRIX[("rising", "rising")].startswith("Accelerating")
