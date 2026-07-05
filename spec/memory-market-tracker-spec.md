# Memory Market Regime Tracker — Phase 1 Specification

**Version 0.4 (free-first sourcing locked)** · July 4, 2026 · Status: ready to build on go

## Changelog v0.3 → v0.4 (free-first decision)

User decision: launch on the zero-cost path. The **eBay Browse API is promoted to the phase-1 primary price source** (new-condition, rated-seller-filtered, robust k-th-lowest ask floor, keyed on MPN + spec filters), and **Keepa moves to a documented later add-on**. The deferral is low-regret by construction: Keepa sells history, so a future subscription backfills the Amazon series retroactively — nothing irreplaceable is lost by waiting. The open verification from v0.3 is also settled, from the user's screenshots of Keepa's own subscription UI: **Keepa Pro (€29/month) explicitly lists "API access (1 token/min)"** — ample for this system's ~50 tokens/day — and the €19 figure from third-party guides was stale pricing. Historical context in phase 1 comes from a hand-curated reference-points file of dated press quotes plus the McCallum series. Server/ECC is promoted to a **phase-1 stretch goal**, since the eBay integration now ships in phase 1 and the marginal cost of server queries is near zero. Phase-1 registrations on the user side: a Census API key and an eBay developer application.

## Changelog v0.2 → v0.3 (sourcing fork resolved)

The user does not have a company/custom-domain email, so per the §3.1 contingency, **Keepa is the phase-1 primary source** and Best Buy is parked (revisitable if a qualifying email ever exists). Consequences propagated through the spec: the Amazon basket's full price history becomes a **phase-1 deliverable** (the dashboard launches with the 2024→2026 crisis arc already charted, not an empty axis); ASINs join the SKU registry; the fillability check is now against Amazon's assortment, where it is expected to pass trivially; and phase 1 honestly runs Amazon-only for consumer pricing until phase 2 adds cross-sources (eBay for server, Newegg go/no-go). Required registrations reduce to two: a Keepa API tier and a Census key.

## Changelog v0.1 → v0.2 (audit findings)

**Verified against primary sources:** Micron CIK 0000723125 and its fiscal cadence (quarter ends late Feb/May/Aug/Nov, reports ~3–4 weeks later) confirmed from actual EDGAR filings. Census international-trade API endpoint, `GEN_VAL_MO`-family variables, and the value/quantity/transport-mode splits confirmed from Census documentation. Best Buy developer program and Products API confirmed live (near-real-time pricing, 5 req/s default limit). Korea flash/monthly cadence previously verified from July 2026 releases.

**Errors corrected:** (1) A Census API key is *required*, not optional, for all queries — free registration. (2) Best Buy no longer issues API keys to free-email addresses (Gmail/Yahoo-type); a company/custom-domain email is required, which changes the phase-1 gating logic and triggers a documented contingency. (3) The claim that the physical layer "cannot be backfilled" was overstated: Keepa sells Amazon price *history*, so the Amazon slice is backfillable at cost — this materially strengthens the case for Keepa and is reflected in §2 and §9.

**Design refinements:** the Price-Falling × Volume-Rising cell of the composite matrix relabeled as the classic memory cycle-top pattern (highest-alert cell) rather than "mix-shift"; divergence flag D2 rebuilt on non-overlapping incremental flash windows (cumulative 1–10 and 1–20 reads overlap and were being compared incorrectly); composite segment weights revised so the noisiest future series (eBay ask-floor) no longer carries the largest weight, with a quality gate before any segment carries weight at all; asymmetric momentum thresholds retained but their rationale (early-warning bias for a levered long) now documented; daily job moved to post-US-close; a new air-share-of-imports metric added to Panel D (free byproduct of Census transport-mode splits, partially substituting for paywalled air-freight indices); McCallum long-run historical context restored (discussed, but dropped from v0.1); an explicit considered-and-deferred appendix added.

---

## 1. Purpose

This system answers one question, refreshed daily: **is the memory market accelerating, plateauing, or weakening — and do independent data layers agree?**

It is built for the holder of leveraged memory instruments ($RAM, a 2x daily-reset fund on the Roundhill Memory ETF; $MUU, a 2x daily-reset fund on Micron), for whom regime *quality* matters as much as direction: daily-reset leverage compounds favorably in smooth trends, decays in choppy plateaus, and cuts sharply in drawdowns. The dashboard therefore reports both the market regime and the trend-quality context in which that regime is unfolding.

