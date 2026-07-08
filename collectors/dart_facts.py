"""Panel B collector — Korean filers via Open DART (spec §3.2 phase-3, promoted 2026-07-05).

Pulls consolidated full statements for DART_ENTITIES (SK hynix: a memory pure-play,
so company-level numbers ARE memory numbers). Extraction keys on IFRS taxonomy tags
with Korean account-name fallbacks — the collector never parses Korean prose.

Korean quarterly reports state income cumulatively (half = 6mo, Q3 = 9mo, annual = FY),
so quarterly flows are derived by DIFFERENCING cumulatives: Q2 = H1-Q1, Q3 = 9M-H1,
Q4 = FY-9M. Balance-sheet items (inventory) are point-in-time — no differencing.

Currency: gross margin % and inventory days are RATIOS — computed in native KRW,
immune to FX by construction. Only levels (revenue, cogs, inventory) are converted,
at the quarterly-average KRW/USD (flows) and period-end (stocks) from yfinance,
with the rates themselves stored as rows for auditability. If FX fetch fails, KRW
values and ratios still publish; USD rows are skipped with a warning.

Requires: DART_API_KEY (free — opendart.fss.or.kr). Surgical refresh: replaces only
rows with cik prefix 'dart:', preserving EDGAR and manual rows.
"""
import csv, io, os, zipfile
import xml.etree.ElementTree as ET
import requests
from collectors.common import append_rows, log, warn, env
from config.settings import DART_ENTITIES, DART_BACKFILL_START_YEAR, FX_TICKER, DATA_DIR

PATH = f"{DATA_DIR}/filings_facts.csv"
HEADER = ["period_end", "cik", "ticker", "concept", "value"]
CORP_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
FS_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
# reprt_code -> (canonical period end MM-DD, cumulative months)
REPRT = {"11013": ("03-31", 3), "11012": ("06-30", 6), "11014": ("09-30", 9), "11011": ("12-31", 12)}
IS_TAGS = {"revenue": ("ifrs-full_Revenue", ("수익(매출액)", "매출액")),
           "cogs": ("ifrs-full_CostOfSales", ("매출원가",))}
BS_TAGS = {"inventory": ("ifrs-full_Inventories", ("재고자산",))}
CF_TAGS = {"capex": ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                     ("유형자산의 취득",))}


