"""
run.py — Goldfish AI 통합 메인 루프
금붕어 자동 사육 AI 시스템 (v2.0)

통합 실행 원칙:
  - SensorReader는 run.py에서 1회만 시작한다.
  - demo_pipeline.py는 run.py가 넘긴 shared_sensor를 재사용한다.
  - ServerTx도 run.py에서 1회만 만들고 demo_pipeline.py에는 shared_tx로 전달한다.
  - Ctrl+C는 stop_event + KeyboardInterrupt로 파이프라인 finally 정리를 보장한다.
"""

from __future__ import annotations

import argparse
import csv
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

# ── 경로 설정 ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PI_CLIENT = ROOT / "pi_client"
if PI_CLIENT.exists() and str(PI_CLIENT) not in sys.path:
    sys.path.insert(0, str(PI_CLIENT))

# ── goldfish_ai imports ───────────────────────────────────────────────────
from scripts.demo_pipeline import get_stream_frame, load_config, run as run_pipeline
from scripts.sensor_reader import SensorReader
from scripts.behavior_bridge import get_bridge
from scripts.decision import DecisionEngine
from scripts.server_tx import ServerTx

# ── pi_client imports ─────────────────────────────────────────────────────
try:
    from command_poller import start_polling
    from register_pi import get_local_ip, register_pi_ip
    from light_timer import get_next_change
    PI_CLIENT_OK = True
except ImportError as e:
    print(f"[RUN] pi_client import 실패 → 해당 기능 비활성화: {e}")
    PI_CLIENT_OK = False

    def get_local_ip() -> str:
        return _detect_local_ip()


LIGHT_INTERVAL = 60
DECISION_INTERVAL = 10
STREAM_PORT = 8080
SENSOR_LOG_PATH = Path("data/sensor_log.csv")

_stop_event = threading.Event()
_stream_server: HTTPServer | None = None


def _detect_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _on_exit(sig, frame):
    """Ctrl+C/SIGTERM 처리.

    기존 문제는 커스텀 signal handler가 KeyboardInterrupt를 막아서
    model.track()/capture 루프가 계속 도는 것이었다. stop_event를 세운 뒤
    KeyboardInterrupt를 발생시켜 run_pipeline의 finally 정리가 실행되게 한다.
    """
    if not _stop_event.is_set():
        print("\n[RUN] 종료 신호 수신 — 정리 중...")
    _stop_event.set()
    raise KeyboardInterrupt


signal.signal(signal.SIGINT, _on_exit)
signal.signal(signal.SIGTERM, _on_exit)


def load_raw_config(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        print(f"[RUN] 경고: {path} 없음 → 기본값 사용")
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class _MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        # 서버/프론트 코드가 /stream.mjpg를 쓰는 경우도 있어 둘 다 허용한다.
        if self.path not in ("/video_feed", "/stream.mjpg"):
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("ngrok-skip-browser-warning", "true")
        self.end_headers()

        try:
            while not _stop_event.is_set():
                frame = get_stream_frame()
                if frame:
                    self.wfile.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    )
                time.sleep(0.07)
        except Exception:
            pass


def _start_stream_server() -> HTTPServer:
    server = HTTPServer(("0.0.0.0", STREAM_PORT), _MJPEGHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="MJPEGStream")
    t.start()
    ip = get_local_ip() if PI_CLIENT_OK else _detect_local_ip()
    print(f"[Stream] MJPEG 스트리밍 시작 → http://{ip}:{STREAM_PORT}/video_feed")
    print(f"[Stream] 호환 URL              → http://{ip}:{STREAM_PORT}/stream.mjpg")
    return server


def append_sensor_log(sensor_data):
    SENSOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = SENSOR_LOG_PATH.exists()
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "temperature_c": getattr(sensor_data, "temperature_c", ""),
        "ph": getattr(sensor_data, "ph", ""),
        "do_mg_l": getattr(sensor_data, "do_mg_l", ""),
        "turbidity_ntu": getattr(sensor_data, "turbidity_ntu", ""),
        "level": getattr(sensor_data, "level", ""),
        "sensor_valid": getattr(sensor_data, "valid", ""),
    }
    with open(SENSOR_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "temperature_c",
                "ph",
                "do_mg_l",
                "turbidity_ntu",
                "level",
                "sensor_valid",
            ],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)



