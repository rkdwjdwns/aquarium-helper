"""Local dashboard data API for aquarium project v2.

Reads the latest runtime CSV tails without scanning multi-hundred-MB files on
every poll. It generates data/live.json using the calibrated v2 rules:
- hourly normalized Activity Index
- 5-minute P01/P99 ABR
- GOOD/FAIR/POOR AI analysis quality
- TOP/MID/BOT distribution
- canonical TDS (ppm), never TDS-as-turbidity
- latest real FRS v2 result
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

try:
    import yaml
except Exception:
    yaml = None

from scripts.analytics.behavior_v2 import BehaviorV2Analyzer

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LIVE_JSON = DATA_DIR / "live.json"
DASH_DIR = ROOT
CONFIG_PATH = ROOT / "config.yaml"


def _config() -> dict:
    if yaml is None or not CONFIG_PATH.exists():
        return {}
    try:
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[API] config 로드 오류: {e}")
        return {}


def _tail_text_lines(path: Path, n_lines: int, block_size: int = 65536) -> list[str]:
    """Return at most the last n_lines non-empty text lines efficiently."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= n_lines:
            read_size = min(block_size, pos)
            pos -= read_size
            f.seek(pos)
            data = f.read(read_size) + data
    lines = data.decode("utf-8", errors="ignore").splitlines()
    return [line for line in lines[-n_lines:] if line.strip()]


def _tail_csv(path: Path, n_rows: int) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            header = f.readline().strip()
        if not header:
            return []
        lines = _tail_text_lines(path, n_rows + 2)
        lines = [line for line in lines if line.strip() and line.strip() != header]
        text = [header] + lines[-n_rows:]
        return list(csv.DictReader(text))
    except Exception as e:
        print(f"[API] tail CSV 오류 {path.name}: {e}")
        return []


def _latest_metrics_path() -> Path | None:
    files = sorted(glob.glob(str(DATA_DIR / "fish_metrics_*.csv")))
    return Path(files[-1]) if files else None


def _load_latest_metrics(n_rows: int = 40000) -> tuple[list[dict], str]:
    path = _latest_metrics_path()
    if path is None:
        return [], ""
    return _tail_csv(path, n_rows), path.name


def _sensor_rows(n_rows: int = 180) -> list[dict]:
    return _tail_csv(DATA_DIR / "sensor_log.csv", n_rows)