def corp_codes(key):
    r = requests.get(CORP_URL, params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml = z.read(z.namelist()[0])
    out = {}
    for el in ET.fromstring(xml).iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        if stock in DART_ENTITIES:
            out[stock] = el.findtext("corp_code").strip()
    return out


def num(s):
    s = (s or "").replace(",", "").strip()
    if s in ("", "-"): return None
    try: return float(s)
    except ValueError: return None


def pick(rows, sj_divs, tag, names):
    """First matching account: IFRS taxonomy id preferred, Korean name fallback."""
    for r in rows:
        if r.get("sj_div") in sj_divs and (r.get("account_id") or "").strip() == tag:
            v = num(r.get("thstrm_add_amount")) if r.get("sj_div") in ("IS", "CIS") else None
            return v if v is not None else num(r.get("thstrm_amount"))
    for r in rows:
        nm = (r.get("account_nm") or "").strip()
        if r.get("sj_div") in sj_divs and any(nm == n or nm.startswith(n) for n in names):
            v = num(r.get("thstrm_add_amount")) if r.get("sj_div") in ("IS", "CIS") else None
            return v if v is not None else num(r.get("thstrm_amount"))
    return None


def fetch_year(key, corp_code, year):
    """-> {period_end: {'rev_cum':x,'cogs_cum':y,'inventory':z}} for one bsns_year."""
    out = {}
    for reprt, (mmdd, _) in REPRT.items():
        r = requests.get(FS_URL, params={"crtfc_key": key, "corp_code": corp_code,
                                         "bsns_year": str(year), "reprt_code": reprt,
                                         "fs_div": "CFS"}, timeout=60)
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "000":  # '013' = no filing yet — normal for future quarters
            continue
        rows = j.get("list", [])
        out[f"{year}-{mmdd}"] = {
            "rev_cum": pick(rows, ("IS", "CIS"), *IS_TAGS["revenue"]),
            "cogs_cum": pick(rows, ("IS", "CIS"), *IS_TAGS["cogs"]),
            "inventory": pick(rows, ("BS",), *BS_TAGS["inventory"]),
            "capex_cum": (lambda c: abs(c) if c is not None else None)(pick(rows, ("CF",), *CF_TAGS["capex"])),
        }
    return out


def quarterly_flows(cum_by_end):
    """Difference cumulative IS figures into per-quarter flows, within each year."""
    flows = {}
    ends = sorted(cum_by_end)
    prev = {}
    for end in ends:
        year = end[:4]
        if prev.get("year") != year:
            prev = {"year": year, "rev": 0.0, "cogs": 0.0, "capex": 0.0}
        c = cum_by_end[end]
        rev_c, cogs_c = c.get("rev_cum"), c.get("cogs_cum")
        if rev_c is None or cogs_c is None:
            prev = {"year": year, "rev": None, "cogs": None, "capex": None}  # chain broken this year
            continue
        if prev["rev"] is None:
            continue
        cap_c = c.get("capex_cum")
        cap_q = (cap_c - prev["capex"]) if (cap_c is not None and prev.get("capex") is not None) else None
        flows[end] = {"revenue": rev_c - prev["rev"], "cogs": cogs_c - prev["cogs"],
                      "inventory": c.get("inventory"), "capex": cap_q}
        prev = {"year": year, "rev": rev_c, "cogs": cogs_c, "capex": cap_c}
    return flows


def fx_series():
    """{'avg': {period_end: rate}, 'eop': {...}} in KRW per USD, or None on failure."""
    try:
        import yfinance as yf
        import pandas as pd
        h = yf.Ticker(FX_TICKER).history(start=f"{DART_BACKFILL_START_YEAR}-01-01")
        if h is None or h.empty: raise RuntimeError("empty FX history")
        close = h["Close"]
        close.index = pd.to_datetime(close.index).tz_localize(None)
        q = close.resample("QE")
        avg, eop = q.mean(), q.last()
        return {"avg": {d.date().isoformat(): float(v) for d, v in avg.items()},
                "eop": {d.date().isoformat(): float(v) for d, v in eop.items()}}
    except Exception as e:
        warn(f"FX fetch failed ({e}) — publishing KRW values and ratios only")
        return None


def main():
    key = env("DART_API_KEY", required=True)
    import datetime as dt
    codes = corp_codes(key)
    fx = fx_series()
    fresh, my_ciks = [], set()
    for stock, label in DART_ENTITIES.items():
        corp = codes.get(stock)
        if not corp:
            warn(f"{label}: stock code {stock} not in DART registry"); continue
        cik = f"dart:{corp}"
        my_ciks.add(cik)
        cum = {}
        for year in range(DART_BACKFILL_START_YEAR, dt.date.today().year + 1):
            try: cum.update(fetch_year(key, corp, year))
            except Exception as e: warn(f"{label} {year}: {e}")
        flows = quarterly_flows(cum)
        for end, f in sorted(flows.items()):
            rev, cogs, inv = f["revenue"], f["cogs"], f["inventory"]
            fresh.append([end, cik, label, "revenue_krw", rev])
            fresh.append([end, cik, label, "cogs_krw", cogs])
            if inv is not None: fresh.append([end, cik, label, "inventory_krw", inv])
            if rev: fresh.append([end, cik, label, "gross_margin_pct",
                                  round(100 * (rev - cogs) / rev, 2)])
            if inv is not None and cogs:
                fresh.append([end, cik, label, "inventory_days", round(91.25 * inv / cogs, 1)])
            cap = f.get("capex")
            if cap is not None:
                fresh.append([end, cik, label, "capex_krw", cap])
                if rev:
                    fresh.append([end, cik, label, "capex_pct_revenue", round(100 * cap / rev, 2)])
            if fx and end in fx["avg"]:
                a, e_ = fx["avg"][end], fx["eop"].get(end, fx["avg"][end])
                fresh.append([end, cik, label, "fx_krwusd_avg", round(a, 2)])
                fresh.append([end, cik, label, "revenue_usd", round(rev / a, 0)])
                fresh.append([end, cik, label, "cogs_usd", round(cogs / a, 0)])
                if inv is not None:
                    fresh.append([end, cik, label, "inventory_usd", round(inv / e_, 0)])
                if f.get("capex") is not None:
                    fresh.append([end, cik, label, "capex_usd", round(f["capex"] / a, 0)])
        log(f"{label}: {len([r for r in fresh if r[1] == cik])} rows from {len(flows)} quarters")
    if not fresh:
        warn("no DART data collected — leaving filings_facts.csv untouched"); return
    keep = []
    if os.path.exists(PATH):
        with open(PATH) as f: keep = [r for r in csv.reader(f)][1:]
        keep = [r for r in keep if r and r[1] not in my_ciks]
        os.remove(PATH)
    append_rows(PATH, HEADER, keep + fresh)
    log(f"filings_facts rebuilt: {len(fresh)} DART rows + {len(keep)} preserved (EDGAR/manual)")


if __name__ == "__main__": main()
