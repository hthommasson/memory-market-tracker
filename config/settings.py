"""Versioned parameters — tune after the first month of live data (spec §4)."""
DATA_DIR = "docs/data"

# Composite regime weights (spec §4.1, v0.2 revision)
WEIGHTS = {"ddr5_desktop": 0.40, "server_ecc": 0.25, "sodimm": 0.20, "ddr4_desktop": 0.15}
QUALITY_GATE_MIN_OBS = 30      # days of live data before a segment carries weight
QUALITY_GATE_MAX_GAP = 3       # max consecutive missing days

# Momentum thresholds — asymmetric by design: early-warning bias for a levered long (spec §4.1)
THRESH_UP = 0.20               # annualized ln-slope above this  -> Rising
THRESH_DOWN = -0.10            # annualized ln-slope below this  -> Falling
MOMENTUM_WINDOW = 30           # days
ACCEL_LAG = 15                 # days between slope measurements
HYSTERESIS_DAYS = 5            # consecutive days required to commit a state change
MIN_OBS_FOR_LABEL = 10         # below this, label = "warming_up"

# eBay collector (spec §3.1 v0.4)
# Seller gate tuned 2026-07-05 from live fillability data: 500/98.0 rejected 77 of 156
# raw listings (49%) and was the binding constraint on ddr5. Remaining protections:
# k-th-lowest robust floor, per-SKU price bands, new-condition-only, per-run seller_rej audit.
K_FLOOR = 3                    # robust floor = k-th lowest qualifying ask
SELLER_FEEDBACK_MIN = 100      # was 500
SELLER_FEEDBACK_PCT_MIN = 97.0 # was 98.0
EBAY_LIMIT = 50

# Equities (spec §3.3)
TICKERS = ["MU", "DRAM", "RAM", "MUU"]
EQUITY_BACKFILL_START = "2024-01-01"

# Fundamentals — Panel B + Memory Inc. (spec §3.2, extended 2026-07-05)
MICRON_CIK = "0000723125"          # retained for reference/back-compat
EDGAR_FILERS = ["MU", "SNDK", "STX", "WDC"]   # CIKs resolved at runtime from SEC ticker file
DART_ENTITIES = {"000660": "SKHYNIX"}          # KRX stock code -> label; corp_code resolved at runtime
DART_BACKFILL_START_YEAR = 2024
FX_TICKER = "KRW=X"                            # via yfinance (already a dependency)
# Memory Inc. aggregate membership. Ratios (GM%, inventory days) run ex-Samsung by necessity:
# Samsung's company-level statements blend the conglomerate; only its memory-SEGMENT revenue
# (manual quarterly entry, templates/samsung_memory_template.csv) is defensible in an aggregate.
# STX/WDC are HDD, not memory: collected for breadth context, excluded from Memory Inc.
MEMORY_INC_REV_MEMBERS = ["MU", "SNDK", "SKHYNIX", "SAMSUNG_MEM"]
MEMORY_INC_RATIO_MEMBERS = ["MU", "SNDK", "SKHYNIX"]
