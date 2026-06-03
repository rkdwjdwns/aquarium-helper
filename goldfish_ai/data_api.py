"""
data_api.py — Pi 5 실시간 데이터 JSON 생성기
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    goldfish_ai/data/ 의 최신 fish_metrics_*.csv를 주기적으로 읽어
    dashboard.html이 폴링할 live.json을 생성.

실행:
    python data_api.py                  # 기본 (30초 간격)
    python data_api.py --interval 10    # 10초 간격
    python data_api.py --port 8081      # HTTP 서버 포트 (dashboard.html 서빙 겸용)

구조:
    goldfish_ai/
    ├── data_api.py          ← 이 파일
    ├── dashboard.html       ← 대시보드
    └── data/
        ├── live.json        ← 생성 대상 (dashboard.html이 폴링)
        ├── fish_metrics_*.csv
        └── growth_records.csv  (선택)
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import statistics
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────
DATA_DIR   = Path(__file__).resolve().parent / "data"
LIVE_JSON  = DATA_DIR / "live.json"
DASH_DIR   = Path(__file__).resolve().parent   # dashboard.html 위치


# ─────────────────────────────────────────────────────────────────────────
# CSV 파서
# ─────────────────────────────────────────────────────────────────────────
def _load_latest_csv(n_rows: int = 500) -> list[dict]:
    """가장 최근 fish_metrics_*.csv의 마지막 n_rows행 반환."""
    files = sorted(glob.glob(str(DATA_DIR / "fish_metrics_*.csv")))
    if not files:
        return []
    path = files[-1]
    try:
        rows = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows[-n_rows:]
    except Exception as e:
        print(f"[API] CSV 읽기 오류: {e}")
        return []


def _load_growth_csv() -> list[dict]:
    """growth_records.csv 로드 (없으면 빈 리스트)."""
    path = DATA_DIR / "growth_records.csv"
    if not path.exists():
        return []
    try:
        rows = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows
    except Exception:
        return []



def _load_sensor_log(n_rows: int = 60) -> list[dict]:
    """
    sensor_log.csv 로드 (ESP32 실측 센서 이력).
    컬럼: timestamp, temperature_c, ph, do_mg_l, tds_ppm, level, sensor_valid
    fish_metrics의 mock 센서값 대신 실측값으로 대시보드에 표시.
    """
    path = DATA_DIR / "sensor_log.csv"
    if not path.exists():
        return []
    try:
        rows = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("sensor_valid") == "True":
                    rows.append(row)
        return rows[-n_rows:]
    except Exception as e:
        print(f"[API] sensor_log 읽기 오류: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────
# 분석 계산
# ─────────────────────────────────────────────────────────────────────────
def _mean(vals: list) -> float:
    return round(statistics.mean(vals), 3) if vals else 0.0


def _std(vals: list) -> float:
    return round(statistics.stdev(vals), 3) if len(vals) >= 2 else 0.0


def _build_live(rows: list[dict], growth_rows: list[dict]) -> dict:
    if not rows:
        return {"status": "no_data", "updated_at": datetime.now().isoformat()}

    repr_rows = [r for r in rows if r.get("is_representative") == "True"]
    if not repr_rows:
        repr_rows = rows

    # ── 기본 현황 ──────────────────────────────────────────────────────────
    fish_ids  = sorted({r["fish_id"] for r in repr_rows})
    speeds    = [float(r["speed_px_s"]) for r in repr_rows if float(r["speed_px_s"]) > 0]
    activities = [float(r["activity"]) for r in repr_rows]

    zones = [r["zone"] for r in repr_rows]
    n_z   = max(len(zones), 1)
    zone_dist = {
        "TOP": round(zones.count("TOP") / n_z * 100, 1),
        "MID": round(zones.count("MID") / n_z * 100, 1),
        "BOT": round(zones.count("BOT") / n_z * 100, 1),
    }

    # ── 센서 (sensor_log.csv 우선, 없으면 fish_metrics 내장값) ──────────
    sensor_log_rows = _load_sensor_log(n_rows=60)
    if sensor_log_rows:
        sl = sensor_log_rows[-1]
        sensor = {
            "temperature_c": float(sl.get("temperature_c", 0)),
            "ph":            float(sl.get("ph", 0)),
            "do_mg_l":       float(sl.get("do_mg_l", 0)),
            "turbidity_ntu": float(sl.get("tds_ppm", 0)),   # TDS→탁도 대체 표시
            "tds_ppm":       float(sl.get("tds_ppm", 0)),
            "valid":         sl.get("sensor_valid") == "True",
            "source":        "sensor_log",
        }
        # 센서 시계열 (최근 60개 → 수온/pH 추이)
        sensor_series = [
            {
                "t":    r["timestamp"],
                "temp": float(r.get("temperature_c", 0)),
                "ph":   float(r.get("ph", 0)),
                "do":   float(r.get("do_mg_l", 0)),
                "tds":  float(r.get("tds_ppm", 0)),
            }
            for r in sensor_log_rows
        ]
    else:
        last = repr_rows[-1]
        sensor = {
            "temperature_c": float(last.get("temperature_c", 0)),
            "ph":            float(last.get("ph", 0)),
            "do_mg_l":       float(last.get("do_mg_l", 0)),
            "turbidity_ntu": float(last.get("turbidity_ntu", 0)),
            "tds_ppm":       0.0,
            "valid":         last.get("sensor_valid") == "True",
            "source":        "fish_metrics",
        }
        sensor_series = []

    # ── FPS 추정 ──────────────────────────────────────────────────────────
    ts_vals = [float(r["timestamp"]) for r in repr_rows[-30:]]
    fps_est = 0.0
    if len(ts_vals) >= 2:
        dur = ts_vals[-1] - ts_vals[0]
        fps_est = round(len(ts_vals) / dur, 1) if dur > 0 else 0.0

    # ── ABR 계산 (Baseline = 전체 repr μ,σ) ──────────────────────────────
    mu    = _mean(speeds)
    sigma = _std(speeds)
    sigma_threshold = 2.0
    anomaly = [s for s in speeds if abs(s - mu) > sigma_threshold * sigma]
    abr = round(len(anomaly) / max(len(speeds), 1), 4)

    # ── 활동량 시계열 (최근 60포인트, 5초 버킷) ───────────────────────────
    activity_series = []
    if repr_rows:
        t0 = float(repr_rows[0]["timestamp"])
        bucket: dict[int, list] = {}
        for r in repr_rows:
            b = int((float(r["timestamp"]) - t0) / 5)
            bucket.setdefault(b, []).append(float(r["activity"]))
        for b in sorted(bucket)[-60:]:
            activity_series.append({
                "t": round(t0 + b * 5),
                "v": round(_mean(bucket[b]), 2),
            })

    # ── 성장 데이터 ────────────────────────────────────────────────────────
    growth_by_fish: dict[str, list] = {}
    for gr in growth_rows:
        fid = gr.get("fish_id", "?")
        growth_by_fish.setdefault(fid, []).append({
            "date": gr.get("timestamp", "")[:10],
            "size_cm": float(gr.get("size_cm", 0)),
        })

    # size_index 기반 임시 추정 (px_to_cm 미확정 시 표시용)
    size_indices = [float(r["size_index"]) for r in repr_rows if "size_index" in r]
    avg_size_index = _mean(size_indices)

    # ── 총 추적 시간 ──────────────────────────────────────────────────────
    all_ts = [float(r["timestamp"]) for r in repr_rows]
    track_sec = round(max(all_ts) - min(all_ts), 1) if len(all_ts) >= 2 else 0.0

    return {
        "status":         "ok",
        "updated_at":     datetime.now().isoformat(),
        "fish_count":     len(fish_ids),
        "fish_ids":       fish_ids,
        "avg_speed":      _mean(speeds),
        "avg_activity":   _mean(activities),
        "fps_est":        fps_est,
        "zone_dist":      zone_dist,
        "sensor":         sensor,
        "abr":            abr,
        "abr_mu":         mu,
        "abr_sigma":      sigma,
        "activity_series":  activity_series,
        "sensor_series":    sensor_series,
        "growth_by_fish":   growth_by_fish,
        "avg_size_index":   avg_size_index,
        "track_sec":        track_sec,
        "total_rows":       len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────
# 주기 업데이트 루프
# ─────────────────────────────────────────────────────────────────────────
def _update_loop(interval: float):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[API] live.json 생성 루프 시작 ({interval}s 간격) → {LIVE_JSON}")
    while True:
        try:
            rows        = _load_latest_csv()
            growth_rows = _load_growth_csv()
            live        = _build_live(rows, growth_rows)
            with open(LIVE_JSON, "w", encoding="utf-8") as f:
                json.dump(live, f, ensure_ascii=False, indent=2)
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[API] {ts} 업데이트 — 행:{live.get('total_rows',0)} "
                  f"어류:{live.get('fish_count',0)} ABR:{live.get('abr',0):.3f}")
        except Exception as e:
            print(f"[API] 오류: {e}")
        time.sleep(interval)


# ─────────────────────────────────────────────────────────────────────────
# HTTP 서버 (dashboard.html + live.json 서빙)
# ─────────────────────────────────────────────────────────────────────────
class _CORSHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASH_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 액세스 로그 억제


def _serve(port: int):
    server = HTTPServer(("0.0.0.0", port), _CORSHandler)
    print(f"[API] HTTP 서버 시작: http://0.0.0.0:{port}/dashboard.html")
    server.serve_forever()


# ─────────────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Goldfish AI 대시보드 데이터 API")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="live.json 갱신 주기 (초, 기본 10)")
    parser.add_argument("--port",     type=int,   default=8081,
                        help="HTTP 서버 포트 (기본 8081)")
    args = parser.parse_args()

    # 업데이트 루프 — 별도 Thread
    t = threading.Thread(target=_update_loop, args=(args.interval,), daemon=True)
    t.start()

    # HTTP 서버 — 메인 Thread (블로킹)
    _serve(args.port)


if __name__ == "__main__":
    main()