The core design principle is a **stack of signals ordered by speed**, where disagreements between adjacent layers are first-class outputs rather than noise. Equities react instantly but overreact to narrative; physical retail prices update daily and anchor the fundamental trend; distributor inventory and flow telemetry give a daily supply-stress read; Korean customs flash data delivers a Samsung/SK-hynix fundamental pulse every ~10 days; monthly trade and revenue series measure volume; quarterly filings confirm the regime after the fact. A divergence between layers (e.g., equities pricing a cycle break the physical market has not confirmed, as on June 5, 2026) is precisely the signal the system exists to surface.

This is an instrument panel, not an advisor. It produces readings, regime labels, and divergence flags. It does not produce buy/sell recommendations, and nothing in it constitutes investment advice.

## 2. The signal stack

| # | Layer | Cadence | Typical latency | Role | Primary sources |
|---|-------|---------|-----------------|------|-----------------|
| 1 | Equities & ETFs | Daily (intraday capable) | None | Forward-looking, narrative-prone | Yahoo Finance (yfinance), Stooq fallback |
| 2 | Physical retail prices | Daily | None (from collection start) | Fundamental trend anchor; leads filings | eBay Browse API (all segments); Keepa (later add-on); optional Newegg |
| 3 | Supply-stress telemetry | Daily | None | Rationing / channel-stress read (experimental) | DigiKey & Mouser APIs; own collector telemetry |
| 4 | Korea customs flash | Every ~10 days | ~1–2 days after period | Samsung + SK hynix volume pulse | KCS 1–10 / 1–20 day releases; MOTIE monthly |
| 5 | Monthly trade & revenue | Monthly | ~8–45 days | Volume regime | US Census imports API; Taiwan MOEA orders; Nanya monthly revenue |
| 6 | Quarterly fundamentals | Quarterly | ~25–45 days after quarter | Regime confirmation | SEC EDGAR XBRL (Micron + US filers); DART (phase 3) |

Backfill asymmetry: layers 1, 5, and 6 can be reconstructed historically at any time. Within layer 2, the Amazon slice is backfillable via Keepa *whenever* a subscription is added — the property that makes deferring Keepa low-regret. The eBay and layer-3 telemetry series exist only from the day collection begins; those collectors ship before any dashboard polish. Phase-1 historical context comes from the reference-points file and the McCallum series (§3.6).

## 3. Panel specifications

### 3.1 Panel A — Physical prices (retail basket)

The panel tracks four segments: DDR5 desktop kits, DDR4 desktop kits, DDR5 SODIMM, and Server/ECC (DDR5 RDIMM). Each segment produces two daily series. The **fixed-basket series** is the median $/GB across a versioned list of ~4 named SKUs and gives a clean like-for-like trend. The **floor series** is the cheapest in-stock price meeting a spec filter and represents what a buyer actually faces; it is also robust to SKU delisting.

Basket construction rules: roughly four SKUs per segment, selected for mainstream spec, sales-rank prominence, and brand spread across Corsair, G.Skill, Kingston, TeamGroup, and ADATA. Crucial is excluded — Micron ended Crucial consumer shipments in February 2026 and remaining stock is a draining, non-representative tail. Indicative spec filters: DDR5 desktop 2x16GB, 5600–6400 MT/s, CL28–36; DDR4 desktop 2x16GB, 3200–3600, CL16–18; SODIMM 2x16GB DDR5-5600; Server/ECC 32GB and 64GB DDR5-4800/5600 RDIMM modules. Because DDR4 production is being wound down industry-wide, its fixed basket is expected to decay; for DDR4 the floor series is primary and the basket is best-effort. Any basket composition change increments `basket_version`, and old and new baskets run in parallel for 14 days to audit the splice.

**Sourcing (revised).** The design principle is two independent sources for the consumer segments, because single-retailer assortment is a real risk in a shortage market that has seen national in-stock reference counts collapse. The candidates:

