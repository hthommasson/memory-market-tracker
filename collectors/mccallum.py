"""One-time context ingestion (spec §3.6): McCallum long-run memory price series ($/MB, 1957->).
v0.4.2: fetch with a browser User-Agent (site 403s Python's default UA)."""
import io, os
import requests
import pandas as pd
from collectors.common import log, warn

OUT = "docs/data/static/mccallum.csv"
URL = "https://jcmit.net/memoryprice.htm"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

def main():
    if os.path.exists(OUT):
        log("mccallum.csv already present — skipping"); return
    try:
        r = requests.get(URL, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
        big = max(tables, key=len)
        big.to_csv(OUT, index=False)
        log(f"mccallum context saved: {len(big)} rows")
    except Exception as e:
        warn(f"mccallum fetch failed ({e}) — if 403 persists from CI, open the page "
             "in a browser once and save the table as docs/data/static/mccallum.csv manually")

if __name__ == "__main__": main()
