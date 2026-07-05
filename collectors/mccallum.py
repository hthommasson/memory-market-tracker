"""One-time context ingestion (spec §3.6): McCallum long-run memory price series ($/MB, 1957->)."""
import os
import pandas as pd
from collectors.common import log, warn

OUT = "docs/data/static/mccallum.csv"
URL = "https://jcmit.net/memoryprice.htm"

def main():
    if os.path.exists(OUT):
        log("mccallum.csv already present — skipping"); return
    try:
        tables = pd.read_html(URL)
        big = max(tables, key=len)
        big.to_csv(OUT, index=False)
        log(f"mccallum context saved: {len(big)} rows")
    except Exception as e:
        warn(f"mccallum fetch failed ({e}) — rerun later; dashboard degrades gracefully without it")

if __name__ == "__main__": main()
