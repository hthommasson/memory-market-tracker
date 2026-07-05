"""Panel B collector: Micron XBRL company facts -> gross margin %, inventory days (spec §3.2)."""
import requests
from collectors.common import append_rows, log, warn, env
from config.settings import MICRON_CIK, DATA_DIR

PATH = f"{DATA_DIR}/filings_facts.csv"
HEADER = ["period_end", "cik", "ticker", "concept", "value"]
CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "gross_profit": ["GrossProfit"],
    "inventory": ["InventoryNet"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue"],
}

def quarterly(facts, names):
    """Extract quarterly (10-Q/10-K) series for the first concept found; restatements win."""
    import datetime as dt
    for name in names:
        node = facts.get("us-gaap", {}).get(name)
        if not node: continue
        out = {}
        for unit_rows in node.get("units", {}).values():
            for r in unit_rows:
                end, form = r.get("end"), r.get("form", "")
                if form not in ("10-Q", "10-K"): continue
                if "start" in r:
                    span = (dt.date.fromisoformat(end) - dt.date.fromisoformat(r["start"])).days
                    if not 75 <= span <= 100: continue
                out[end] = r["val"]
        if out: return out
    return {}

def main():
    contact = env("SEC_CONTACT_EMAIL", required=True)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{MICRON_CIK}.json"
    r = requests.get(url, headers={"User-Agent": f"memory-market-tracker {contact}"}, timeout=60)
    r.raise_for_status()
    facts = r.json().get("facts", {})
    series = {k: quarterly(facts, v) for k, v in CONCEPTS.items()}
    rows = []
    for concept, data in series.items():
        for end, val in sorted(data.items()):
            rows.append([end, MICRON_CIK, "MU", concept, val])
    for end in sorted(series.get("gross_profit", {})):
        rev, gp = series["revenue"].get(end), series["gross_profit"].get(end)
        cogs, inv = series["cogs"].get(end), series["inventory"].get(end)
        if rev and gp: rows.append([end, MICRON_CIK, "MU", "gross_margin_pct", round(100 * gp / rev, 2)])
        if cogs and inv: rows.append([end, MICRON_CIK, "MU", "inventory_days", round(91.25 * inv / cogs, 1)])
    import os
    if os.path.exists(PATH): os.remove(PATH)  # full-refresh table: restatements make append-only wrong here
    append_rows(PATH, HEADER, rows)

if __name__ == "__main__": main()
