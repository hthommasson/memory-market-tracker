"""Panel C collector: daily closes + volume, with historical backfill (spec §3.3)."""
import os, pandas as pd
from collectors.common import append_rows, log, warn
from config.settings import TICKERS, EQUITY_BACKFILL_START, DATA_DIR

PATH = f"{DATA_DIR}/equity_daily.csv"
HEADER = ["date", "ticker", "close", "volume"]

def last_date():
    if not os.path.exists(PATH): return None
    df = pd.read_csv(PATH)
    return None if df.empty else df["date"].max()

def main():
    try:
        import yfinance as yf
    except ImportError:
        warn("yfinance not installed"); return
    start = last_date()
    start = EQUITY_BACKFILL_START if start is None else (pd.Timestamp(start) + pd.Timedelta(days=1)).date().isoformat()
    rows = []
    for t in TICKERS:
        try:
            df = yf.download(t, start=start, progress=False, auto_adjust=False)
            if df is None or df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            for d, r in df.iterrows():
                rows.append([d.date().isoformat(), t, round(float(r["Close"]), 4), int(r.get("Volume", 0) or 0)])
        except Exception as e:
            warn(f"{t}: {e}")  # note: RAM/DRAM listed 2026; earlier dates return empty — expected
    if rows: append_rows(PATH, HEADER, rows)
    else: log("no new equity rows")

if __name__ == "__main__": main()
