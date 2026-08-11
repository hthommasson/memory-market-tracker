"""Regression tests for the v0.4.1 divergence/notify idempotency fix.

The bug: engine.divergence used collectors.common.append_rows, so every run appended a
fresh row. Two redundant crons plus ghost runs left 2-4 identical rows per firing day
(divergence_flags.csv had 4 rows for 2026-08-07 alone), and engine.notify re-posted every
row dated today on every run.
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.divergence import upsert_rows

HEADER = ["date", "flag", "detail"]


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_upsert_creates_file_with_header(tmp_path):
    p = str(tmp_path / "flags.csv")
    upsert_rows(p, HEADER, [["2026-08-08", "D1", "D1: first"]])
    rows = read(p)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-08-08" and rows[0]["flag"] == "D1"


def test_same_day_same_flag_written_twice_stays_one_row(tmp_path):
    """The exact production symptom: two crons on one day must not produce two rows."""
    p = str(tmp_path / "flags.csv")
    upsert_rows(p, HEADER, [["2026-08-08", "D1", "D1: DRAM 20d -12.6% vs physical"]])
    upsert_rows(p, HEADER, [["2026-08-08", "D1", "D1: DRAM 20d -13.2% vs physical"]])
    rows = read(p)
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    assert "-13.2%" in rows[0]["detail"], "latest run should win on detail"


def test_distinct_days_and_flags_both_kept(tmp_path):
    p = str(tmp_path / "flags.csv")
    upsert_rows(p, HEADER, [["2026-08-08", "D1", "a"]])
    upsert_rows(p, HEADER, [["2026-08-09", "D1", "b"]])
    upsert_rows(p, HEADER, [["2026-08-09", "D4", "c"]])
    rows = read(p)
    assert len(rows) == 3
    assert [(r["date"], r["flag"]) for r in rows] == [
        ("2026-08-08", "D1"), ("2026-08-09", "D1"), ("2026-08-09", "D4")], "ledger must stay sorted"


def test_existing_duplicates_on_disk_are_collapsed(tmp_path):
    """Self-heal: the first run after the patch cleans dups the old writer left behind."""
    p = str(tmp_path / "flags.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for detail in ("D1: -12.6%", "D1: -12.6%", "D1: -12.4%", "D1: -12.4%"):
            w.writerow(["2026-08-07", "D1", detail])
        w.writerow(["2026-08-08", "D1", "D1: -13.2%"])
    assert len(read(p)) == 5
    upsert_rows(p, HEADER, [["2026-08-09", "D1", "D1: -13.9%"]])
    rows = read(p)
    assert len(rows) == 3, f"4 dup rows should collapse to 1; got {len(rows)} total"
    assert [r["date"] for r in rows] == ["2026-08-07", "2026-08-08", "2026-08-09"]


def test_notify_latches_flags_and_does_not_repost(tmp_path, monkeypatch):
    """Second cron on the same day must not re-ping an already-notified (date, flag)."""
    import engine.notify as N
    d = tmp_path
    flags = d / "divergence_flags.csv"
    comp = d / "composite_regime.csv"
    state = d / "notify_state.json"
    today = __import__("pandas").Timestamp.now("UTC").date().isoformat()
    with open(flags, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerow([today, "D1", "D1: layers disagree"])
    with open(comp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "price", "volume", "cell"])
        w.writerow([today, "rising", "rising", "Accelerating (broad boom)"])
    monkeypatch.setattr(N, "FLAGS", str(flags))
    monkeypatch.setattr(N, "COMP", str(comp))
    monkeypatch.setattr(N, "STATE", str(state))
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    sent = []
    monkeypatch.setattr(N, "log", lambda m: sent.append(m))
    N.main()
    first = json.load(open(state))
    assert first["cell"] == "Accelerating (broad boom)"
    assert f"{today}|D1" in first["flags_notified"]
    assert any("layers disagree" in m for m in sent), "first run should report the flag"

    sent.clear()
    N.main()
    assert not any("layers disagree" in m for m in sent), "second run must not re-post the flag"
    assert any("nothing to report" in m for m in sent)