def _decision_loop(
    sensor: SensorReader,
    engine: DecisionEngine,
    tx: ServerTx,
    server_enabled: bool,
    event_log_enabled: bool,
):
    print("[Decision] 제어 판단 루프 시작 (A 방식 — 서버 우선)")
    while not _stop_event.is_set():
        try:
            sensor_data = sensor.get_latest()
            behavior = get_bridge().get_latest()
            result = engine.decide(sensor_data, behavior)

            if sensor_data.valid:
                append_sensor_log(sensor_data)
                if server_enabled:
                    tx.send_sensor(sensor_data)

            if result.alerts:
                for alert in result.alerts:
                    print(f"[Decision] ⚠️  {alert}")
                    if event_log_enabled:
                        tx.send_event_log(
                            level="WARNING" if not result.behavior_ok else "INFO",
                            message=alert,
                        )

            if result.water_score < 50 and event_log_enabled:
                tx.send_event_log(
                    level="DANGER",
                    message=f"수질 점수 위험: {result.water_score}/100",
                )

        except Exception as e:
            if not _stop_event.is_set():
                print(f"[Decision] 오류: {e}")

        _stop_event.wait(DECISION_INTERVAL)


def main():
    global _stream_server

    parser = argparse.ArgumentParser(description="Goldfish AI 통합 메인")
    parser.add_argument("--source", default="0")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--mock-sensor", action="store_true")
    parser.add_argument("--no-server", action="store_true", help="서버 전송 비활성화")
    args = parser.parse_args()

    raw = load_raw_config(args.config)
    server_cfg = raw.get("server", {})
    server_enabled = bool(server_cfg.get("enabled", False)) and not args.no_server
    server_mock = bool(server_cfg.get("mock", True))
    event_log_enabled = bool(server_cfg.get("event_log_enabled", False))

    # demo_pipeline 설정 검증용 로드
    load_config(args.config)

    print(f"\n{'=' * 60}")
    print("  Goldfish AI — 통합 메인 루프")
    print(f"{'=' * 60}")
    print(f"  config     : {args.config}")
    print(f"  mock-sensor: {args.mock_sensor}")
    print(f"  server     : {'활성화' if server_enabled else '비활성화'}")
    print(f"  server_mock: {server_mock}")
    print(f"  event_log  : {'활성화' if event_log_enabled else '비활성화'}")
    print(f"  pi_client  : {'OK' if PI_CLIENT_OK else '미연결'}")

    sensor = None
    tx = None

    try:
        if PI_CLIENT_OK and server_enabled:
            register_pi_ip(stream_port=STREAM_PORT)
            print(f"  조명 예정: {get_next_change()}")
            start_polling(interval=4.0)
            print("[RUN] 장치 명령 polling 시작")

        sensor_cfg = raw.get("sensor", {})
        sensor = SensorReader(
            port=sensor_cfg.get("port", "/dev/ttyACM0"),
            baudrate=sensor_cfg.get("baudrate", 115200),
            timeout=sensor_cfg.get("timeout_sec", 1.0),
            sample_count=sensor_cfg.get("sample_count", 1),
            mock=args.mock_sensor,
        )
        sensor.start()

        tx = ServerTx(
            mock=(not server_enabled) or server_mock,
            event_log_enabled=event_log_enabled,
        )

        engine = DecisionEngine()
        decision_thread = threading.Thread(
            target=_decision_loop,
            args=(sensor, engine, tx, server_enabled, event_log_enabled),
            daemon=True,
            name="DecisionLoop",
        )
        decision_thread.start()

        _stream_server = _start_stream_server()

        last_light_time = 0.0

        def _aux_loop():
            nonlocal last_light_time
            while not _stop_event.is_set():
                now = time.time()

                if PI_CLIENT_OK and now - last_light_time >= LIGHT_INTERVAL:
                    # 조명 자동 제어는 DB 상태 정리 후 재활성화
                    last_light_time = now

                _stop_event.wait(5)

        aux_thread = threading.Thread(target=_aux_loop, daemon=True, name="AuxLoop")
        aux_thread.start()

        print("\n[RUN] 모든 모듈 시작 완료 — AI 파이프라인 실행\n")

        args.shared_sensor = sensor
        args.shared_tx = tx
        args.stop_event = _stop_event
        # 통합 실행에서는 SensorReader/ServerTx를 새로 만들지 않는다.
        args.pipeline_server_enabled = server_enabled
        args.pipeline_send_sensor = False      # 센서 전송은 decision_loop 한 곳에서만 수행
        args.pipeline_send_behavior = server_enabled
        args.pipeline_register_pi = False      # IP 등록은 run.py 한 곳에서만 수행

        run_pipeline(args)

    except KeyboardInterrupt:
        _stop_event.set()
        print("\n[RUN] KeyboardInterrupt — 종료 처리 진행")

    finally:
        _stop_event.set()

        if sensor is not None:
            sensor.stop()

        if _stream_server is not None:
            try:
                _stream_server.shutdown()
                _stream_server.server_close()
            except Exception:
                pass

        if tx is not None:
            tx.print_stats()

        print("[RUN] 종료 완료")


if __name__ == "__main__":
    main()