**The eBay Browse API is the phase-1 primary source (free path locked in v0.4).** The Browse API is free via eBay's developer program (OAuth client-credentials flow; default allowances run to thousands of calls per day against our load of a few dozen) and now covers *all four segments* from phase 1. Because eBay has no stable per-product identifier equivalent to an ASIN, the basket keys on **MPN + spec filters** rather than listing IDs: per MPN per day, the collector queries new-condition listings from sellers above a feedback threshold with US item location, recording the qualifying-listing count, the median ask, and the **robust floor — the k-th-lowest conforming ask (k≈3)** — so a single bait or mispriced listing cannot poison the series. The structural caveat is stated on the dashboard itself: these are *asking prices, not transactions*, so a monthly manual Terapeak sold-price calibration point is retained. Server/ECC uses the same collector with condition tracked explicitly; new and used remain **separate series and are never blended**. **Keepa is a documented later add-on**, its open question settled by Keepa's own subscription UI: Keepa Pro (€29/month) includes API access at 1 token/minute — ~1,440 tokens/day against our ~50/day load — and adding it at any point backfills the Amazon series retroactively. Revisit trigger: if after the first live month the eBay ask-floor proves too noisy for regime detection (day-over-day dispersion swamping the momentum signal). **Best Buy stays parked** (company-email constraint). **Newegg** remains an optional, off-by-default, robots.txt-respecting scrape module.

Honest concentration note: consumer pricing launches on a single free source of asking prices — the weakest layer in the stack, deliberately hedged by the system's redundancy: the regime engine leans on Korea trade values, Census unit values, fundamentals, and equities in parallel, so a noisy price floor degrades the composite gracefully rather than fatally. The **fillability check** adapts to eBay: each consumer segment must yield at least 3 MPNs with ≥3 qualifying new-condition listings each.

Per-day computed metrics, per segment: median $/GB (in-stock, first-party/authorized sellers only unless tagged otherwise); 7/30/90-day momentum, defined as the OLS slope of ln(price) annualized; acceleration, defined as the current 30-day slope minus the 30-day slope measured 15 days prior; 52-week percentile; in-stock rate across tracked SKUs; SKU churn count; and a per-order quantity-limit flag where retailers impose purchase caps.

### 3.2 Panel B — Company fundamentals & filings

The EDGAR leg uses the SEC's free structured-data endpoints (JSON, no key; requests must send a declared `User-Agent` with contact email and stay under 10 req/s). For Micron (**CIK 0000723125, verified against live filings**), the collector pulls the XBRL company-facts series for revenue, gross profit, cost of goods, and net inventory, and derives the two canonical cycle-state variables: **gross margin %** and **inventory days** (91.25 × inventory ÷ quarterly COGS). The same puller extends trivially to other US filers in the memory complex (Sandisk/Western Digital, Seagate, and optionally the equipment makers as a capex read). The submissions feed supplies an 8-K stream (earnings, guidance, material events) and Form 4 insider-transaction rollups (net insider buys/sells, trailing 90 days) for MU — the only near-real-time signal EDGAR offers.

Micron's off-cycle fiscal calendar is treated as a feature — and is now verified from filing records: quarters end in late February, May, August, and November, with 10-Qs landing roughly three to four weeks later, making each MU print the industry's early read for its calendar quarter. Earnings dates are pre-seeded in the events table, and guidance deltas are logged as events.

Korean filers (Samsung, SK hynix) do not file with EDGAR. Phase 1 handles them manually: Samsung's preliminary earnings (published ~8 days after quarter end) and both companies' quarterly DRAM commentary are entered into `monthly_series`/`events` by hand — a few minutes per quarter. Phase 3 automates this via DART's free public API (opendart.fss.or.kr).

### 3.3 Panel C — Market layer (equities & ETFs)

Daily closes for MU, DRAM, RAM, and MUU, with SK hynix (000660.KS) and Samsung (005930.KS) optional, via yfinance with a Stooq fallback. Computed metrics: 1/5/20/60-day returns; 20-day realized volatility, annualized; drawdown from the trailing 252-day high; and the MU/DRAM ratio as a single-name-vs-basket dispersion read.

The panel also renders a **trend-quality readout** for the leveraged context: a simple trend-efficiency ratio (magnitude of the 60-day move relative to realized volatility over the same window), labeled in zones such as "trend-dominant" versus "chop-dominant." This is a descriptive statement about the daily-reset mechanics of the instruments held — in chop-dominant zones, daily rebalancing decay is the documented behavior of 2x products even absent a downtrend — and is presented as context, not as a recommendation.

### 3.4 Panel D — Trade & volume

