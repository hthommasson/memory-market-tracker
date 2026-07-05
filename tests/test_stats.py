import numpy as np
import pandas as pd
from engine.stats import lag_corr, month_index, MIN_PAIRS

def make(seed=7, n=30):
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 1, n + 2)
    x = pd.Series(base[2:n+2])                                  # x_t = base_{t+2}
    y = pd.Series(base[:n] * 0.9 + rng.normal(0, 0.25, n))     # y_{t+2} = x_t: x leads y by 2
    idx = pd.period_range("2024-01", periods=n, freq="M")
    x.index = idx; y.index = idx
    return x, y

def test_recovers_known_lead():
    x, y = make()
    results = {lag: lag_corr(x, y, lag) for lag in range(0, 5)}
    best = max(results, key=lambda l: abs(results[l][1] or 0))
    assert best == 2
    assert results[2][1] > 0.6           # strong spearman at true lag
    assert results[2][0] == 28           # n reflects the shift

def test_insufficient_n_gate():
    x, y = make(n=MIN_PAIRS - 1 + 0)     # below the gate after shifting
    n, sp, pe = lag_corr(x.iloc[:4], y.iloc[:4], 0)
    assert sp is None and pe is None and n < MIN_PAIRS

def test_month_index_fills_gaps_with_nan():
    s = pd.Series([1.0, 3.0], index=["2026-01", "2026-04"])
    m = month_index(s)
    assert len(m) == 4 and m.isna().sum() == 2
