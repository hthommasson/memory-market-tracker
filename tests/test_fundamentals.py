"""Offline verification of the Memory Inc. data layer with synthetic API fixtures."""
import csv, io, json, os, sys, types, zipfile
import datetime as dt
import pytest


class FakeResp:
    def __init__(self, payload, binary=False):
        self._p, self._b = payload, binary
    def raise_for_status(self): pass
    def json(self): return self._p
    @property
    def content(self): return self._p


def write_facts(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period_end", "cik", "ticker", "concept", "value"])
        w.writerows(rows)


def q_entry(start, end, val):
    return {"start": start, "end": end, "val": val, "form": "10-Q"}


def test_sec_multifiler_surgical_refresh(tmp_path, monkeypatch):
    from collectors import sec_facts
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "t@example.com")
    write_facts("docs/data/filings_facts.csv", [
        ["2026-03-31", "manual", "SAMSUNG_MEM", "revenue_krw", "27000000000000"],
        ["2026-03-31", "dart:00164779", "SKHYNIX", "revenue_usd", "13000000000"]])
    tickers = {"0": {"ticker": "MU", "cik_str": 723125},
               "1": {"ticker": "SNDK", "cik_str": 1234}}
    mu = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            q_entry("2025-11-29", "2026-02-26", 8_000_000_000)]}},
        "GrossProfit": {"units": {"USD": [q_entry("2025-11-29", "2026-02-26", 4_000_000_000)]}},
        "CostOfGoodsAndServicesSold": {"units": {"USD": [
            q_entry("2025-11-29", "2026-02-26", 4_000_000_000)]}},
        "InventoryNet": {"units": {"USD": [{"end": "2026-02-26", "val": 9_000_000_000, "form": "10-Q"}]}}}}}
    sndk = {"facts": {"us-gaap": {   # no GrossProfit tag -> exercises rev-cogs fallback
        "Revenues": {"units": {"USD": [q_entry("2026-01-01", "2026-03-31", 2_000_000_000)]}},
        "CostOfRevenue": {"units": {"USD": [q_entry("2026-01-01", "2026-03-31", 1_500_000_000)]}},
        "InventoryNet": {"units": {"USD": [{"end": "2026-03-31", "val": 3_000_000_000, "form": "10-Q"}]}}}}}
    def fake_get(url, **kw):
        if "company_tickers" in url: return FakeResp(tickers)
        if "0000723125" in url: return FakeResp(mu)
        if "0000001234" in url: return FakeResp(sndk)
        raise AssertionError("unexpected URL " + url)
    monkeypatch.setattr(sec_facts.requests, "get", fake_get)
    sec_facts.main()
    rows = list(csv.DictReader(open("docs/data/filings_facts.csv")))
    tickers_seen = {r["ticker"] for r in rows}
    assert {"SAMSUNG_MEM", "SKHYNIX", "MU", "SNDK"} <= tickers_seen   # surgical: preserved
    mu_gm = [r for r in rows if r["ticker"] == "MU" and r["concept"] == "gross_margin_pct"]
    assert float(mu_gm[0]["value"]) == 50.0
    sndk_gm = [r for r in rows if r["ticker"] == "SNDK" and r["concept"] == "gross_margin_pct"]
    assert float(sndk_gm[0]["value"]) == 25.0                          # derived fallback
    mu_inv = [r for r in rows if r["ticker"] == "MU" and r["concept"] == "inventory_days"]
    assert abs(float(mu_inv[0]["value"]) - 91.25 * 9 / 4) < 0.11


