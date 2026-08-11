"""Optional alerting (spec §6): fires on composite-cell change or new divergence flags.
Posts to Discord if DISCORD_WEBHOOK_URL is set; otherwise logs. State persists in-repo."""
import json, os
import pandas as pd
from collectors.common import log, warn, env
from config.settings import DATA_DIR

COMP = f"{DATA_DIR}/composite_regime.csv"
FLAGS = f"{DATA_DIR}/divergence_flags.csv"
STATE = f"{DATA_DIR}/notify_state.json"
FLAG_LATCH_DAYS = 3   # how long a notified (date, flag) key is remembered

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}

def save_state(state):
    json.dump(state, open(STATE, "w"))

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