**Korea** is the tier-one feed. The trade ministry publishes full monthly trade data on approximately the 1st (semiconductors broken out, with HBM now reported separately), and Korea Customs publishes 1–10 day and 1–20 day flash reads mid-month. Every Korean series is stored with both the headline YoY and a working-day-adjusted YoY, since calendar effects routinely distort the flash reads by ten points or more. Phase-1 ingestion is a manual CSV template — roughly three two-minute entries per month — with an optional scraper deferred.

**US Census** import data is the most automatable leg, and its mechanics are now verified: the international-trade timeseries API (`api.census.gov/data/timeseries/intltrade/imports/hs`) provides monthly value *and* quantity by HS code with a **required, free API key** (~5–6 week publication lag). The collector tracks the memory-IC code 8542.32 plus an exploratory module-adjacent code family, computes import unit values (value ÷ quantity) as a blended landed-ASP proxy, and slices by origin (KR, TW, CN, MY, JP). **New in v0.2:** because the dataset splits value by transport mode, the collector also computes the **air share of memory imports** (air value ÷ total value) — a free structural indicator of urgency/value-density in the flow, and a monthly-cadence partial substitute for the paywalled air-freight-rate indices. Standing caveats stored with the series: HS categories blend DRAM/NAND/HBM, so unit values are mix-shift-contaminated; and origin splits reflect supply-chain routing (fab → offshore packaging/test → re-export), not end demand.

**Taiwan** contributes the leading edge: MOEA export orders (electronics), published monthly around the 20th, historically precede shipments by one to three months and are where weakening tends to appear first. **Nanya Technology** (TWSE 2408), a pure-play commodity-DRAM maker, must disclose revenue monthly by the ~10th via MOPS — a free monthly pure-play DRAM revenue datapoint with no customs ambiguity. Both are manual-entry in phase 1, scraper candidates in phase 2.

The panel reduces to a **volume-regime score** (Rising / Flat / Falling) blending the direction of working-day-adjusted Korean semiconductor export growth, Taiwan order momentum, and Nanya revenue momentum.

### 3.5 Panel E — Physical flow (experimental)

This panel exists to shave days off the ~10-day Korea flash cadence and is explicitly labeled experimental on the dashboard.

**Distributor basket (phase 2, highest confidence).** DigiKey and Mouser both offer free-registration APIs exposing live stock quantities and factory lead times per part number. The collector tracks a fixed basket of ~10 MPNs (commodity DDR4/DDR5 DRAM ICs across the three makers, plus standard modules where listed) daily, producing 30-day stock-change and lead-time-change series. Honest scope note: distributors carry industrial and legacy parts, not HBM or leading-edge server DIMMs — but channel inventory is where squeezes propagate visibly first.

**Own telemetry (phase 1, free).** Panel A's collector already produces daily in-stock rates, delist events, and quantity-cap flags; these are promoted to an explicit supply-stress sub-panel.

**Freighter counts via ADS-B (phase 3, prototype-gated).** Flight tracking is aviation's AIS, and unlike ocean shipping, dedicated freighters out of Incheon and Taoyuan are a meaningfully chip-weighted flow. Using the free OpenSky API, the prototype counts weekly cargo-carrier departures on Korea/Taiwan → North America lanes, with charter surges as the event of interest. Methodology (freighter identification via registration lists vs. cargo-carrier callsigns) is to be settled in the prototype. Promotion gate: the series must demonstrate meaningful correlation with the Korea flash data before it earns a place on the main dashboard; until then it lives on an experimental sub-page.

**Air freight rates** (TAC Index, Freightos) remain watch-only — the good indices are paywalled — with the Census air-share metric (§3.4) now covering part of this signal at monthly cadence for free. Ocean data (transpacific container volumes, Port of LA throughput) is retained only as a low-weight consumer-electronics demand backdrop, never as a memory signal: chips fly.

### 3.6 Historical context (static, phase 1)

A one-time ingestion of McCallum's long-run memory price dataset (jcmit.net, $/MB back to 1957) provides the 60-year curve the live data sits inside, rendered as a log-scale context chart on the dashboard. Static reference files live in `/data/static` and are exempt from the append-only convention.

## 4. Regime engine

### 4.1 Price regime (per segment, daily)

