"""Panel B collector v2: XBRL company facts for all US memory-complex filers
(spec §3.2, extended 2026-07-05) -> per-filer revenue, gross margin %, inventory days.

CIKs are resolved at runtime from the SEC's official ticker file — nothing hardcoded,
new filers are a one-line settings edit. filings_facts.csv is refreshed SURGICALLY:
this collector replaces only rows for its own CIKs, preserving DART-sourced rows
(cik prefix 'dart:') and manual entries (e.g. SAMSUNG_MEM memory-segment revenue).
"""
import csv, datetime as dt, os
import requests
from collectors.common import append_rows, log, warn, env
from config.settings import EDGAR_FILERS, DATA_DIR

PATH = f"{DATA_DIR}/filings_facts.csv"
HEADER = ["period_end", "cik", "ticker", "concept", "value"]
TICKER_FILE = "https://www.sec.gov/files/company_tickers.json"
CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "gross_profit": ["GrossProfit"],
    "inventory": ["InventoryNet"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue"],
}


def resolve_ciks(headers):
    r = requests.get(TICKER_FILE, headers=headers, timeout=60)
    r.raise_for_status()
    by_ticker = {v["ticker"].upper(): f"{v['cik_str']:010d}" for v in r.json().values()}
    out = {}
    for t in EDGAR_FILERS:
        if t.upper() in by_ticker:
            out[t] = by_ticker[t.upper()]
        else:
            warn(f"{t}: not found in SEC ticker file — skipping")
    return out


def quarterly(facts, names):
    """Quarterly (10-Q/10-K) series for the first concept found; restatements win."""
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


def annual(facts, names):
    """Full-year (10-K) figures for the first concept found, ~52/53-week spans."""
    for name in names:
        node = facts.get("us-gaap", {}).get(name)
        if not node:
            continue
        out = {}
        for unit_rows in node.get("units", {}).values():
            for r in unit_rows:
                if r.get("form") != "10-K" or "start" not in r:
                    continue
                span = (dt.date.fromisoformat(r["end"]) - dt.date.fromisoformat(r["start"])).days
                if 340 <= span <= 380:
                    out[r["end"]] = r["val"]
        if out:
            return out
    return {}


def filer_rows(ticker, cik, headers):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    facts = r.json().get("facts", {})
    series = {k: quarterly(facts, v) for k, v in CONCEPTS.items()}
    # v2.1: synthesize the 10-K-only fiscal Q4 as (annual - three reported quarters).
    # Micron tags full-year income but not a standalone Q4, so its Aug-ending quarter
    # otherwise contributes only balance-sheet rows and calendar-Q3 aggregates sawtooth.
    synth = 0
    for concept in ("revenue", "gross_profit", "cogs"):
        for a_end, a_val in annual(facts, CONCEPTS[concept]).items():
            if a_end in series[concept]:
                continue
            A = dt.date.fromisoformat(a_end)
            qs = [v for e, v in series[concept].items()
                  if 0 < (A - dt.date.fromisoformat(e)).days < 370]
            if len(qs) == 3:
                series[concept][a_end] = a_val - sum(qs)
                synth += 1
    # Gross profit fallback: derive from revenue - cogs where the tag is absent
    for end, rev in series["revenue"].items():
        if end not in series["gross_profit"] and end in series["cogs"]:
            series["gross_profit"][end] = rev - series["cogs"][end]
    rows = []
    for concept, data in series.items():
        for end, val in sorted(data.items()):
            rows.append([end, cik, ticker, concept, val])
    for end in sorted(series["gross_profit"]):
        rev, gp = series["revenue"].get(end), series["gross_profit"].get(end)
        cogs, inv = series["cogs"].get(end), series["inventory"].get(end)
        if rev and gp:
            rows.append([end, cik, ticker, "gross_margin_pct", round(100 * gp / rev, 2)])
        if cogs and inv:
            rows.append([end, cik, ticker, "inventory_days", round(91.25 * inv / cogs, 1)])
    return rows, synth


def main():
    contact = env("SEC_CONTACT_EMAIL", required=True)
    headers = {"User-Agent": f"memory-market-tracker {contact}"}
    ciks = resolve_ciks(headers)
    fresh = []
    for ticker, cik in ciks.items():
        try:
            rows, synth = filer_rows(ticker, cik, headers)
            fresh.extend(rows)
            note = f" (+{synth} synthesized fiscal-Q4 values)" if synth else ""
            log(f"{ticker} (CIK {cik}): {len(rows)} rows{note}")
        except Exception as e:
            warn(f"{ticker}: {e} — other filers unaffected")
    if not fresh:
        warn("no filer data collected — leaving filings_facts.csv untouched")
        return
    # Surgical refresh: replace only this collector's rows (matched by CIK)
    mine = set(ciks.values())
    keep = []
    if os.path.exists(PATH):
        with open(PATH) as f:
            keep = [r for r in csv.reader(f)][1:]
        keep = [r for r in keep if r and r[1] not in mine]
        os.remove(PATH)
    append_rows(PATH, HEADER, keep + fresh)
    log(f"filings_facts rebuilt: {len(fresh)} EDGAR rows + {len(keep)} preserved (DART/manual)")


if __name__ == "__main__": main()
