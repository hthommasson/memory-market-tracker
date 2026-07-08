"""Memory Inc. — the industry as one company (spec §3.2 extension, 2026-07-05).

Aggregates per-filer fundamentals from filings_facts.csv into industry-level rows:
  revenue_usd_bn        sum across MEMORY_INC_REV_MEMBERS present that quarter
  gross_margin_pct      aggregate ex-Samsung: 100 * sigma(GP) / sigma(rev), USD basis
  inventory_days        91.25 * sigma(inventory) / sigma(quarterly COGS), USD basis
  breadth_improving     count of ratio members with GM up AND inventory days down q/q

Honesty rules: every row carries its member list — the aggregate never pretends to
more coverage than it has. Ratio rows require >= 2 members (no aggregate-of-one).
Mixed fiscal calendars are bucketed to the NEAREST calendar quarter-end (Micron's
late-Feb close maps to Q1, etc.); the smear is a documented approximation.
SAMSUNG_MEM is manual memory-segment revenue in KRW (templates/), converted at the
same quarterly-average rate the DART collector stored — one rate, one truth.
"""
import csv, datetime as dt, os
from collections import defaultdict
from collectors.common import log, warn
from config.settings import (DATA_DIR, MEMORY_INC_REV_MEMBERS, MEMORY_INC_RATIO_MEMBERS)

FACTS = f"{DATA_DIR}/filings_facts.csv"
OUT = f"{DATA_DIR}/memory_inc.csv"


def bucket(period_end):
    """Nearest calendar quarter-end -> ('2026Q1', date(2026,3,31))."""
    d = dt.date.fromisoformat(period_end)
    cands = []
    for y in (d.year - 1, d.year, d.year + 1):
        for m, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            cands.append(dt.date(y, m, day))
    q = min(cands, key=lambda c: abs((c - d).days))
    return f"{q.year}Q{(q.month - 1) // 3 + 1}", q


def load():
    """-> {(ticker, concept): {bucket_label: value}} keeping the latest period per bucket."""
    if not os.path.exists(FACTS): return None
    data = defaultdict(dict)
    seen = defaultdict(dict)   # tiebreak: later period_end wins within a bucket
    with open(FACTS) as f:
        for r in csv.DictReader(f):
            try: val = float(r["value"])
            except (ValueError, TypeError): continue
            lab, _ = bucket(r["period_end"])
            key = (r["ticker"], r["concept"])
            if r["period_end"] >= seen[key].get(lab, ""):
                seen[key][lab] = r["period_end"]
                data[key][lab] = val
    return data


def usd_capex(data, member, lab):
    if member == "SAMSUNG_MEM":
        return None
    key = "capex_usd" if member == "SKHYNIX" else "capex"
    return data.get((member, key), {}).get(lab)


def usd_components(data, member, lab):
    """(revenue, cogs, inventory) in USD for one member-quarter, or Nones."""
    if member == "SKHYNIX":
        return (data.get((member, "revenue_usd"), {}).get(lab),
                data.get((member, "cogs_usd"), {}).get(lab),
                data.get((member, "inventory_usd"), {}).get(lab))
    if member == "SAMSUNG_MEM":
        krw = data.get((member, "revenue_krw"), {}).get(lab)
        fx = data.get(("SKHYNIX", "fx_krwusd_avg"), {}).get(lab)
        return (krw / fx if krw and fx else None, None, None)
    return (data.get((member, "revenue"), {}).get(lab),      # EDGAR filers: native USD
            data.get((member, "cogs"), {}).get(lab),
            data.get((member, "inventory"), {}).get(lab))


def main():
    data = load()
    if not data:
        warn("no filings_facts.csv yet — run a fundamentals collector first"); return
    labels = sorted({lab for series in data.values() for lab in series})
    rows = []
    ratio_hist = defaultdict(dict)   # member -> {lab: (gm, inv_days)}
    for lab in labels:
        rev_members, rev_total = [], 0.0
        for m in MEMORY_INC_REV_MEMBERS:
            rev, _, _ = usd_components(data, m, lab)
            if rev:
                rev_members.append(m); rev_total += rev
        if rev_members:
            rows.append([lab, "revenue_usd_bn", round(rev_total / 1e9, 2),
                         "|".join(rev_members), f"{len(rev_members)}/{len(MEMORY_INC_REV_MEMBERS)} members"])
        gp_sum = rev_sum = cogs_sum = inv_sum = 0.0
        ratio_members = []
        for m in MEMORY_INC_RATIO_MEMBERS:
            rev, cogs, inv = usd_components(data, m, lab)
            if rev and cogs and inv is not None:
                ratio_members.append(m)
                rev_sum += rev; cogs_sum += cogs; inv_sum += inv
                gp_sum += rev - cogs
                ratio_hist[m][lab] = (100 * (rev - cogs) / rev, 91.25 * inv / cogs)
        cap_sum, cap_rev, cap_members = 0.0, 0.0, []
        for mmb in MEMORY_INC_RATIO_MEMBERS:
            cap = usd_capex(data, mmb, lab)
            rv, _, _ = usd_components(data, mmb, lab)
            if cap is not None and rv:
                cap_members.append(mmb); cap_sum += cap; cap_rev += rv
        if len(cap_members) >= 2 and cap_rev:
            nc = "|".join(cap_members)
            meta_c = f"supply response; {len(cap_members)}/{len(MEMORY_INC_RATIO_MEMBERS)} members"
            rows.append([lab, "capex_usd_bn", round(cap_sum / 1e9, 2), nc, meta_c])
            rows.append([lab, "capex_pct_revenue", round(100 * cap_sum / cap_rev, 2), nc, meta_c])
        if len(ratio_members) >= 2 and rev_sum and cogs_sum:
            names = "|".join(ratio_members)
            note = f"ex-Samsung by necessity; {len(ratio_members)}/{len(MEMORY_INC_RATIO_MEMBERS)} members"
            rows.append([lab, "gross_margin_pct", round(100 * gp_sum / rev_sum, 2), names, note])
            rows.append([lab, "inventory_days", round(91.25 * inv_sum / cogs_sum, 1), names, note])
    for i, lab in enumerate(labels[1:], 1):
        prev = labels[i - 1]
        reporting = [m for m in MEMORY_INC_RATIO_MEMBERS
                     if lab in ratio_hist[m] and prev in ratio_hist[m]]
        if not reporting: continue
        improving = [m for m in reporting
                     if ratio_hist[m][lab][0] > ratio_hist[m][prev][0]
                     and ratio_hist[m][lab][1] < ratio_hist[m][prev][1]]
        rows.append([lab, "breadth_improving", len(improving), "|".join(improving) or "-",
                     f"of {len(reporting)} reporting: GM up AND inv days down q/q"])
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["quarter", "metric", "value", "members", "meta"])
        w.writerows(rows)
    log(f"memory_inc rebuilt: {len(rows)} rows across {len(labels)} quarters")


if __name__ == "__main__": main()