The engine classifies each segment from its 30-day annualized momentum (`m30`, the OLS slope of ln $/GB) and its acceleration (`a30`, the change in `m30` over 15 days). Initial thresholds, explicitly tunable after four weeks of live data: `m30 > +20%` → Rising; `−10% ≤ m30 ≤ +20%` → Flat; `m30 < −10%` → Falling; with the Rising/Falling labels annotated "and steepening / and easing" from the sign of `a30`. **The asymmetry is deliberate and now documented:** a levered long benefits from early warning, so the engine is more sensitive to incipient weakening (triggering Falling at −10%) than to declaring strength (requiring +20% for Rising). To prevent label-flapping, a state change requires the new condition to hold for five consecutive trading days (hysteresis).

The market-level price regime is a weighted blend. **Revised weights:** DDR5 desktop 0.40, Server/ECC 0.25, SODIMM 0.20, DDR4 0.15. (v0.1 assigned Server/ECC the largest weight, which would have let the noisiest series — a phase-2 eBay ask-floor — dominate the composite; the enterprise story is carried more reliably by Panel D's trade values.) **Quality gate:** a segment carries weight only after 30 live days and a basic stability check (no gaps > 3 days, dispersion within bounds); until then its weight is redistributed pro-rata. Weights are a declared, versioned parameter, not a hidden constant.

### 4.2 Composite regime (price × volume)

The headline regime badge combines the price regime with Panel D's volume-regime score:

| | **Volume Rising** | **Volume Flat** | **Volume Falling** |
|---|---|---|---|
| **Price Rising** | Accelerating (broad boom) | Scarcity-led (supply-constrained) | Late-cycle squeeze (watch) |
| **Price Flat** | Rationed squeeze (enterprise pull, consumer plateau) | Stagnating | Early weakening (volume leads) |
| **Price Falling** | **Cycle-top pattern (highest alert):** bits still flowing while ASPs crack — the classic memory-downturn onset | Softening | Weakening (broad) |

The Price-Falling × Volume-Rising cell was relabeled in v0.2: in memory-cycle history (2018–19, 2022–23), volumes continuing to grow while prices roll over is the canonical top signal, not a benign mix-shift — and for a levered long it is the single most consequential cell in the matrix. For reference, the July 2026 starting condition reads as **Price Flat × Volume Rising → Rationed squeeze**: consumer retail on a plateau at multi-year highs while Korean semiconductor export values roughly tripled year-over-year.

### 4.3 Divergence flags (daily evaluation)

- **D1 — Equity vs. physical:** sign of the 20-day DRAM ETF return disagrees with the sign of 30-day physical momentum, with both exceeding magnitude thresholds. This is the June 5 pattern: equities repricing a cycle break the physical market had not confirmed.
- **D2 — Flash vs. price (rebuilt in v0.2):** Korea's published flash reads are *cumulative* (days 1–10 and 1–20) and therefore overlap; comparing them directly double-counts the first ten days. The engine instead derives non-overlapping increments — the 1–10 window, the implied 11–20 window (P20 − P10), and the implied 21–month-end window (monthly total − P20) — each normalized per working day. D2 fires when two consecutive incremental windows decelerate while physical prices still accelerate, or the reverse.
- **D3 — Fundamentals confirmation light:** Micron inventory days falling with gross margin rising confirms a tight regime; the joint reversal is the classic early confirmation of a turn. Rendered as a green/amber/red light rather than a flag.
- **D4 — Leverage-context notice:** trend-quality readout in the chop-dominant zone while the price regime is Flat — a descriptive notice that daily-reset decay mechanics are active.

(Formatting exception: flags are enumerated because they are referenced by ID elsewhere in the system.)

### 4.4 Statistics module (monthly batch)

Monthly-aligned series (physical $/GB, Korea exports WDA, Taiwan orders, Nanya revenue, MU fundamentals interpolated) are cross-correlated at lags of 0–6 months, reporting best-lag correlations with sample sizes displayed alongside. The module is descriptive only: with quarterly fundamentals contributing perhaps 8–12 observations over the study horizon, regression models and backtests are explicitly out of scope for phase 1 to avoid manufacturing false confidence.

## 5. Data model

Append-only CSVs, one file per table, committed to the repo daily (the "git scraping" pattern gives versioned history for free). An optional SQLite mirror is generated for local analysis. All dates UTC, all prices USD. Corrections are new rows carrying a revision flag, never edits. Static reference data (§3.6) lives in `/data/static` outside these conventions.

| Table | Grain | Key fields |
|---|---|---|
| `sku_registry` | One row per tracked SKU | sku_id, segment, brand, mpn, capacity_gb, kit_config, gen, speed, cas, first_seen, retired_on, basket_version |
| `price_obs` | SKU × source × day | date, sku_id, source, price, list_price, in_stock, seller_type, condition, qty_limit |
| `segment_daily` | Segment × series × day | date, segment, series {basket, floor}, usd_per_gb, n_obs, in_stock_rate |
| `equity_daily` | Ticker × day | date, ticker, close, volume |
| `monthly_series` | Source × metric × period | period (supports flash periods like `2026-06-P10`, `2026-06-P20`), source, metric, value, value_wda, meta |
| `filings_facts` | CIK × concept × period | period_end, cik, ticker, concept, value |
| `events` | One row per event | date, category {filing, guidance, policy, tech, supply, market}, title, url, impact_tags |
| `distributor_obs` | MPN × source × day | date, mpn, source, qty_available, lead_weeks |

The `events` table is hand-curated and treated as half the analytical value of the system: every chart on the dashboard renders event markers from it.

## 6. Repository & operations

**Layout.** `/collectors` (bestbuy.py, keepa.py, equities.py, sec_facts.py, census.py, distributors.py, ebay.py), `/engine` (regime.py, divergence.py, stats.py), `/data` (CSV tables; `/data/static` for reference series), `/dashboard` (static index.html + JS reading raw CSV URLs), `/templates` (manual-entry CSVs for Korea/Taiwan/Nanya/DART), `/docs` (this spec), `.github/workflows`.

**Scheduling (revised).** A single daily workflow at ~22:30 UTC — after the US market close year-round, DST included — runs the price, equity, and distributor collectors, then the regime engine, then commits; this captures the same day's equity close alongside an end-of-day retail snapshot. A weekly workflow runs basket health checks. A monthly workflow runs the Census pull and the statistics module. Manual-entry templates raise reminder issues automatically on their expected publication dates (the 1st, ~11th, ~21st for Korea; ~10th for Nanya; ~20th for Taiwan).

**Secrets.** `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` (required — phase-1 primary source), `CENSUS_API_KEY` (required — free registration), `SEC_CONTACT_EMAIL`; phase-2 `MOUSER_API_KEY`, `DIGIKEY_CLIENT_ID/SECRET`; phase-3 `DART_KEY`; later add-on: `KEEPA_API_KEY`; parked: `BESTBUY_API_KEY` — all stored as GitHub Actions secrets.

**Dashboard.** Static GitHub Pages site, Plotly.js, no backend: a regime banner (composite badge + per-segment badges), the panels, divergence flags with history, the event timeline, the long-run context chart, and a per-feed staleness badge that turns red when a feed's last update exceeds 1.5× its expected cadence. Note: GitHub Pages on a free plan requires a public repository; a private repo needs a paid plan or a different host. Nothing in the system is sensitive (no account data, no positions), so a public repo is viable — flagged as a decision item.

**Failure handling.** Each collector is independently fault-isolated (one source failing never blocks the commit of others); workflow failures email via GitHub's default notifications; a SKU missing or out of stock for 7+ consecutive days auto-files a basket-health issue. Optional phase-2 alerting pushes regime changes and divergence flags to email or a Discord webhook.

## 7. Phasing

**Phase 1 — the clock-starter (target: ~1 week of build effort).** Repo scaffold; eBay Browse collector covering the three consumer segments (~12 MPNs, plus robust-floor queries), including the fillability check, with **Server/ECC as an in-phase stretch goal** since the same collector serves it at near-zero marginal cost; equities collector with historical backfill; Micron company-facts puller with 12-quarter backfill; McCallum context ingestion; **reference-points file** seeded from dated press quotes (e.g., ~$80–120 for 32GB DDR5 in mid-2025 vs. ~$375 in June 2026, with comparable anchors per segment); manual-entry templates seeded with June 2026 values (Korea's record month, the 20-day flash, Nanya's latest print); events table seeded with the story so far (Crucial exit announcement and February cutoff, the TurboQuant shock, the June 5 drawdown, Micron's June 24 earnings, Korea's June record); dashboard v0 rendering Panels A, C, D-partial, the context chart, and the event timeline; regime engine running price-regime-only (the 30-day momentum window warms up over the first live month; reference points render as context markers meanwhile). **Acceptance: seven consecutive daily commits with no manual intervention; dashboard rendering on Pages; fillability check passed (≥3 MPNs per consumer segment with ≥3 qualifying new-condition listings each); all specified Panel A/C metrics visible.**

**Phase 2 — depth (weeks 2–4).** Server/ECC hardening (sold-price calibration cadence, condition-series QA — the collector itself starts as the phase-1 stretch); Census import ingestion with unit values and air share; distributor basket live; volume regime, composite matrix, and divergence flags D1–D4; alert webhook; go/no-go decision on the Newegg scrape module.

**Phase 3 — opportunistic.** DART automation for Samsung/SK hynix; ADS-B freighter prototype behind its correlation gate; filing text-drift analysis (quarter-over-quarter risk-factor and MD&A deltas) as an optional NLP layer.

## 8. Risks and honest limitations

The system's physical layer measures consumer retail, while roughly two-thirds of the thesis lives in enterprise and contract markets it cannot observe directly; enterprise conditions are inferred from the consumer/enterprise spread, trade values, and fundamentals, and the dashboard labels this inference rather than hiding it. Trade unit values are mix-shift-contaminated by design and are presented as revenue-cycle signals, never as like-for-like prices. Retail-source access carries an audited constraint: Best Buy keys require a non-free-provider email, and its API terms should be reviewed for the intended use at any future signup — moot for now with eBay as the phase-1 source, but recorded for any revisit. Scraping is treated as a last resort: official APIs are preferred everywhere, any scraping module respects robots.txt and runs at low frequency, and every scraper is assumed to break eventually — fault isolation and staleness badges exist for exactly this reason. Quarterly fundamentals contribute too few observations for inferential statistics, so the statistics module stays descriptive and the regime engine stays rule-based. Non-backfillable series (eBay, distributor telemetry) are why collectors ship before polish; the parked Best Buy note in §3.1 records the email constraint for any future revisit. Manual-entry feeds depend on a human habit, which is why reminder issues are auto-filed. And the standing disclaimer: this is an information instrument built and maintained for the user's own analysis; it is not investment advice, and regime labels are descriptive classifications of data, not forecasts.

## 9. Decisions needed before build

Sourcing is locked (eBay-primary free path; Keepa recorded as a later add-on at €29/month including 1 token/min per Keepa's own subscription UI; Best Buy parked). Two registrations remain on the user's side, both free and parallelizable with the scaffold build: a **Census API key** — one universal key from the Census signup page covers every Census dataset, including the trade timeseries this system uses; there is no per-dataset key to choose — and an **eBay developer application** (developer.ebay.com → register → create an application → production Client ID and Client Secret for the Browse API). Phase-2 registrations (Mouser, DigiKey) can wait. Judgment items still open: public vs. private repository (public enables free GitHub Pages; nothing sensitive is stored either way); alert channel preference (email vs. Discord); and confirmation or adjustment of the composite weights (0.40 / 0.25 / 0.20 / 0.15) and the asymmetric momentum thresholds, both versioned parameters intended to be tuned after the first month of live data. Everything that does not depend on the two keys — scaffold, equities and SEC collectors, McCallum ingestion, reference points, templates, engine, dashboard skeleton, and the eBay collector in dry-run mode — is buildable immediately, with the keys dropped in as repo secrets when they arrive.

## Appendix — Considered and deferred

WSTS/SIA monthly semiconductor billings: authoritative but the memory-segment detail sits behind a paid subscription; topline press releases enter the event log instead. PCPartPicker: excellent multi-retailer history, but its terms prohibit scraping — excluded on those grounds. CamelCamelCamel: free Amazon alerts but no API — superseded by Keepa. TAC Index / Freightos air rates: paywalled; partially substituted by the Census air-share metric. UN Comtrade: too slow for cycle timing; useful only for annual structural context. Panjiva/ImportGenius-style bill-of-lading data: ocean-manifest-only and therefore structurally blind to air-freighted semiconductors — rejected for this use.

---

*End of specification v0.2. On approval, phase 1 begins with the repo scaffold and the sourcing-fork resolution; the physical-price clock starts on the first daily commit.*
