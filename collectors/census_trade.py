"""Panel D collector: US memory-IC imports by origin — value, quantity, air share (spec §3.4).

v0.4.1 fixes:
- Month fallback: tries the 3 most recent plausibly-published months; HTTP 204 means
  "not published yet" (per Census docs), so we step back instead of failing.
- Idempotent: skips any period already ingested (safe to re-run the workflow).
- Variable fallback: if quantity/transport variables 400, retries value-only and warns.
"""
import datetime, requests
from collectors.common import append_rows, log, warn, env
from config.settings import DATA_DIR

PATH = f"{DATA_DIR}/monthly_series.csv"
HEADER = ["period", "source", "metric", "value", "value_wda", "meta"]
BASE = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
HS = "854232"  # electronic ICs: memories


def candidate_periods():
    """Most recent 3 months that could plausibly be published (2, 3, 4 months back)."""
    first = datetime.date.today().replace(day=1)
    out = []
    d = first
    for _ in range(4):
        d = (d - datetime.timedelta(days=1)).replace(day=1)
        out.append(d.strftime("%Y-%m"))
    return out[1:]  # skip last month (never published this early)


def call(key, get_vars, period):
    r = requests.get(BASE, params={"get": get_vars, "I_COMMODITY": HS,
                                   "time": period, "key": key}, timeout=60)
    if r.status_code != 200:
        return None, r.status_code
    try:
        return r.json(), 200
    except ValueError:
        warn(f"non-JSON 200 response for {period}: {r.text[:200]}")
        return None, 200


def already_ingested(period):
    try:
        with open(PATH) as f:
            return any(line.startswith(f"{period},census,") for line in f)
    except FileNotFoundError:
        return False


def main():
    key = env("CENSUS_API_KEY", required=True)
    data, period, code = None, None, None
    for cand in candidate_periods():
        if already_ingested(cand):
            log(f"{cand} already ingested — skipping")
            return
        data, code = call(key, "CTY_CODE,CTY_NAME,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1", cand)
        if data is None and code == 400:
            warn(f"{cand}: value+quantity vars rejected (400); retrying value-only "
                 "(verify names at imports/hs/variables.html)")
            data, code = call(key, "CTY_CODE,CTY_NAME,GEN_VAL_MO", cand)
        if data is not None:
            period = cand
            break
        if code == 204:
            log(f"{cand}: not published yet (204) — stepping back a month")
        else:
            warn(f"{cand}: census call failed with HTTP {code}")
    if data is None:
        warn("no candidate month returned data — if the browser key-test also fails, "
             "the key is invalid or unactivated (check the Census activation email)")
        return

    header, rows_in = data[0], data[1:]
    idx = {h: i for i, h in enumerate(header)}
    rows = []
    for r in rows_in:
        cty, name, val = r[idx["CTY_CODE"]], r[idx["CTY_NAME"]], r[idx["GEN_VAL_MO"]]
        qty = r[idx["GEN_QY1_MO"]] if "GEN_QY1_MO" in idx else ""
        unit = r[idx["UNIT_QY1"]] if "UNIT_QY1" in idx else ""
        rows.append([period, "census", f"us_imports_memory_value:{cty}", val, "", name])
        if qty not in ("", "0", None):
            rows.append([period, "census", f"us_imports_memory_qty:{cty}", qty, "",
                         f"{name}|unit={unit}"])
            try:
                rows.append([period, "census", f"us_imports_memory_unitvalue:{cty}",
                             round(float(val) / float(qty), 4), "", name])
            except (ValueError, ZeroDivisionError):
                pass
    air, acode = call(key, "CTY_CODE,AIR_VAL_MO,VES_VAL_MO", period)
    if air:
        aidx = {h: i for i, h in enumerate(air[0])}
        for r in air[1:]:
            try:
                a, v = float(r[aidx["AIR_VAL_MO"]]), float(r[aidx["VES_VAL_MO"]])
                if a + v > 0:
                    rows.append([period, "census",
                                 f"us_imports_memory_airshare:{r[aidx['CTY_CODE']]}",
                                 round(a / (a + v), 4), "", ""])
            except (ValueError, KeyError):
                continue
    else:
        warn(f"air/vessel variables not accepted (HTTP {acode}) — "
             "verify names at variables.html; value data unaffected")
    append_rows(PATH, HEADER, rows)
    log(f"census ingested {period}: {len(rows)} rows")


if __name__ == "__main__":
    main()
