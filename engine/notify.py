"""Optional alerting (spec §6): fires on composite-cell change or new divergence flags.
Posts to Discord if DISCORD_WEBHOOK_URL is set; otherwise logs. State persists in-repo."""
import json, os
import pandas as pd
from collectors.common import log, warn, env
from config.settings import DATA_DIR

COMP = f"{DATA_DIR}/composite_regime.csv"
FLAGS = f"{DATA_DIR}/divergence_flags.csv"
STATE = f"{DATA_DIR}/notify_state.json"

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}

def main():
    msgs = []
    state = load_state()
    if os.path.exists(COMP):
        cell = pd.read_csv(COMP)["cell"].iloc[-1]
        if cell != state.get("cell"):
            msgs.append(f"Regime cell changed: {state.get('cell','(first run)')} -> {cell}")
            state["cell"] = cell
    if os.path.exists(FLAGS):
        flags = pd.read_csv(FLAGS)
        today = pd.Timestamp.now("UTC").date().isoformat()
        fired = flags[flags["date"] == today]
        for _, r in fired.iterrows(): msgs.append(f"Divergence {r['detail']}")
    if not msgs:
        log("notify: nothing to report"); return
    hook = env("DISCORD_WEBHOOK_URL")
    text = "**memory-market-tracker**\n" + "\n".join(f"- {m}" for m in msgs)
    if hook:
        import requests
        try:
            requests.post(hook, json={"content": text[:1900]}, timeout=15)
            log(f"notify: sent {len(msgs)} item(s) to Discord")
        except Exception as e:
            warn(f"notify failed: {e}")
    else:
        log("notify (no webhook set):\n" + text)
    json.dump(state, open(STATE, "w"))

if __name__ == "__main__": main()
