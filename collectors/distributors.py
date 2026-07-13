"""Panel E collector — distributor supply telemetry via Mouser + DigiKey (spec §3.5, phase 2).

The signal here is not price: it is STOCK QUANTITY and LEAD TIME on component-level
DRAM (ICs and industrial modules) — the industrial market's thermometer. In a squeeze,
distributor shelves empty and lead times stretch weeks before retail feels it.

Both sources are searched by base MPN (the suffixless lesson from the eBay basket):
keyword search returns the part family; we aggregate exact-prefix matches, summing
available quantity and taking the minimum quoted lead time.

Graceful activation: if a source's credentials are absent the source is skipped with
a log line, not an error — the collector can ship before the keys exist and starts
producing the day secrets are added. Idempotent per (date, sku, source) from day one.

Modes: default daily append | --dry-run synthetic | --fillability per-SKU diagnostics.
"""
import csv, os, re, sys, random
import requests
from collectors.common import append_rows, log, warn, today
from config.settings import DATA_DIR

REGISTRY = "config/dist_registry.csv"
PATH = f"{DATA_DIR}/dist_obs.csv"
HEADER = ["date", "sku_id", "source", "mpn_matched", "matches",
          "qty_available", "lead_time_days", "unit_price_usd"]
MOUSER_URL = "https://api.mouser.com/api/v1/search/keyword"
DK_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
DK_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"


def load_registry():
    with open(REGISTRY) as f:
        return [r for r in csv.DictReader(f) if r.get("retired_on", "") == ""]


def days_from(text):
    """'77 Days' -> 77; '16 Weeks' -> 112; '' -> None."""
    m = re.search(r"([\d.]+)\s*(day|week)", str(text), re.I)
    if not m: return None
    n = float(m.group(1))
    return int(n * 7) if m.group(2).lower().startswith("w") else int(n)


def mouser_lookup(mpn, key):
    r = requests.post(MOUSER_URL, params={"apiKey": key}, timeout=30,
                      json={"SearchByKeywordRequest": {"keyword": mpn, "records": 10}})
    r.raise_for_status()
    parts = (r.json().get("SearchResults") or {}).get("Parts") or []
    fam = [p for p in parts
           if str(p.get("ManufacturerPartNumber", "")).upper().startswith(mpn.upper())]
    if not fam: return None
    qty = 0
    for p in fam:
        m = re.search(r"[\d,]+", str(p.get("Availability", "")))
        if m: qty += int(m.group().replace(",", ""))
    leads = [d for d in (days_from(p.get("LeadTime")) for p in fam) if d is not None]
    prices = []
    for p in fam:
        for br in p.get("PriceBreaks") or []:
            m = re.search(r"[\d.]+", str(br.get("Price", "")))
            if m: prices.append(float(m.group())) if float(m.group()) > 0 else None; break
    return {"mpn": fam[0].get("ManufacturerPartNumber", mpn), "matches": len(fam),
            "qty": qty, "lead": min(leads) if leads else None,
            "price": min(prices) if prices else None}


def digikey_token(cid, secret):
    r = requests.post(DK_TOKEN_URL, timeout=30,
                      data={"client_id": cid, "client_secret": secret,
                            "grant_type": "client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]


def digikey_lookup(mpn, cid, token):
    r = requests.post(DK_SEARCH_URL, timeout=30,
                      headers={"Authorization": f"Bearer {token}",
                               "X-DIGIKEY-Client-Id": cid,
                               "X-DIGIKEY-Locale-Site": "US",
                               "X-DIGIKEY-Locale-Currency": "USD"},
                      json={"Keywords": mpn, "Limit": 10})
    r.raise_for_status()
    prods = r.json().get("Products") or []
    fam = [p for p in prods
           if str(p.get("ManufacturerProductNumber", "")).upper().startswith(mpn.upper())]
    if not fam: return None
    qty = sum(int(p.get("QuantityAvailable") or 0) for p in fam)
    leads = []
    for p in fam:
        w = p.get("ManufacturerLeadWeeks")
        d = days_from(w if re.search(r"[a-z]", str(w), re.I) else f"{w} weeks") if w else None
        if d is not None: leads.append(d)
    prices = [float(p["UnitPrice"]) for p in fam
              if p.get("UnitPrice") not in (None, "") and float(p["UnitPrice"]) > 0]
    return {"mpn": fam[0].get("ManufacturerProductNumber", mpn), "matches": len(fam),
            "qty": qty, "lead": min(leads) if leads else None,
            "price": min(prices) if prices else None}


def already_observed_today():
    if not os.path.exists(PATH): return False
    prefix = today() + ","
    with open(PATH) as f:
        return any(line.startswith(prefix) for line in f)


def synthetic(sku):
    return {"mpn": sku["mpn"], "matches": random.randint(1, 6),
            "qty": random.randint(0, 5000), "lead": random.choice([14, 56, 112, None]),
            "price": round(random.uniform(20, 300), 2)}


def main():
    dry = "--dry-run" in sys.argv
    fillability = "--fillability" in sys.argv
    if not fillability and already_observed_today():
        log(f"{today()} already observed — skipping (idempotent guard)"); return
    mouser_key = os.environ.get("MOUSER_API_KEY", "").strip()
    dk_id = os.environ.get("DIGIKEY_CLIENT_ID", "").strip()
    dk_secret = os.environ.get("DIGIKEY_CLIENT_SECRET", "").strip()
    sources = []
    if dry:
        sources = [("mouser", None), ("digikey", None)]
    else:
        if mouser_key: sources.append(("mouser", mouser_key))
        else: log("MOUSER_API_KEY not set — skipping mouser (add the secret to activate)")
        if dk_id and dk_secret:
            try: sources.append(("digikey", (dk_id, digikey_token(dk_id, dk_secret))))
            except Exception as e: warn(f"digikey auth failed: {e}")
        else: log("DIGIKEY_CLIENT_ID/SECRET not set — skipping digikey (add secrets to activate)")
    if not sources:
        log("no distributor sources active — nothing to do"); return

    rows, diags = [], []
    for sku in load_registry():
        for name, cred in sources:
            res, err = None, ""
            try:
                if dry: res = synthetic(sku)
                elif name == "mouser": res = mouser_lookup(sku["mpn"], cred)
                else: res = digikey_lookup(sku["mpn"], cred[0], cred[1])
            except Exception as e:
                err = str(e); warn(f"{sku['sku_id']} @ {name}: {e}")
            if res:
                rows.append([today(), sku["sku_id"], name, res["mpn"], res["matches"],
                             res["qty"], res["lead"] if res["lead"] is not None else "",
                             res["price"] if res["price"] is not None else ""])
            if fillability:
                if res:
                    diags.append(f"  {sku['sku_id']:22s} {sku['mpn']:18s} @ {name:8s} "
                                 f"matches={res['matches']:<3d} qty={res['qty']:<7d} "
                                 f"lead={res['lead'] if res['lead'] is not None else '-':<5} "
                                 f"px={res['price'] if res['price'] is not None else '-'}")
                else:
                    diags.append(f"  {sku['sku_id']:22s} {sku['mpn']:18s} @ {name:8s} "
                                 f"NO FAMILY MATCH{' (' + err + ')' if err else ''}  <- prune candidate")
    if fillability:
        log("distributor fillability diagnostics:")
        for d in diags: print(d)
        covered = len({r[1] for r in rows})
        log(f"coverage: {covered}/{len(load_registry())} SKUs matched on at least one source")
        return
    append_rows(PATH, HEADER, rows)
    log(f"wrote {len(rows)} distributor observations")


if __name__ == "__main__": main()
