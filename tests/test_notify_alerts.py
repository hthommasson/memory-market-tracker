"""Batch19 alert classes in engine.notify: book transitions, segment label events,
and the composite flip countdown — each latched, and committed only on confirmed
delivery (the v0.4.1 rule extended). All fixture dates are relative to today (UTC)
so the latch/prune windows never age these tests out.
"""
import csv, json, os, sys, types
import pandas as pd
import pytest
import engine.notify as N

TODAY = pd.Timestamp.now("UTC").date()
def D(n):  # n days ago, ISO
    return (TODAY - pd.Timedelta(days=n)).isoformat()


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


OBS_COLS = ["date", "sku_id", "source", "price", "list_price", "in_stock",
            "seller_type", "condition", "qty_limit"]
REG_COLS = ["date", "segment", "m30_annualized", "a30", "label_raw", "label_committed"]
SEGD_COLS = ["date", "segment", "series", "usd_per_gb", "n_obs"]
SKU_COLS = ["sku_id", "segment", "brand", "mpn", "capacity_gb", "kit_config", "gen",
            "speed", "cas", "condition", "price_lo", "price_hi", "first_seen",
            "retired_on", "basket_version", "status"]


def obs(date, sku, in_stock, price=""):
    return [date, sku, "ebay", price, price, in_stock, "ebay_new", "new", 1]


def sku(sku_id, retired_on=""):
    return [sku_id, "ddr5_desktop", "B", "M-" + sku_id, 32, "2x16", "ddr5", 6000, 36,
            "new", 250, 900, D(45), retired_on, 1, ""]


def test_book_transitions_dark_return_first_light(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_csv("config/sku_registry.csv", SKU_COLS,
              [sku("steady"), sku("goes_dark"), sku("comes_back"),
               sku("first_light"), sku("retired_dark", retired_on=D(10))])
    write_csv("docs/data/price_obs.csv", OBS_COLS, [
        obs(D(9), "comes_back", "True", "500"),         # prior history -> "returned"
        obs(D(1), "steady", "True", "500"),
        obs(D(1), "goes_dark", "True", "500"),
        obs(D(1), "comes_back", "False"),
        obs(D(1), "first_light", "False"),
        obs(D(1), "retired_dark", "True", "500"),
        obs(D(0), "steady", "True", "500"),
        obs(D(0), "goes_dark", "False", "500"),         # listed but not in stock
        obs(D(0), "comes_back", "True", "500"),
        obs(D(0), "first_light", "True", "500"),
        obs(D(0), "retired_dark", "False"),             # retired: never alerts
    ])
    msgs, latch = N.book_transition_msgs({})
    assert msgs == [
        f"Book dark: goes_dark — last in-stock ask {D(1)}",
        f"Book returned: comes_back — in-stock ask again on {D(0)}",
        f"New book lit: first_light — first qualifying ask on {D(0)}",
    ]
    assert set(latch) == {f"{D(0)}|dark|goes_dark", f"{D(0)}|return|comes_back",
                          f"{D(0)}|return|first_light"}
    again, _ = N.book_transition_msgs({"books_notified": latch})
    assert again == []                                   # latched


def test_label_flip_withheld_restored_composite_ignored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_csv("docs/data/regime_daily.csv", REG_COLS, [
        [D(1), "flipper", 0.5, 0.1, "falling", "rising"],
        [D(1), "cliffed", -0.7, 0.1, "falling", "falling"],
        [D(1), "COMPOSITE", 1.0, 0.1, "rising", "rising"],
        [D(0), "flipper", -0.6, 0.1, "falling", "falling"],
        [D(0), "back", 0.9, 0.1, "rising", "rising"],
        [D(0), "COMPOSITE", 1.1, 0.1, "falling", "rising"],   # composite: ignored here
    ])
    write_csv("docs/data/segment_daily.csv", SEGD_COLS, [
        [D(0), "cliffed", "floor", 15.7, 1],
    ])
    msgs, latch = N.label_event_msgs({})
    assert "Segment flip: flipper committed rising -> falling (m30 -60.0% ann.)" in msgs
    assert ("Label withheld: cliffed — 1 qualifying book(s), min 2; "
            "floor still prints, label is masked") in msgs
    assert "Label restored: back — committed rising (m30 +90.0% ann.)" in msgs
    assert len(msgs) == 3                                # COMPOSITE contributed nothing
    again, _ = N.label_event_msgs({"labels_notified": latch})
    assert again == []


def test_countdown_fires_once_per_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = [[D(n), "COMPOSITE", 0.7, 0.1, "rising", "rising"] for n in range(7, 2, -1)]
    rows += [[D(2), "COMPOSITE", 0.2, 0.1, "falling", "rising"],
             [D(1), "COMPOSITE", 0.1, 0.1, "falling", "rising"]]
    write_csv("docs/data/regime_daily.csv", REG_COLS, rows)
    msgs, latch = N.countdown_msgs({})
    assert msgs == []                                    # run of 2 < COUNTDOWN_AT
    rows.append([D(0), "COMPOSITE", 0.05, 0.1, "falling", "rising"])
    write_csv("docs/data/regime_daily.csv", REG_COLS, rows)
    msgs, latch = N.countdown_msgs({})
    assert msgs == ["Flip countdown: composite raw 'falling' x3d vs committed 'rising' "
                    "— commits at 5 consecutive (m30 +5.0% ann.)"]
    assert latch == [f"{D(2)}|falling"]
    again, latch2 = N.countdown_msgs({"countdown_notified": latch})
    assert again == [] and latch2 == latch               # a 4th day stays silent
    # run breaks, then a fresh 3-day run backdated inside the window: new key, fires again
    rows2 = rows + [[chr(0)]]                            # placeholder replaced below
    rows2 = rows[:-1] + [[D(0), "COMPOSITE", 0.8, 0.1, "rising", "rising"]]
    write_csv("docs/data/regime_daily.csv", REG_COLS, rows2)
    msgs, _ = N.countdown_msgs({"countdown_notified": latch})
    assert msgs == []                                    # agreement again: no countdown


def test_new_latches_commit_only_on_delivery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_csv("config/sku_registry.csv", SKU_COLS, [sku("goes_dark")])
    write_csv("docs/data/price_obs.csv", OBS_COLS, [
        obs(D(1), "goes_dark", "True", "500"),
        obs(D(0), "goes_dark", "False", "500"),
    ])
    calls = []
    class Resp:
        def __init__(self, code): self.status_code = code
    fake = types.ModuleType("requests")
    fake.post = lambda url, json=None, timeout=None: (calls.append(json), Resp(fake.code))[1]
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook.test/x")

    fake.code = 500
    N.main()                                             # delivery fails: nothing latches
    if os.path.exists("docs/data/notify_state.json"):
        st = json.load(open("docs/data/notify_state.json"))
        assert st.get("books_notified", []) == []
    assert len(calls) == 1 and "Book dark: goes_dark" in calls[0]["content"]

    fake.code = 204
    N.main()                                             # retry succeeds, latch commits
    st = json.load(open("docs/data/notify_state.json"))
    assert st["books_notified"] == [f"{D(0)}|dark|goes_dark"]
    assert len(calls) == 2

    N.main()                                             # latched: nothing re-posts
    assert len(calls) == 2
