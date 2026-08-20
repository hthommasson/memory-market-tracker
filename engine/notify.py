"""Optional alerting (spec §6): fires on composite-cell change or new divergence flags.
Posts to Discord if DISCORD_WEBHOOK_URL is set; otherwise logs. State persists in-repo.

v0.4.4 (batch19) adds three alert classes, all latched and delivery-confirmed like v0.4.1:
  books_notified      'date|dark/return|sku'   — a qualifying book going dark, returning,
                                                 or lighting for the first time
  labels_notified     'date|segment|event'     — committed-label flips, label withheld at
                                                 the MIN_BOOKS cliff, label restored
  countdown_notified  'runstart|rawlabel'      — composite raw label has disagreed with
                                                 the committed label for >= COUNTDOWN_AT
                                                 consecutive days (flip commits at
                                                 HYSTERESIS_DAYS); fires once per run
COMPOSITE is excluded from the flip class — its flips surface as cell changes already.
"""
import json, os
import pandas as pd
from collectors.common import log, warn, env
from config.settings import DATA_DIR, MIN_BOOKS_FOR_LABEL, HYSTERESIS_DAYS

COMP = f"{DATA_DIR}/composite_regime.csv"
FLAGS = f"{DATA_DIR}/divergence_flags.csv"
OBS = f"{DATA_DIR}/price_obs.csv"
REG = f"{DATA_DIR}/regime_daily.csv"
SEG = f"{DATA_DIR}/segment_daily.csv"
REGISTRY = "config/sku_registry.csv"
STATE = f"{DATA_DIR}/notify_state.json"
FLAG_LATCH_DAYS = 3   # how long a notified (date, flag) key is remembered
COUNTDOWN_AT = 3      # raw-run length that arms the flip-countdown alert
COUNTDOWN_KEEP_DAYS = 14

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}

def save_state(state):
    json.dump(state, open(STATE, "w"))

def _prune(keys, cutoff):
    return sorted(k for k in keys if k.split("|")[0] >= cutoff)

def book_transition_msgs(state):
    """Book dark/return transitions between the two most recent observation dates.

    A book is 'qualifying' when in_stock is True with a positive ask (mirrors the
    engine's floor filter). Retired registry rows never alert. Returns (msgs, latch)
    where latch is the pruned books_notified list — the caller commits it only after
    confirmed delivery.
    """
    cutoff = (pd.Timestamp.now("UTC").date() - pd.Timedelta(days=FLAG_LATCH_DAYS)).isoformat()
    notified = set(state.get("books_notified", []))
    if not os.path.exists(OBS):
        return [], _prune(notified, cutoff)
    obs = pd.read_csv(OBS)
    if obs.empty:
        return [], _prune(notified, cutoff)
    obs["date"] = obs["date"].astype(str)
    obs["qual"] = ((obs["in_stock"].astype(str) == "True")
                   & (pd.to_numeric(obs["price"], errors="coerce") > 0))
    dates = sorted(obs["date"].unique())
    if len(dates) < 2:
        return [], _prune(notified, cutoff)
    d1, d0 = dates[-1], dates[-2]
    qual_on = lambda d: set(obs[(obs["date"] == d) & obs["qual"]]["sku_id"])
    q1, q0 = qual_on(d1), qual_on(d0)
    prior = set(obs[(obs["date"] < d1) & obs["qual"]]["sku_id"])
    retired = set()
    if os.path.exists(REGISTRY):
        reg = pd.read_csv(REGISTRY)
        retired = set(reg[reg["retired_on"].fillna("") != ""]["sku_id"])
    msgs = []
    for sku in sorted(q0 - q1 - retired):
        key = f"{d1}|dark|{sku}"
        if key in notified: continue
        msgs.append(f"Book dark: {sku} — last in-stock ask {d0}")
        notified.add(key)
    for sku in sorted(q1 - q0 - retired):
        key = f"{d1}|return|{sku}"
        if key in notified: continue
        msgs.append(f"New book lit: {sku} — first qualifying ask on {d1}" if sku not in prior
                    else f"Book returned: {sku} — in-stock ask again on {d1}")
        notified.add(key)
    return msgs, _prune(notified, cutoff)

