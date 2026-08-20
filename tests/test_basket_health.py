"""Basket health lanes (spec §6 + ack_dark, 2026-08-20).

The weekly workflow opens an issue when any stdout line starts with "- ". These tests
pin the routing: real problems alert, acknowledged dark books ("~ ") never do, retired
books vanish, and fresh candidates get their 7-day grace.
"""
import csv, os
import pytest
from engine import basket_health

REG_COLS = ["sku_id","segment","brand","mpn","capacity_gb","kit_config","gen","speed",
            "cas","condition","price_lo","price_hi","first_seen","retired_on",
            "basket_version","status"]
OBS_COLS = ["date","sku_id","source","price","list_price","in_stock","seller_type",
            "condition","qty_limit"]


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def reg_row(sku, first_seen="2026-07-01", retired_on="", status=""):
    return [sku, "ddr5_desktop", "B", "MPN-" + sku, 32, "2x16", "ddr5", 6000, 36, "new",
            250, 900, first_seen, retired_on, 1, status]


def obs_row(date, sku, in_stock, price=""):
    return [date, sku, "ebay", price, price, in_stock, "ebay_new", "new",
            5 if in_stock == "True" else 0]


def run(capsys):
    basket_health.main()
    return capsys.readouterr().out


def test_problem_vs_ack_routing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_csv("config/sku_registry.csv", REG_COLS, [
        reg_row("fresh_ok"),
        reg_row("dark_alert"),
        reg_row("dark_acked", status="ack_dark"),
    ])
    write_csv("docs/data/price_obs.csv", OBS_COLS, [
        obs_row("2026-08-01", "dark_alert", "True", "500"),
        obs_row("2026-08-01", "dark_acked", "True", "500"),
        obs_row("2026-08-20", "fresh_ok", "True", "500"),
        obs_row("2026-08-20", "dark_alert", "False"),
        obs_row("2026-08-20", "dark_acked", "False"),
    ])
    out = run(capsys)
    alert_lines = [l for l in out.splitlines() if l.startswith("- ")]
    ack_lines = [l for l in out.splitlines() if l.startswith("~ ")]
    assert alert_lines == ["- dark_alert: no qualifying listings for 19 days (last 2026-08-01)"]
    assert ack_lines == ["~ dark_acked: no qualifying listings for 19 days (last 2026-08-01)"]
    assert "fresh_ok" not in out                      # healthy book stays silent


def test_ack_only_dark_does_not_trigger_issue(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_csv("config/sku_registry.csv", REG_COLS, [
        reg_row("ok_book"),
        reg_row("dark_acked", status="ack_dark"),
    ])
    write_csv("docs/data/price_obs.csv", OBS_COLS, [
        obs_row("2026-07-20", "dark_acked", "True", "500"),
        obs_row("2026-08-20", "ok_book", "True", "500"),
        obs_row("2026-08-20", "dark_acked", "False"),
    ])
    out = run(capsys)
    # the workflow greps '^-': zero such lines means no issue gets opened
    assert not [l for l in out.splitlines() if l.startswith("- ")]
    assert "basket healthy (1 acknowledged dark books watching)" in out
    assert "~ dark_acked" in out


def test_retired_excluded_and_candidate_grace(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write_csv("config/sku_registry.csv", REG_COLS, [
        reg_row("ok_book"),
        reg_row("zombie", retired_on="2026-08-20", status="retired_dead_listing"),
        reg_row("cand_new", first_seen="2026-08-17", status="candidate"),   # 3d: grace
        reg_row("cand_stale", first_seen="2026-08-01", status="candidate"), # 19d: flag
    ])
    write_csv("docs/data/price_obs.csv", OBS_COLS, [
        obs_row("2026-08-20", "ok_book", "True", "500"),
        obs_row("2026-08-20", "zombie", "False"),
        obs_row("2026-08-20", "cand_new", "False"),
        obs_row("2026-08-20", "cand_stale", "False"),
    ])
    out = run(capsys)
    assert "zombie" not in out                        # retired: gone entirely
    assert "cand_new" not in out                      # inside the 7-day grace
    assert "- cand_stale: no qualifying listings in the 19 days since added" in out
