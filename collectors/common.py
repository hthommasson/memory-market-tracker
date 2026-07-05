import csv, os, sys, datetime

def log(msg): print(f"[{datetime.datetime.utcnow().isoformat(timespec='seconds')}Z] {msg}", flush=True)
def warn(msg): log(f"WARN: {msg}")
def today(): return datetime.date.today().isoformat()

def append_rows(path, header, rows):
    """Append-only CSV writer; creates file with header if absent (spec §5)."""
    exists = os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if not exists: w.writerow(header)
        for r in rows: w.writerow(r)
    log(f"wrote {len(rows)} rows -> {path}")

def env(name, required=False):
    v = os.environ.get(name, "").strip()
    if required and not v:
        warn(f"missing env {name} — skipping this collector (add it as a GitHub Actions secret)")
        sys.exit(0)  # exit 0 so one missing secret never fails the whole workflow (spec §6 fault isolation)
    return v