def _m30_txt(row):
    try:
        v = float(row.get("m30_annualized"))
        return f" (m30 {100*v:+.1f}% ann.)"
    except (TypeError, ValueError):
        return ""

def label_event_msgs(state):
    """Committed-label flips, label-withheld (segment drops below MIN_BOOKS and the
    engine stops writing its regime row), and label-restored — per segment, between
    the two most recent regime dates. Returns (msgs, latch) like the book class.
    """
    cutoff = (pd.Timestamp.now("UTC").date() - pd.Timedelta(days=FLAG_LATCH_DAYS)).isoformat()
    notified = set(state.get("labels_notified", []))
    if not os.path.exists(REG):
        return [], _prune(notified, cutoff)
    reg = pd.read_csv(REG)
    reg = reg[reg["segment"].astype(str) != "COMPOSITE"]
    if reg.empty:
        return [], _prune(notified, cutoff)
    reg["date"] = reg["date"].astype(str)
    dates = sorted(reg["date"].unique())
    if len(dates) < 2:
        return [], _prune(notified, cutoff)
    d1, d0 = dates[-1], dates[-2]
    at = lambda d: {r["segment"]: r for _, r in reg[reg["date"] == d].iterrows()}
    r1, r0 = at(d1), at(d0)
    n_obs = {}
    if os.path.exists(SEG):
        sd = pd.read_csv(SEG)
        fl = sd[(sd["series"].astype(str) == "floor") & (sd["date"].astype(str) == d1)]
        n_obs = {r["segment"]: r.get("n_obs") for _, r in fl.iterrows()}
    msgs = []
    def add(seg, event, msg):
        key = f"{d1}|{seg}|{event}"
        if key not in notified:
            msgs.append(msg); notified.add(key)
    for seg in sorted(set(r0) | set(r1)):
        a, b = r0.get(seg), r1.get(seg)
        if a is not None and b is not None:
            if str(a["label_committed"]) != str(b["label_committed"]):
                add(seg, "flip", f"Segment flip: {seg} committed "
                    f"{a['label_committed']} -> {b['label_committed']}{_m30_txt(b)}")
        elif a is not None and b is None:
            try: n = int(float(n_obs.get(seg)))
            except (TypeError, ValueError): n = "?"
            add(seg, "withheld", f"Label withheld: {seg} — {n} qualifying book(s), "
                f"min {MIN_BOOKS_FOR_LABEL}; floor still prints, label is masked")
        elif a is None and b is not None:
            add(seg, "restored",
                f"Label restored: {seg} — committed {b['label_committed']}{_m30_txt(b)}")
    return msgs, _prune(notified, cutoff)

def countdown_msgs(state):
    """Flip countdown for COMPOSITE: fires once per divergent run when the raw label
    has disagreed with the committed label for >= COUNTDOWN_AT consecutive days.
    Keyed 'runstart|rawlabel' so a broken-and-restarted run can alert again.
    """
    keep = (pd.Timestamp.now("UTC").date() - pd.Timedelta(days=COUNTDOWN_KEEP_DAYS)).isoformat()
    notified = set(state.get("countdown_notified", []))
    if not os.path.exists(REG):
        return [], _prune(notified, keep)
    reg = pd.read_csv(REG)
    reg = reg[reg["segment"].astype(str) == "COMPOSITE"].copy()
    if reg.empty:
        return [], _prune(notified, keep)
    reg["date"] = reg["date"].astype(str)
    reg = reg.sort_values("date").reset_index(drop=True)
    last = reg.iloc[-1]
    raw, com = str(last["label_raw"]), str(last["label_committed"])
    msgs = []
    if raw != com and raw != "warming_up":
        run = 0
        for i in range(len(reg) - 1, -1, -1):
            if str(reg.iloc[i]["label_raw"]) == raw: run += 1
            else: break
        if run >= COUNTDOWN_AT:
            runstart = reg.iloc[len(reg) - run]["date"]
            key = f"{runstart}|{raw}"
            if key not in notified:
                msgs.append(f"Flip countdown: composite raw '{raw}' x{run}d vs committed "
                            f"'{com}' — commits at {HYSTERESIS_DAYS} consecutive{_m30_txt(last)}")
                notified.add(key)
    return msgs, _prune(notified, keep)