def test_dart_cumulative_differencing_and_fx(tmp_path, monkeypatch):
    import pandas as pd
    fake_yf = types.ModuleType("yfinance")
    idx = pd.date_range("2025-01-02", "2025-06-30", freq="D")
    rates = pd.Series([1300.0 if d.quarter == 1 else 1400.0 for d in idx], index=idx)
    class T:
        def __init__(self, *_): pass
        def history(self, **kw): return pd.DataFrame({"Close": rates})
    fake_yf.Ticker = T
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    from collectors import dart_facts
    monkeypatch.setattr(dart_facts, "DART_BACKFILL_START_YEAR", 2025)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DART_API_KEY", "k")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", "<result><list><corp_code>00164779</corp_code>"
                   "<corp_name>SK</corp_name><stock_code>000660</stock_code></list></result>")
    q1 = {"status": "000", "list": [
        {"sj_div": "CIS", "account_id": "ifrs-full_Revenue", "account_nm": "수익(매출액)",
         "thstrm_amount": "100", "thstrm_add_amount": "100"},
        {"sj_div": "CIS", "account_id": "ifrs-full_CostOfSales", "account_nm": "매출원가",
         "thstrm_amount": "60", "thstrm_add_amount": "60"},
        {"sj_div": "BS", "account_id": "ifrs-full_Inventories", "account_nm": "재고자산",
         "thstrm_amount": "500"}]}
    h1 = {"status": "000", "list": [
        {"sj_div": "CIS", "account_id": "", "account_nm": "수익(매출액)",   # name fallback path
         "thstrm_amount": "120", "thstrm_add_amount": "220"},
        {"sj_div": "CIS", "account_id": "ifrs-full_CostOfSales", "account_nm": "매출원가",
         "thstrm_amount": "70", "thstrm_add_amount": "130"},
        {"sj_div": "BS", "account_id": "ifrs-full_Inventories", "account_nm": "재고자산",
         "thstrm_amount": "520"}]}
    def fake_get(url, params=None, **kw):
        if "corpCode" in url: return FakeResp(buf.getvalue(), binary=True)
        if params["reprt_code"] == "11013": return FakeResp(q1)
        if params["reprt_code"] == "11012": return FakeResp(h1)
        return FakeResp({"status": "013"})
    monkeypatch.setattr(dart_facts.requests, "get", fake_get)
    dart_facts.main()
    rows = list(csv.DictReader(open("docs/data/filings_facts.csv")))
    get = lambda c, e: float([r for r in rows if r["concept"] == c and r["period_end"] == e][0]["value"])
    assert get("revenue_krw", "2025-06-30") == 120.0            # 220 cumulative - 100 Q1
    assert get("cogs_krw", "2025-06-30") == 70.0
    assert abs(get("gross_margin_pct", "2025-06-30") - 100 * 50 / 120) < 0.01
    assert abs(get("inventory_days", "2025-06-30") - 91.25 * 520 / 70) < 0.11
    assert abs(get("revenue_usd", "2025-03-31") - 100 / 1300) < 0.01 or get("revenue_usd", "2025-03-31") == 0.0


def test_memory_inc_bucketing_and_aggregate(tmp_path, monkeypatch):
    from engine import memory_inc
    lab, q = memory_inc.bucket("2026-02-26")
    assert lab == "2026Q1" and q == dt.date(2026, 3, 31)
    assert memory_inc.bucket("2026-01-02")[0] == "2025Q4"
    monkeypatch.chdir(tmp_path)
    B = 1e9
    write_facts("docs/data/filings_facts.csv", [
        # prior quarter (worse gm, higher inv days) for breadth
        ["2025-11-27", "c1", "MU", "revenue", 6 * B], ["2025-11-27", "c1", "MU", "cogs", 4 * B],
        ["2025-11-27", "c1", "MU", "inventory", 10 * B],
        ["2025-12-31", "d", "SKHYNIX", "revenue_usd", 10 * B],
        ["2025-12-31", "d", "SKHYNIX", "cogs_usd", 6 * B],
        ["2025-12-31", "d", "SKHYNIX", "inventory_usd", 11 * B],
        # current quarter
        ["2026-02-26", "c1", "MU", "revenue", 8 * B], ["2026-02-26", "c1", "MU", "cogs", 4 * B],
        ["2026-02-26", "c1", "MU", "inventory", 9 * B],
        ["2026-03-31", "d", "SKHYNIX", "revenue_usd", 13 * B],
        ["2026-03-31", "d", "SKHYNIX", "cogs_usd", 6 * B],
        ["2026-03-31", "d", "SKHYNIX", "inventory_usd", 10 * B],
        ["2026-03-31", "d", "SKHYNIX", "fx_krwusd_avg", 1350],
        ["2026-03-31", "manual", "SAMSUNG_MEM", "revenue_krw", 27000 * B]])
    memory_inc.main()
    out = list(csv.DictReader(open("docs/data/memory_inc.csv")))
    row = lambda m, q_: [r for r in out if r["metric"] == m and r["quarter"] == q_][0]
    rev = row("revenue_usd_bn", "2026Q1")
    assert abs(float(rev["value"]) - (8 + 13 + 27000 / 1350)) < 0.01
    assert set(rev["members"].split("|")) == {"MU", "SKHYNIX", "SAMSUNG_MEM"}
    gm = row("gross_margin_pct", "2026Q1")
    assert abs(float(gm["value"]) - 100 * (4 + 7) / 21) < 0.01
    assert "SAMSUNG_MEM" not in gm["members"]                    # ratios stay ex-Samsung
    inv = row("inventory_days", "2026Q1")
    assert abs(float(inv["value"]) - 91.25 * 19 / 10) < 0.11
    br = row("breadth_improving", "2026Q1")
    assert float(br["value"]) == 2.0                             # both improved q/q