def _as_float(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _sensor_snapshot(rows: list[dict]) -> tuple[dict, list[dict]]:
    if not rows:
        return ({
            "temperature_c": 0.0, "ph": 0.0, "do_mg_l": 0.0,
            "tds_ppm": 0.0, "level": None, "valid": False,
            "quality": "INCOMPLETE", "source": "none",
        }, [])

    series = []
    for r in rows:
        tds = _as_float(r.get("tds_ppm", r.get("turbidity_ntu", 0.0)))
        valid = _as_bool(r.get("sensor_valid", r.get("valid", False)))
        temp = _as_float(r.get("temperature_c"))
        ph = _as_float(r.get("ph"))
        do = _as_float(r.get("do_mg_l"))
        quality = "GOOD" if valid and temp > 0 and ph > 0 and do > 0 and tds > 0 else "INCOMPLETE"
        series.append({
            "t": str(r.get("timestamp", "")),
            "temp": temp,
            "ph": ph,
            "do": do,
            "tds": tds,
            "quality": quality,
        })

    last = rows[-1]
    last_s = series[-1]
    level_raw = last.get("level", "")
    try:
        level = float(level_raw) if str(level_raw).strip() else None
    except Exception:
        level = None
    sensor = {
        "temperature_c": last_s["temp"],
        "ph": last_s["ph"],
        "do_mg_l": last_s["do"],
        "tds_ppm": last_s["tds"],
        "level": level,
        "valid": last_s["quality"] == "GOOD",
        "quality": last_s["quality"],
        "source": "sensor_log",
        "tds_monitor_only": True,
        "turbidity_available": False,
    }
    return sensor, series


def _fps_estimate(rows: list[dict]) -> float:
    # Count unique frame indices in the recent ~10 seconds, not fish rows.
    parsed = []
    for r in rows[-3000:]:
        try:
            parsed.append((float(r.get("timestamp", 0)), int(float(r.get("frame_idx", -1)))))
        except Exception:
            pass
    if len(parsed) < 2:
        return 0.0
    last_ts = max(t for t, _ in parsed)
    recent = [(t, f) for t, f in parsed if last_ts - t <= 10 and f >= 0]
    if len(recent) < 2:
        return 0.0
    duration = max(t for t, _ in recent) - min(t for t, _ in recent)
    frames = len({f for _, f in recent})
    return round(frames / duration, 1) if duration > 0 else 0.0


def _latest_frs() -> dict | None:
    rows = _tail_csv(DATA_DIR / "frs_history.csv", 5)
    if not rows:
        return None
    r = rows[-1]
    try:
        score = _as_float(r.get("score", r.get("frs_v2", 0.0)))
        version = str(r.get("version", "v1"))
        return {
            "version": version,
            "status": r.get("status", "OK"),
            "feeding_ts": _as_float(r.get("feeding_ts", 0.0)),
            "datetime": r.get("datetime_str", r.get("feeding_timestamp", "")),
            "score": round(score, 2),
            "activity_increase_pct": _as_float(r.get("activity_increase_pct", 0.0)),
            "response_latency_sec": _as_float(r.get("response_latency_sec", r.get("first_surface_sec", 0.0))),
            "activity_score": _as_float(r.get("activity_score", _as_float(r.get("s2_activity_inc", 0.0)) * 100.0)),
            "latency_score": _as_float(r.get("latency_score", _as_float(r.get("s1_response_time", 0.0)) * 100.0)),
            "zone_component_used": _as_bool(r.get("zone_component_used", False)),
            "note": r.get("note", ""),
        }
    except Exception:
        return None


def _growth_status() -> dict:
    rows = _tail_csv(DATA_DIR / "growth_prediction.csv", 3)
    if not rows:
        return {"available": False, "status": "calibration_required", "message": "px_to_cm calibration 필요"}
    r = rows[-1]
    status = str(r.get("model_status", r.get("status", "unknown")))
    return {
        "available": status not in {"calibration_required", "disabled", "unknown"},
        "status": status,
        "message": r.get("message", ""),
    }


def _build_live(rows: list[dict], source_session: str) -> dict:
    if not rows:
        return {"status": "no_data", "updated_at": datetime.now().isoformat()}

    cfg = _config()
    activity_cfg = cfg.get("analytics", {}).get("activity_v2", {}) or {}
    baseline_csv = activity_cfg.get(
        "baseline_csv",
        cfg.get("storage", {}).get("baseline_v2_csv", "data/activity_baseline_v2.csv"),
    )
    baseline_path = Path(baseline_csv)
    if not baseline_path.is_absolute():
        baseline_path = ROOT / baseline_path

    sensor, sensor_series = _sensor_snapshot(_sensor_rows())
    analyzer = BehaviorV2Analyzer(activity_cfg, baseline_csv=str(baseline_path))
    behavior = analyzer.summarize(rows, sensor_ready=sensor.get("quality") == "GOOD")

    return {
        "status": "ok",
        "schema_version": "dashboard-v2",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source_session": source_session,
        "dashboard_ready": behavior.get("dashboard_ready", False),

        "activity_index": behavior.get("activity_index"),
        "activity_state": behavior.get("activity_state", "UNKNOWN"),
        "raw_activity": behavior.get("raw_activity", 0.0),
        "baseline_activity_median": behavior.get("baseline_activity_median", 0.0),
        "activity_series": behavior.get("activity_series", []),

        "abr_5min_pct": behavior.get("abr_5min_pct"),
        "abr_warning_pct": behavior.get("abr_warning_pct", 13.0),
        "abnormal_activity_flag": behavior.get("abnormal_activity_flag", False),

        "analysis_quality": behavior.get("analysis_quality", "POOR"),
        "analysis_good_pct": behavior.get("analysis_good_pct", 0.0),
        "analysis_usable_pct": behavior.get("analysis_usable_pct", 0.0),
        "behavior_quality": behavior.get("behavior_quality", "POOR"),
        "frame_count_5s": behavior.get("frame_count_5s", 0),

        "zone_dist": behavior.get("zone_dist", {"TOP": 0, "MID": 0, "BOT": 0}),
        "sensor": sensor,
        "sensor_series": sensor_series,
        "frs_latest": _latest_frs(),
        "growth": _growth_status(),

        "developer": {
            "fish_count_estimate": behavior.get("fish_count_estimate_dev", 0.0),
            "speed_px_s_median": behavior.get("speed_px_s_median_dev", 0.0),
            "fps_est": _fps_estimate(rows),
            "loaded_tail_rows": len(rows),
            "abr_valid_bins": behavior.get("abr_valid_bins", 0),
        },
    }


def _write_live(live: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LIVE_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LIVE_JSON)


def _update_loop(interval: float):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[API v2] live.json 갱신 시작 ({interval}s) -> {LIVE_JSON}")
    while True:
        try:
            rows, session = _load_latest_metrics()
            live = _build_live(rows, session)
            _write_live(live)
            abr = live.get("abr_5min_pct")
            abr_text = f"{abr:.1f}%" if isinstance(abr, (int, float)) else "N/A"
            print(
                f"[API v2] {datetime.now().strftime('%H:%M:%S')} "
                f"Activity={live.get('activity_index')} {live.get('activity_state')} "
                f"ABR5m={abr_text} AI={live.get('analysis_quality')}"
            )
        except Exception as e:
            print(f"[API v2] 오류: {type(e).__name__}: {e}")
        time.sleep(interval)


class _CORSHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASH_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def _serve(port: int):
    server = HTTPServer(("0.0.0.0", port), _CORSHandler)
    print(f"[API v2] http://0.0.0.0:{port}/dashboard.html")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Aquarium dashboard data API v2")
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--once", action="store_true", help="live.json 1회 생성 후 종료")
    args = parser.parse_args()

    if args.once:
        rows, session = _load_latest_metrics()
        live = _build_live(rows, session)
        _write_live(live)
        print(json.dumps(live, ensure_ascii=False, indent=2))
        return

    t = threading.Thread(target=_update_loop, args=(args.interval,), daemon=True)
    t.start()
    _serve(args.port)


if __name__ == "__main__":
    main()