def main():
    """v0.4.1, two fixes:

    1. Flags are latched like the cell. Previously every run re-posted every row dated
       today, so the second redundant cron (23:29 UTC) re-pinged D1 — compounding with the
       duplicate rows the old append-only divergence writer left behind. Keyed on
       (date, flag), not detail, so a refreshed close/m30 within a day does not re-fire.
    2. State commits only after confirmed delivery. Previously the cell was latched even
       when the POST raised, so a dropped webhook silently consumed the alert and never
       retried — which is why the Aug 3 first-cell ping is unverifiable after the fact.
       A failed send now leaves state untouched and retries on the next run, and
       last_notified_utc records the delivery for later audit.

    v0.4.4: three new latched classes (books, labels, countdown) join the same single
    post and the same delivery-confirmed commit.
    """
    msgs = []
    state = load_state()
    pending = dict(state)
    if os.path.exists(COMP):
        cell = pd.read_csv(COMP)["cell"].iloc[-1]
        if cell != state.get("cell"):
            msgs.append(f"Regime cell changed: {state.get('cell','(first run)')} -> {cell}")
            pending["cell"] = cell
    if os.path.exists(FLAGS):
        today = pd.Timestamp.now("UTC").date().isoformat()
        cutoff = (pd.Timestamp.now("UTC").date() - pd.Timedelta(days=FLAG_LATCH_DAYS)).isoformat()
        notified = set(state.get("flags_notified", []))
        try:
            flags = pd.read_csv(FLAGS)
            for _, r in flags[flags["date"].astype(str) == today].iterrows():
                key = f"{r['date']}|{r['flag']}"
                if key in notified: continue
                msgs.append(f"Divergence {r['detail']}")
                notified.add(key)
        except Exception as e:
            warn(f"notify: could not read {FLAGS}: {e}")
        pending["flags_notified"] = sorted(k for k in notified if k.split("|")[0] >= cutoff)
    for fn, key in ((book_transition_msgs, "books_notified"),
                    (label_event_msgs, "labels_notified"),
                    (countdown_msgs, "countdown_notified")):
        try:
            m, latch = fn(state)
            msgs += m
            pending[key] = latch
        except Exception as e:
            warn(f"notify: {fn.__name__} failed: {e} — class skipped this run")
    if not msgs:
        save_state(pending)      # prune-only write; identical bytes when nothing moved
        log("notify: nothing to report"); return
    hook = env("DISCORD_WEBHOOK_URL")
    text = "**memory-market-tracker**\n" + "\n".join(f"- {m}" for m in msgs)
    delivered = False
    if hook:
        import requests
        try:
            resp = requests.post(hook, json={"content": text[:1900]}, timeout=15)
            if resp.status_code < 300:
                delivered = True
                log(f"notify: sent {len(msgs)} item(s) to Discord (HTTP {resp.status_code})")
            else:
                warn(f"notify: Discord returned HTTP {resp.status_code} — will retry next run")
        except Exception as e:
            warn(f"notify failed: {e} — will retry next run")
    else:
        delivered = True          # log-only mode: nothing to fail
        log("notify (no webhook set):\n" + text)
    if delivered:
        pending["last_notified_utc"] = pd.Timestamp.now("UTC").isoformat(timespec="seconds")
        save_state(pending)
    else:
        log("notify: state left unchanged so the alert re-fires next run")

if __name__ == "__main__": main()
