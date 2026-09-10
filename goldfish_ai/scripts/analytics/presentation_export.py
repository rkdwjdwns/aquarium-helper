"""Create the four presentation CSVs used by the frontend demo.

This utility does not alter RAW data. It exports already calibrated/analysed
results into small, purpose-specific CSV files. AI control decisions are logged
at runtime by scripts/ai_control_policy.py and are intentionally not generated here:
- activity_dashboard.csv
- abr_dashboard.csv
- feeding_response_v2.csv
- growth_dashboard.csv

Usage example:
  python scripts/analytics/presentation_export.py \
      --dashboard data/dashboard_dataset_v2.csv \
      --frs data/feeding_response_v2.csv \
      --growth data/growth_vbgf_comet_reference.csv \
      --output data/presentation
"""
from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def _read_dashboard(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _latest_hours(rows: list[dict], hours: int) -> list[dict]:
    parsed=[]
    for r in rows:
        try:
            parsed.append((datetime.fromisoformat(r["timestamp_kst"]), r))
        except Exception:
            continue
    if not parsed:
        return []
    end=max(x[0] for x in parsed)
    start=end-timedelta(hours=hours)
    return [r for dt,r in parsed if dt>=start]


def _write_subset(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k:r.get(k, "") for k in fields})


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--dashboard", required=True)
    ap.add_argument("--frs", required=True)
    ap.add_argument("--growth", required=True)
    ap.add_argument("--output", default="data/presentation")
    ap.add_argument("--hours", type=int, default=24)
    args=ap.parse_args()

    dashboard=_latest_hours(_read_dashboard(Path(args.dashboard)), args.hours)
    out=Path(args.output)
    _write_subset(out/"activity_dashboard.csv", dashboard, [
        "timestamp_kst","activity_index","activity_state","activity_median",
        "baseline_activity_median","behavior_quality","dashboard_ready",
        "top_ratio","mid_ratio","bot_ratio",
    ])
    _write_subset(out/"abr_dashboard.csv", dashboard, [
        "timestamp_kst","abr_5min_pct","abr_valid_ratio_5min",
        "abnormal_activity_flag","activity_state","behavior_quality","dashboard_ready",
    ])
    shutil.copy2(args.frs, out/"feeding_response_v2.csv")
    shutil.copy2(args.growth, out/"growth_dashboard.csv")
    print(f"presentation CSV export complete: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
