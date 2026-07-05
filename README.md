# Memory Market Regime Tracker

Daily instrument panel for the DRAM/memory cycle: **is the market accelerating, plateauing, or weakening — and do independent data layers agree?** Built per `spec/memory-market-tracker-spec.md` (v0.4). Signals are stacked by speed — equities, physical ask-floors, Korea customs flash, monthly trade/revenue, quarterly fundamentals — and divergences between layers are first-class outputs.

**This is an information instrument, not investment advice.** Regime labels are descriptive classifications of data, not forecasts.

## Setup (once, ~15 minutes)

1. Create a **public** GitHub repository (public enables free GitHub Pages) and push this folder to it.
2. **Settings → Actions → General → Workflow permissions** → select *Read and write permissions* (the bot commits data).
3. **Settings → Secrets and variables → Actions** → add the secrets below (add what you have; missing ones skip gracefully).
4. **Settings → Pages** → *Deploy from a branch* → branch `main`, folder `/docs`.
5. **Actions tab** → run the `daily` workflow manually once (workflow_dispatch) to prime the pipeline.
6. Open your Pages URL — the dashboard renders with seeds (events, Korea June, reference points) immediately and fills as data lands.

## Secrets

| Secret | Status | Where to get it |
|---|---|---|
| `CENSUS_API_KEY` | **required** | api.census.gov/data/key_signup.html (one universal key, free) |
| `SEC_CONTACT_EMAIL` | **required** | your email — SEC requires a declared User-Agent contact |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | **required for prices** | developer.ebay.com → create application → *production* keyset |
| `MOUSER_API_KEY`, `DIGIKEY_*` | phase 2 | distributor basket |
| `KEEPA_API_KEY` | later add-on | Keepa Pro (€29/mo) includes 1 token/min; backfills Amazon history retroactively whenever added |

## Local commands

```bash
pip install -r requirements.txt
python -m pytest tests/                          # engine math tests
python -m collectors.ebay_prices --dry-run       # synthetic data through the full pipeline (no creds)
python -m collectors.ebay_prices --fillability   # phase-1 acceptance: >=3 MPNs/segment with >=3 listings
python -m engine.regime                          # rebuild segment_daily + regime_daily

# validate your Census key in one line:
curl "https://api.census.gov/data/timeseries/intltrade/imports/hs?get=CTY_CODE,CTY_NAME,GEN_VAL_MO&I_COMMODITY=854232&time=2026-03&key=$CENSUS_API_KEY"
```

## What runs when

| Workflow | Schedule (UTC) | Does |
|---|---|---|
| `daily` | 22:30 (post-US-close) | equities, eBay ask-floors, SEC facts → regime engine → divergence flags → commit |
| `monthly` | 5th, 12:00 | Census memory imports (value, quantity, unit value, air share) + one-time McCallum context |

## Your manual routine (~6 minutes/month)

Korea Customs publishes 1–10 and 1–20 day flash reads (~11th and ~21st) and MOTIE publishes the monthly total (~1st). Copy `templates/korea_entry_template.csv` rows into `docs/data/monthly_series.csv` with the numbers — always record working days and the per-working-day adjusted YoY. Same pattern for Taiwan export orders (~20th) and Nanya monthly revenue (~10th). The event log `docs/data/events.csv` is hand-curated and is half the analytical value: add fab news, guidance changes, tech shocks as they happen.

## First live steps

1. Add eBay secrets, then run `python -m collectors.ebay_prices --fillability` (or the daily workflow) — **the SKU registry ships as `status=candidate`**: expect to adjust a few MPNs or price bands until each consumer segment passes with ≥3 MPNs. Server/ECC is a stretch goal and may pass later.
2. Seven consecutive clean daily commits = phase-1 acceptance (spec §7).
3. Tune `config/settings.py` (weights, thresholds) after the first month of live data — they are versioned parameters, not constants.

## Honest limitations

Prices are eBay **asking prices from qualified sellers, not transactions** — labeled as such on the dashboard, calibrated monthly against Terapeak sold prices by hand. Consumer pricing launches on this single free source; the regime engine hedges it with Korea trade values, Census unit values, fundamentals, and equities in parallel. Census HS categories blend DRAM/NAND/HBM (unit values are mix-shift signals, not like-for-like prices). Quarterly fundamentals are too few observations for inferential statistics — the engine stays rule-based on purpose. Data in `docs/data/*.csv` is append-only; corrections are new rows, never edits.

## License

MIT — see `LICENSE`. Code only; data files are derived from third-party and public sources.
