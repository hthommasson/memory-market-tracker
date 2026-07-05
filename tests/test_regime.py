import numpy as np
import pandas as pd
from engine.regime import ann_slope, raw_label, committed
from config.settings import THRESH_UP, THRESH_DOWN, HYSTERESIS_DAYS

def test_ann_slope_recovers_growth_rate():
    rate = 0.50 / 365  # +50% annualized
    s = pd.Series(100 * np.exp(rate * np.arange(60)))
    m = ann_slope(s)
    assert abs(m - 0.50) < 0.02

def test_raw_labels():
    assert raw_label(THRESH_UP + 0.05) == "rising"
    assert raw_label(THRESH_DOWN - 0.05) == "falling"
    assert raw_label(0.0) == "flat"
    assert raw_label(None) == "warming_up"

def test_hysteresis_blocks_flapping_and_commits_real_change():
    labels = ["flat"] * 10 + ["falling"] * (HYSTERESIS_DAYS - 1) + ["flat"] * 3 \
             + ["falling"] * HYSTERESIS_DAYS
    out = committed(labels)
    assert out[10 + HYSTERESIS_DAYS - 2] == "flat"      # short falling run: not committed
    assert out[-1] == "falling"                          # sustained run: committed
