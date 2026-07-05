"""Panel A collector — phase-1 primary (spec §3.1 v0.4).

Per MPN per day: query new-condition US listings from qualified sellers,
record the qualifying count, median ask, and robust floor (k-th lowest ask).
Asking prices, not transactions — labeled as such downstream.

Modes:
  python -m collectors.ebay_prices                 daily collection (needs EBAY_* secrets)
  python -m collectors.ebay_prices --dry-run       synthetic prices; proves the pipeline pre-credentials
  python -m collectors.ebay_prices --fillability   phase-1 acceptance check with per-SKU diagnostics

v0.4.3: fillability now prints per-SKU diagnostics (raw hits, seller-gate rejects,
lowest asks) plus a category probe when an MPN returns zero raw results, so dead
part numbers are distinguishable from thin supply and from over-tight bands.
"""
import base64, csv, random, statistics, sys
import requests
from collectors.common import append_rows, log, warn, env, today
from config.settings import (DATA_DIR, K_FLOOR, SELLER_FEEDBACK_MIN,
                             SELLER_FEEDBACK_PCT_MIN, EBAY_LIMIT)

REGISTRY = "config/sku_registry.csv"
PATH = f"{DATA_DIR}/price_obs.csv"
HEADER = ["date", "sku_id", "source", "price", "list_price", "in_stock",
          "seller_type", "condition", "qty_limit"]
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def load_registry():
    with open(REGISTRY) as f:
        return [r for r in csv.DictReader(f) if r.get("retired_on", "") == ""]


def get_token(cid, secret):
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = requests.post(TOKEN_URL,
                      headers={"Authorization": f"Basic {auth}",
                               "Content-Type": "application/x-www-form-urlencoded"},
                      data={"grant_type": "client_credentials",
                            "scope": "https://api.ebay.com/oauth/api_scope"},
                      timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def search(query, lo, hi, token):
    params = {
        "q": query,
        "filter": f"conditions:{{NEW}},itemLocationCountry:US,"
                  f"price:[{lo:.0f}..{hi:.0f}],priceCurrency:USD",
        "limit": str(EBAY_LIMIT),
        "sort": "price",
    }
    r = requests.get(SEARCH_URL, params=params, timeout=30,
                     headers={"Authorization": f"Bearer {token}",
                              "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
    r.raise_for_status()
    return r.json().get("itemSummaries", [])


def qualified_asks(sku, token):
    """(sorted qualifying asks, raw hit count, seller-gate reject count) for one MPN."""
    lo, hi = float(sku["price_lo"]), float(sku["price_hi"])
    items = search(sku["mpn"], lo, hi, token)
    asks, rejected = [], 0
    for item in items:
        seller = item.get("seller", {})
        try:
            score = int(seller.get("feedbackScore", 0))
            pct = float(seller.get("feedbackPercentage", 0))
            price = float(item["price"]["value"])
        except (KeyError, ValueError, TypeError):
            continue
        if score >= SELLER_FEEDBACK_MIN and pct >= SELLER_FEEDBACK_PCT_MIN:
            asks.append(price)
        else:
            rejected += 1
    return sorted(asks), len(items), rejected


def category_probe(sku, token):
    """Zero-raw diagnostic: does a generic brand+spec query find anything in-band?
    Diagnostic only — never used for collection (generic queries mix products)."""
    q = f"{sku['brand']} {sku['gen'].upper()} {sku['capacity_gb']}GB {sku['speed']}"
    try:
        return len(search(q, float(sku["price_lo"]), float(sku["price_hi"]), token))
    except Exception:
        return -1


def synthetic_asks(sku):
    lo, hi = float(sku["price_lo"]), float(sku["price_hi"])
    mid = (lo + hi) / 2
    return sorted(round(random.uniform(mid * 0.9, mid * 1.15), 2) for _ in range(8))


def observe(sku, asks):
    n = len(asks)
    if n == 0:
        return [today(), sku["sku_id"], "ebay", "", "", False, "ebay_new",
                sku.get("condition", "new"), 0]
    floor = asks[min(K_FLOOR, n) - 1]          # robust floor: k-th lowest (spec §3.1)
    med = round(statistics.median(asks), 2)
    return [today(), sku["sku_id"], "ebay", floor, med, n >= K_FLOOR, "ebay_new",
            sku.get("condition", "new"), n]


def main():
    dry = "--dry-run" in sys.argv
    fillability = "--fillability" in sys.argv
    registry = load_registry()
    token = None
    if not dry:
        cid = env("EBAY_CLIENT_ID", required=True)
        secret = env("EBAY_CLIENT_SECRET", required=True)
        token = get_token(cid, secret)

    rows, per_segment, diags = [], {}, []
    for sku in sorted(registry, key=lambda s: s["segment"]):
        raw, rejected = 0, 0
        try:
            if dry:
                asks = synthetic_asks(sku); raw = len(asks)
            else:
                asks, raw, rejected = qualified_asks(sku, token)
        except Exception as e:
            warn(f"{sku['sku_id']}: {e}")
            asks = []
        rows.append(observe(sku, asks))
        per_segment.setdefault(sku["segment"], []).append(len(asks) >= K_FLOOR)
        if fillability:
            lows = ",".join(f"${a:.0f}" for a in asks[:3]) or "-"
            line = (f"  {sku['segment']:13s} {sku['sku_id']:26s} {sku['mpn']:26s} "
                    f"raw={raw:<3d} seller_rej={rejected:<3d} qual={len(asks):<3d} "
                    f"lowest=[{lows}]")
            if raw == 0 and not dry:
                probe = category_probe(sku, token)
                line += f"  <- ZERO RAW: MPN likely dead/wrong (category probe={probe} in-band)"
            elif len(asks) < K_FLOOR:
                line += "  <- thin: found but under threshold (band or seller gate?)"
            diags.append(line)

    if fillability:
        log("per-SKU diagnostics:")
        for d in diags:
            print(d)
        ok = True
        for seg, hits in per_segment.items():
            passed = sum(hits)
            status = "PASS" if passed >= 3 else "FAIL"
            if passed < 3 and seg != "server_ecc":  # server is the phase-1 stretch goal
                ok = False
            log(f"fillability {seg}: {passed} MPNs with >= {K_FLOOR} qualifying listings [{status}]")
        log("FILLABILITY " + ("PASSED" if ok else "FAILED — adjust MPNs/bands in sku_registry.csv"))
        return

    append_rows(PATH, HEADER, rows)
    if dry:
        log("dry-run complete — synthetic data written; replace with live run once EBAY_* secrets exist")


if __name__ == "__main__":
    main()
