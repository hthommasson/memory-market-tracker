"""Panel D collector: US memory-IC imports by origin — value, quantity, air share (spec §3.4).
Runs monthly. Variable-name fallback built in: if quantity/transport variables 400,
retries value-only and warns (verify names at /variables.html — spec build-time TODO)."""
import datetime, requests
from collectors.common import append_rows, log, warn, env
from config.settings import DATA_DIR

PATH = f"{DATA_DIR}/monthly_series.csv"
HEADER = ["period", "source", "metric", "value", "value_wda", "meta"]
BASE = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
HS = "854232"  # electronic ICs: memories

def target_period():
    d = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
    d = d.replace(day=1) - datetime.timedelta(days=1)  # two full months back = safely published
    return d.strftime("%Y-%m")

def call(key, get_vars, period):
    r = requests.get(BASE, params={"get": get_vars, "I_COMMODITY": HS, "time": period, "key": key}, timeout=60)
    if r.status_code != 200: return None, r.status_code
    return r.json(), 200

def main():
    key = env("CENSUS_API_KEY", required=True)
    period = target_period()
    data, code = call(key, "CTY_CODE,CTY_NAME,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1", period)
    if data is None:
        warn(f"value+quantity call returned {code}; retrying value-only (check variables.html)")
        data, code = call(key, "CTY_CODE,CTY_NAME,GEN_VAL_MO", period)
    if data is None:
        warn(f"census call failed ({code}) for {period}"); return
    header, rows_in = data[0], data[1:]
    idx = {h: i for i, h in enumerate(header)}
    rows = []
    for r in rows_in:
        cty, name, val = r[idx["CTY_CODE"]], r[idx["CTY_NAME"]], r[idx["GEN_VAL_MO"]]
        qty = r[idx["GEN_QY1_MO"]] if "GEN_QY1_MO" in idx else ""
        unit = r[idx["UNIT_QY1"]] if "UNIT_QY1" in idx else ""
        rows.append([period, "census", f"us_imports_memory_value:{cty}", val, "", name])
        if qty not in ("", "0", None):
            rows.append([period, "census", f"us_imports_memory_qty:{cty}", qty, "", f"{name}|unit={unit}"])
            try: rows.append([period, "census", f"us_imports_memory_unitvalue:{cty}",
                              round(float(val) / float(qty), 4), "", name])
            except (ValueError, ZeroDivisionError): pass
    air, code = call(key, "CTY_CODE,AIR_VAL_MO,VES_VAL_MO", period)  # air-share attempt (spec v0.2 addition)
    if air:
        aidx = {h: i for i, h in enumerate(air[0])}
        for r in air[1:]:
            try:
                a, v = float(r[aidx["AIR_VAL_MO"]]), float(r[aidx["VES_VAL_MO"]])
                if a + v > 0:
                    rows.append([period, "census", f"us_imports_memory_airshare:{r[aidx['CTY_CODE']]}",
                                 round(a / (a + v), 4), "", ""])
            except (ValueError, KeyError): continue
    else:
        warn("air/vessel variables not accepted — verify names at variables.html")
    append_rows(PATH, HEADER, rows)

if __name__ == "__main__": main()
