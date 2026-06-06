"""
run.py — Goldfish AI 통합 메인 루프
금붕어 자동 사육 AI 시스템 (v2.0)

통합 항목:
    [goldfish_ai]
    - AI 파이프라인 (YOLO + ByteTrack + Feature) — 별도 Thread
    - 센서 수신 (MQTT)
    - 분석 모듈 (FRS / ABR / 패턴 / 성장)
    - 서버 전송 (server_tx.py)
    - 행동 브릿지 (behavior_bridge.py)
    - 제어 판단 (decision.py)

    [pi_client]
    - 장치 명령 polling (command_poller.py) — 별도 Thread
    - Pi IP 등록 (register_pi.py)
    - 조명 타이머 (light_timer.py)
    - 성장 기록 전송 (growth_sender.py)
    - 활동 패턴 전송 (pattern_sender.py)

    [스트리밍]
    - MJPEG 스트리밍 서버 (port 8080) — 별도 Thread
      → 프론트엔드: <img src="http://192.168.0.56:8080/video_feed">

실행:
    python run.py                  # 기본
    python run.py --show           # 화면 표시 (f키: 급이, q키: 종료)
    python run.py --mock-sensor    # ESP32 없이 Mock 센서
    python run.py --no-server      # 서버 전송 없이 로컬만
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

import csv
from datetime import datetime

# ── 경로 설정 ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# pi_client 경로 추가 (v6: goldfish_ai/ 안으로 이동됨)
PI_CLIENT = ROOT / "pi_client"
if PI_CLIENT.exists() and str(PI_CLIENT) not in sys.path:
    sys.path.insert(0, str(PI_CLIENT))

# ── goldfish_ai imports ───────────────────────────────────────────────────
from scripts.demo_pipeline   import run as run_pipeline, load_config, get_stream_frame
from scripts.sensor_reader   import SensorReader, check_water_quality
from scripts.behavior_bridge import get_bridge
from scripts.decision        import DecisionEngine
from scripts.server_tx       import ServerTx

# ── pi_client imports (없으면 Mock) ──────────────────────────────────────
try:
    from command_poller import start_polling
    from register_pi    import register_pi_ip
    from light_timer    import control_light, get_next_change
    from growth_sender  import send_growth, estimate_weight
    PI_CLIENT_OK = True
except ImportError as e:
    print(f"[RUN] pi_client import 실패 → 해당 기능 비활성화: {e}")
    PI_CLIENT_OK = False


# ─────────────────────────────────────────────────────────────────────────
# 주기 설정 (초)
# ─────────────────────────────────────────────────────────────────────────
LIGHT_INTERVAL    = 60
GROWTH_INTERVAL   = 3600
DECISION_INTERVAL = 10   # 제어 판단 주기
STREAM_PORT       = 8080  # MJPEG 스트리밍 포트


# ─────────────────────────────────────────────────────────────────────────
# 종료 핸들러
# ─────────────────────────────────────────────────────────────────────────
_stop_event = threading.Event()

def _on_exit(sig, frame):
    print("\n[RUN] 종료 신호 수신 — 정리 중...")
    _stop_event.set()
    sys.exit(0)

signal.signal(signal.SIGINT,  _on_exit)
signal.signal(signal.SIGTERM, _on_exit)


# ─────────────────────────────────────────────────────────────────────────
# MJPEG 스트리밍 서버
# ─────────────────────────────────────────────────────────────────────────
class _MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 콘솔 로그 억제

    def do_GET(self):
        if self.path != "/video_feed":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Access-Control-Allow-Origin", "*")  # CORS 허용
        self.end_headers()

        try:
            while True:
                frame = get_stream_frame()
                if frame:
                    self.wfile.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame + b"\r\n"
                    )
                time.sleep(0.07)  # ~14fps
        except Exception:
            pass  # 클라이언트 연결 끊김 시 조용히 종료


def _start_stream_server():
    """MJPEG 스트리밍 서버를 백그라운드 Thread로 시작."""
    server = HTTPServer(("0.0.0.0", STREAM_PORT), _MJPEGHandler)
    t = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="MJPEGStream",
    )
    t.start()
    print(f"[Stream] MJPEG 스트리밍 시작 → http://192.168.0.56:{STREAM_PORT}/video_feed")


# ─────────────────────────────────────────────────────────────────────────
# 성장 기록 전송 (pi_client/growth_sender.py 호출)
# ─────────────────────────────────────────────────────────────────────────
def _send_growth_records(tx: ServerTx):
    """
    analytics/growth_tracker.py의 최근 기록을 서버로 전송.
    GrowthTracker는 demo_pipeline.py 내부에서 관리.
    현재는 bridge의 size_index 기반 추정값으로 전송.
    """
    try:
        behavior = get_bridge().get_latest()
        size_index = behavior.get("size_index", 0.0)
        if size_index <= 0:
            return

        # size_index → 체장 추정 (카메라 캘리브레이션 전 임시)
        # px_to_cm_ratio 미확정 → 실측 후 config.yaml에 반영 예정
        estimated_length = size_index * 0.5   # 임시 비율

        for fish_id in range(1, 4):  # 3마리 (3~5cm 코멧 금붕어)
            tx.send_growth({
                "fish_id":          fish_id,
                "current_size_cm":  estimated_length,
                "growth_per_day":   0.0,     # Baseline 쌓이면 계산
                "estimated_stage":  "juvenile",  # 3~5cm 유어 단계
                "moving_avg_size":  size_index,
            })
    except Exception as e:
        print(f"[RUN] 성장 기록 전송 오류: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 제어 판단 루프 (별도 Thread)
# ─────────────────────────────────────────────────────────────────────────
def _decision_loop(sensor: SensorReader, engine: DecisionEngine, tx: ServerTx):
    """
    10초마다 수질 + 행동 데이터로 제어 판단.

    [A 방식 — 서버 우선 제어]
    decision.py 는 판단만 담당. 실제 릴레이 제어는 서버가 수행:
        1. tx.send_sensor() → POST /api/sensor/
        2. 서버가 히스테리시스 기준으로 auto_actions 결정
        3. command_poller.py 가 GET /api/commands/ 폴링 → set_relay()

    decision.py 는 서버가 모르는 AI 행동 분석 기반 경고(alerts)를
    tx.send_event_log() 로 서버 EventLog 에 기록하는 역할만 수행.
    """
    print("[Decision] 제어 판단 루프 시작 (A 방식 — 서버 우선)")
    while not _stop_event.is_set():
        try:
            sensor_data = sensor.get_latest()
            behavior    = get_bridge().get_latest()
            result      = engine.decide(sensor_data, behavior)

            # ── 센서 데이터 서버 전송 (서버가 auto_actions 결정) ──────────
            # command_poller.py 가 4초마다 GET /api/commands/ 로 결과를 받아
            # set_relay() 를 호출함 → 릴레이 충돌 없음
            if sensor_data.valid:
                append_sensor_log(sensor_data)
                tx.send_sensor(sensor_data)

            # ── AI 행동 분석 기반 경고 → 서버 EventLog 전송 ──────────────
            # 수면 집군 / 이상 행동 등 센서만으로 감지 불가한 이벤트를 기록
            if result.alerts:
                for alert in result.alerts:
                    print(f"[Decision] ⚠️  {alert}")
                    tx.send_event_log(
                        level   = "WARNING" if not result.behavior_ok else "INFO",
                        message = alert,
                    )

            # ── 수질 점수 이상 시 DANGER 로그 ────────────────────────────
            if result.water_score < 50:
                tx.send_event_log(
                    level   = "DANGER",
                    message = f"수질 점수 위험: {result.water_score}/100",
                )

        except Exception as e:
            print(f"[Decision] 오류: {e}")

        time.sleep(DECISION_INTERVAL)


# ─────────────────────────────────────────────────────────────────────────
# 센서 전용 CSV 로거
# ─────────────────────────────────────────────────────────────────────────
SENSOR_LOG_PATH = Path("data/sensor_log.csv")

def append_sensor_log(sensor_data):
    """
    실제 SensorReader에서 읽은 센서값을 data/sensor_log.csv에 누적 저장.
    fish_metrics_*.csv와 다르게 물고기 감지 여부와 상관없이 저장됨.
    """
    SENSOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    file_exists = SENSOR_LOG_PATH.exists()

    row = {
        "timestamp":     datetime.now().isoformat(timespec="seconds"),
        "temperature_c": getattr(sensor_data, "temperature_c", ""),
        "ph":            getattr(sensor_data, "ph", ""),
        "do_mg_l":       getattr(sensor_data, "do_mg_l", ""),
        "tds_ppm":       getattr(sensor_data, "turbidity_ntu", ""),
        "level":         getattr(sensor_data, "level", ""),
        "sensor_valid":  getattr(sensor_data, "valid", ""),
    }

    with open(SENSOR_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp", "temperature_c", "ph",
                "do_mg_l", "tds_ppm", "level", "sensor_valid",
            ],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ─────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Goldfish AI 통합 메인")
    parser.add_argument("--source",      default="0")
    parser.add_argument("--config",      default="config.yaml")
    parser.add_argument("--show",        action="store_true")
    parser.add_argument("--max-frames",  type=int, default=None)
    parser.add_argument("--mock-sensor", action="store_true")
    parser.add_argument("--no-server",   action="store_true",
                        help="서버 전송 비활성화 (로컬 테스트용)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    print(f"\n{'='*60}")
    print(f"  Goldfish AI — 통합 메인 루프")
    print(f"{'='*60}")
    print(f"  config    : {args.config}")
    print(f"  mock-sensor: {args.mock_sensor}")
    print(f"  server    : {'비활성화' if args.no_server else cfg.get('server_enabled', False)}")
    print(f"  pi_client : {'OK' if PI_CLIENT_OK else '미연결'}")

    # ── Pi IP 등록 ────────────────────────────────────────────────────────
    if PI_CLIENT_OK:
        register_pi_ip()
        print(f"  조명 예정: {get_next_change()}")

    # ── 장치 명령 polling 시작 (pi_client) ───────────────────────────────
    if PI_CLIENT_OK:
        start_polling(interval=4.0)
        print("[RUN] 장치 명령 polling 시작")

    # ── 센서 Reader 시작 ──────────────────────────────────────────────────
    sensor = SensorReader(
        broker = cfg.get("mqtt_broker", "localhost"),
        topic  = cfg.get("mqtt_topic",  "goldfish/sensors"),
        mock   = args.mock_sensor,
    )
    sensor.start()

    # ── 서버 전송 초기화 ──────────────────────────────────────────────────
    server_enabled = cfg.get("server_enabled", False) and not args.no_server
    tx = ServerTx(mock=not server_enabled or cfg.get("server_mock", True))

    # ── 제어 판단 엔진 ────────────────────────────────────────────────────
    engine = DecisionEngine()

    # ── 제어 판단 루프 (별도 Thread) ──────────────────────────────────────
    decision_thread = threading.Thread(
        target  = _decision_loop,
        args    = (sensor, engine, tx),
        daemon  = True,
        name    = "DecisionLoop",
    )
    decision_thread.start()

    # ── MJPEG 스트리밍 서버 시작 (별도 Thread) ────────────────────────────
    # demo_pipeline.py가 매 프레임 _set_stream_frame()으로 공유 → 여기서 송출
    # 프론트엔드: <img src="http://192.168.0.56:8080/video_feed">
    _start_stream_server()

    # ── 주기 타이머 ──────────────────────────────────────────────────────
    last_light_time  = 0.0
    last_growth_time = 0.0

    # ── 보조 루프 (조명/성장 주기 관리) ──────────────────────────────────
    def _aux_loop():
        nonlocal last_light_time, last_growth_time
        while not _stop_event.is_set():
            now = time.time()

            if PI_CLIENT_OK and now - last_light_time >= LIGHT_INTERVAL:
                # ※ 조명 자동 제어 임시 비활성화 (DB 상태 초기화 후 재활성화)
                # try:
                #     control_light()
                # except Exception as e:
                #     print(f"[RUN] 조명 제어 오류: {e}")
                last_light_time = now

            if now - last_growth_time >= GROWTH_INTERVAL:
                _send_growth_records(tx)
                last_growth_time = now

            time.sleep(5)

    aux_thread = threading.Thread(
        target=_aux_loop, daemon=True, name="AuxLoop"
    )
    aux_thread.start()

    print("\n[RUN] 모든 모듈 시작 완료 — AI 파이프라인 실행\n")

    # ── 메인 파이프라인 실행 (블로킹) ────────────────────────────────────
    # demo_pipeline.run()이 메인 루프를 담당
    # 종료 시 (q키 또는 Ctrl+C) 반환됨
    try:
        # run.py에서 이미 실제 센서를 읽고 있으므로,
        # demo_pipeline.py에서는 /dev/ttyACM0를 다시 열지 않게 함
        args.mock_sensor = True
        run_pipeline(args)
    except SystemExit:
        pass
    finally:
        sensor.stop()
        tx.print_stats()
        print("[RUN] 종료 완료")


if __name__ == "__main__":
    main()