"""
main.py
Pi 메인 루프 — 전체 자동화 통합

제출본 정리 원칙:
  - 센서값이 없을 때 정상값을 임의 생성하지 않는다.
  - 실제 AI 분석 결과가 없으면 행동/성장 데이터를 서버에 전송하지 않는다.
  - ESP32의 `turb` 채널은 현재 TDS(ppm) 센서값으로 취급한다.
"""

import time
import signal
import sys

from config                 import TANK_ID
from serial_reader          import SerialReader
from sensor_sender          import send_sensor
from behavior_sender        import send_behavior
from growth_sender          import send_growth
from pattern_sender         import ActivityPatternAnalyzer, analyze_and_send
from feeding_controller     import FeedingController
from light_timer            import control_light, get_next_change
from water_change_detector  import WaterChangeDetector
from register_pi            import register_pi_ip
from command_poller         import start_polling

# ── 주기 설정 (초) ─────────────────────────────
SENSOR_INTERVAL   = 10
BEHAVIOR_INTERVAL = 30
LIGHT_INTERVAL    = 60
GROWTH_INTERVAL   = 3600
PATTERN_INTERVAL  = 86400


def on_exit(sig, frame):
    print("\n[MAIN] 종료 신호 수신 — 정리 중...")
    reader = globals().get("serial_reader")
    if reader is not None:
        reader.close()
    sys.exit(0)


signal.signal(signal.SIGINT, on_exit)
signal.signal(signal.SIGTERM, on_exit)


def get_behavior_result() -> dict | None:
    """
    실제 YOLO/ByteTrack 분석 모듈의 결과를 반환하는 연결 지점.

    발표용 고정값은 제거했다. 실제 분석 모듈이 연결되지 않은 상태에서는
    가짜 행동 데이터를 서버에 저장하지 않기 위해 None을 반환한다.
    """
    return None


def get_growth_result() -> list[dict]:
    """
    실제 개체별 성장 분석 결과를 반환하는 연결 지점.

    발표용 Fish 1 고정 체장 데이터는 제거했다. 실제 분석 결과가 없으면
    빈 목록을 반환하여 서버에 임의 성장 기록을 만들지 않는다.
    """
    return []


def _sensor_payload(sensor_data: dict) -> dict | None:
    """필수 센서값이 모두 있을 때만 서버 전송용 값을 만든다."""
    key_map = {
        "temp": "temperature",
        "ph": "ph",
        "do": "dissolved_oxygen",
        "turb": "tds_ppm",
        "level": "water_level",
    }
    missing = [key for key in key_map if sensor_data.get(key) is None]
    if missing:
        print(f"[MAIN] 센서 필수값 누락 — 전송 생략: {', '.join(missing)}")
        return None

    return {
        "temperature": sensor_data["temp"],
        "ph": sensor_data["ph"],
        "dissolved_oxygen": sensor_data["do"],
        "tds_ppm": sensor_data["turb"],
        "water_level": sensor_data["level"],
    }


if __name__ == "__main__":
    print(f"[MAIN] 어항 자동 사육 시스템 시작 — TANK_ID={TANK_ID}")
    register_pi_ip()
    start_polling(interval=4.0)

    serial_reader         = SerialReader()
    pattern_analyzer      = ActivityPatternAnalyzer()
    feeding_controller    = FeedingController()
    water_change_detector = WaterChangeDetector()

    last_sensor_time   = 0
    last_behavior_time = 0
    last_light_time    = 0
    last_growth_time   = 0
    last_pattern_time  = 0

    print(f"[LIGHT] {get_next_change()}")

    while True:
        now = time.time()

        if now - last_sensor_time >= SENSOR_INTERVAL:
            sensor_data = serial_reader.read()
            if sensor_data:
                payload = _sensor_payload(sensor_data)
                if payload:
                    send_sensor(**payload)
                    result = water_change_detector.update(sensor_data["level"])
                    if result == "WATER_CHANGE_DETECTED":
                        print("[MAIN] 환수 완료 자동 기록됨!")
            else:
                print("[MAIN] 센서 데이터 없음 (ESP32 연결 확인)")
            last_sensor_time = now

        if now - last_behavior_time >= BEHAVIOR_INTERVAL:
            behavior = get_behavior_result()
            if behavior:
                send_behavior(**behavior)
                pattern_analyzer.record(behavior["activity_level"])

                growth_data = get_growth_result()
                if growth_data:
                    # 실제 행동/성장 결과가 모두 있을 때만 급이 판단을 수행한다.
                    feeding_controller.execute_feed(
                        behavior=behavior,
                        sensor={},
                        growth=growth_data[0],
                    )
            last_behavior_time = now

        if now - last_light_time >= LIGHT_INTERVAL:
            control_light()
            last_light_time = now

        if now - last_growth_time >= GROWTH_INTERVAL:
            for fish in get_growth_result():
                send_growth(**fish)
            last_growth_time = now

        if now - last_pattern_time >= PATTERN_INTERVAL:
            print("[MAIN] 24시간 활동 패턴 분석 시작...")
            analyze_and_send(pattern_analyzer)
            last_pattern_time = now

        time.sleep(1)
