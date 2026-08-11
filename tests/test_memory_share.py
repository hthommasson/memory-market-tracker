"""Amplitude gauge: memory_share_of_semis rows in the Memory Inc. builder (spec §watch).

share = 100 * quarter revenue / (3 x end-month SIA 3mma). The SIA series is a 3-month
moving average, so 3x the quarter-end month equals the true quarter total — these tests
pin the arithmetic, the publish-gate (no row until the quarter-end SIA month exists),
and the row-noise filters in load_sia.
"""
import csv, os
from engine import memory_inc


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_facts(rows):
    write_csv("docs/data/filings_facts.csv",
              ["period_end", "cik", "ticker", "concept", "value"], rows)


def write_monthly(rows):
    write_csv("docs/data/monthly_series.csv",
              ["period", "source", "metric", "value", "value_wda", "meta"], rows)


def test_share_row_math_and_publish_gate():
    sia = {"2026-03": 100e9}
    r = memory_inc.share_row("2026Q1", 120e9, "MU|SKHYNIX", "2/4 members", sia)
    assert r[0] == "2026Q1" and r[1] == "memory_share_of_semis"
    assert abs(r[2] - 40.0) < 1e-9                      # 120 / (3 * 100)
    assert r[3] == "MU|SKHYNIX"
    assert "2/4 members" in r[4] and "2026-03" in r[4]  # coverage + basis carried on the row
    assert memory_inc.share_row("2026Q2", 120e9, "MU", "1/4 members", sia) is None  # month absent
    assert memory_inc.share_row("2026Q1", 120e9, "MU", "1/4 members", {"2026-03": 0}) is None


def test_load_sia_filters_noise(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_monthly([
        ["2026-03", "sia_wsts", "global_semi_sales_usd", 99.5e9, "", "yoy=+79.2%|3mma"],
        ["2025-12", "sia_wsts", "memory_category_sales_usd_annual", 223.1e9, "", "fy2025"],  # wrong metric
        ["2025", "sia_wsts", "global_semi_sales_usd", 791.7e9, "", "annual"],                # not YYYY-MM
        ["2026-04", "sia_wsts", "global_semi_sales_usd", "n/a", "", ""],                     # unparseable
        ["2026-05", "kr_customs", "global_semi_sales_usd", 1e9, "", ""],                     # wrong source
        ["2026-06", "sia_wsts", "global_semi_sales_usd", -5e9, "", ""],                      # non-positive
    ])
    sia = memory_inc.load_sia()
    assert sia == {"2026-03": 99.5e9}


def test_share_rows_land_in_main_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    B = 1e9
    write_facts([
        # 2026Q1: MU 8 + SKHYNIX 13 + SAMSUNG_MEM 27000/1350=20 -> 41bn revenue
        ["2026-02-26", "c1", "MU", "revenue", 8 * B],
        ["2026-03-31", "d", "SKHYNIX", "revenue_usd", 13 * B],
        ["2026-03-31", "d", "SKHYNIX", "fx_krwusd_avg", 1350],
        ["2026-03-31", "manual", "SAMSUNG_MEM", "revenue_krw", 27000 * B],
        # 2026Q2 revenue exists but its SIA end-month does not -> no share row
        ["2026-06-30", "c1", "MU", "revenue", 9 * B],
    ])
    write_monthly([
        ["2026-03", "sia_wsts", "global_semi_sales_usd", 100 * B, "", "3mma"],
    ])
    memory_inc.main()
    out = list(csv.DictReader(open("docs/data/memory_inc.csv")))
    share = [r for r in out if r["metric"] == "memory_share_of_semis"]
    assert len(share) == 1 and share[0]["quarter"] == "2026Q1"
    assert abs(float(share[0]["value"]) - 100 * 41 / 300) < 0.01        # 13.67%
    assert set(share[0]["members"].split("|")) == {"MU", "SKHYNIX", "SAMSUNG_MEM"}
    assert "3/4 members" in share[0]["meta"] and "2026-03" in share[0]["meta"]
    q2 = [r for r in out if r["quarter"] == "2026Q2" and r["metric"] == "memory_share_of_semis"]
    assert q2 == []                                                     # publish-gate holds


def test_main_survives_missing_monthly_series(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    B = 1e9
    write_facts([["2026-02-26", "c1", "MU", "revenue", 8 * B]])
    memory_inc.main()                                   # no monthly_series.csv at all
    out = list(csv.DictReader(open("docs/data/memory_inc.csv")))
    assert [r for r in out if r["metric"] == "revenue_usd_bn"]          # builder still ran
    assert not [r for r in out if r["metric"] == "memory_share_of_semis"]