def test_sec_fq4_synthesis(tmp_path, monkeypatch):
    from collectors import sec_facts
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "t@example.com")
    monkeypatch.setattr(sec_facts, "EDGAR_FILERS", ["MU"])
    tickers = {"0": {"ticker": "MU", "cik_str": 723125}}
    B = 1_000_000_000
    def qe(s, e, v): return {"start": s, "end": e, "val": v, "form": "10-Q"}
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            qe("2024-08-30", "2024-11-28", 10 * B), qe("2024-11-29", "2025-02-27", 12 * B),
            qe("2025-02-28", "2025-05-29", 14 * B),
            {"start": "2024-08-30", "end": "2025-08-28", "val": 50 * B, "form": "10-K"}]}},
        "CostOfGoodsAndServicesSold": {"units": {"USD": [
            qe("2024-08-30", "2024-11-28", 6 * B), qe("2024-11-29", "2025-02-27", 6 * B),
            qe("2025-02-28", "2025-05-29", 6 * B),
            {"start": "2024-08-30", "end": "2025-08-28", "val": 26 * B, "form": "10-K"}]}},
        "InventoryNet": {"units": {"USD": [
            {"end": "2025-08-28", "val": 8 * B, "form": "10-K"}]}}}}}
    def fake_get(url, **kw):
        return FakeResp(tickers if "company_tickers" in url else facts)
    monkeypatch.setattr(sec_facts.requests, "get", fake_get)
    sec_facts.main()
    rows = list(csv.DictReader(open("docs/data/filings_facts.csv")))
    get = lambda c: [r for r in rows if r["concept"] == c and r["period_end"] == "2025-08-28"]
    assert float(get("revenue")[0]["value"]) == 14 * B          # 50 - (10+12+14)
    assert float(get("cogs")[0]["value"]) == 8 * B              # 26 - 18
    assert abs(float(get("gross_margin_pct")[0]["value"]) - 100 * 6 / 14) < 0.01
    assert abs(float(get("inventory_days")[0]["value"]) - 91.25 * 8 / 8) < 0.11


def test_fred_append_only_and_idempotent(tmp_path, monkeypatch):
    from collectors import fred_series
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setattr(fred_series, "FRED_SERIES", {"TEST1": "us_test_metric"})
    os.makedirs("docs/data", exist_ok=True)
    with open("docs/data/monthly_series.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["period","source","metric","value","value_wda","meta"])
        w.writerow(["2026-05","manual","kr_exports_semis_usd","44820000000","","yoy=+199.5%"])
    payload = {"observations": [
        {"date": "2026-03-01", "value": "150.2"},
        {"date": "2026-04-01", "value": "."},
        {"date": "2026-05-01", "value": "161.7"}]}
    monkeypatch.setattr(fred_series.requests, "get", lambda *a, **k: FakeResp(payload))
    fred_series.main(); fred_series.main()          # second run must add nothing
    rows = list(csv.DictReader(open("docs/data/monthly_series.csv")))
    fred = [r for r in rows if r["source"] == "fred"]
    assert len(fred) == 2                            # "." skipped, no duplicates
    assert [r for r in rows if r["source"] == "manual"]   # manual row untouched
    assert fred[0]["meta"] == "fred:TEST1"


def test_capex_cumulative_differencing_edgar(tmp_path, monkeypatch):
    from collectors import sec_facts
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "t@example.com")
    monkeypatch.setattr(sec_facts, "EDGAR_FILERS", ["MU"])
    B = 1_000_000_000
    def cf(s, e, v, form="10-Q"): return {"start": s, "end": e, "val": v, "form": form}
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"start": "2025-08-30", "end": "2025-11-28", "val": 10 * B, "form": "10-Q"}]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            cf("2025-08-30", "2025-11-28", 3 * B),          # Q1 YTD
            cf("2025-08-30", "2026-02-27", 7 * B),          # H1 YTD -> Q2 = 4
            cf("2025-08-30", "2026-05-29", 12 * B),         # 9M  -> Q3 = 5
            cf("2025-08-30", "2026-08-28", 18 * B, "10-K")]}}}}}  # FY -> Q4 = 6
    monkeypatch.setattr(sec_facts.requests, "get", lambda url, **k: FakeResp(
        {"0": {"ticker": "MU", "cik_str": 723125}} if "company_tickers" in url else facts))
    sec_facts.main()
    rows = list(csv.DictReader(open("docs/data/filings_facts.csv")))
    cap = {r["period_end"]: float(r["value"]) for r in rows if r["concept"] == "capex"}
    assert cap == {"2025-11-28": 3 * B, "2026-02-27": 4 * B,
                   "2026-05-29": 5 * B, "2026-08-28": 6 * B}
    pct = [r for r in rows if r["concept"] == "capex_pct_revenue"]
    assert len(pct) == 1 and float(pct[0]["value"]) == 30.0    # 3/10 where revenue exists
