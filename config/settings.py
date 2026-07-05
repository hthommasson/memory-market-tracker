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
K_FLOOR = 3                    # robust floor = k-th lowest qualifying ask
SELLER_FEEDBACK_MIN = 500
SELLER_FEEDBACK_PCT_MIN = 98.0
EBAY_LIMIT = 50

# Equities (spec §3.3)
TICKERS = ["MU", "DRAM", "RAM", "MUU"]
EQUITY_BACKFILL_START = "2024-01-01"

# SEC (spec §3.2)
MICRON_CIK = "0000723125"
