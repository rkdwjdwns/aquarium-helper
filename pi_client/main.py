"""
main.py
Pi 메인 루프 — 전체 자동화 통합

자동화 항목:
  - 수질 센서 수집 및 전송 (10초)
  - AI 행동 분석 전송 (30초)
  - 자동 급이 (FRS/행동 기반)
  - 조명 타이머 (08:00 점등 / 20:00 소등)
  - 환수 자동 감지 (수위 변화 패턴)
  - 성장 기록 (1시간)
  - 활동 패턴 분석 (24시간)
  - 장치 명령 polling (4초, 백그라운드)
  - Pi IP 자동 등록 (시작 시)
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
    serial_reader.close()
    sys.exit(0)

signal.signal(signal.SIGINT,  on_exit)
signal.signal(signal.SIGTERM, on_exit)


def get_behavior_result() -> dict | None:
    # TODO: from yolo_analyzer import FishAnalyzer
    return {
        "fish_count": 3, "overlap_frames": 1,
        "activity_level": 14.5, "abr_score": 0.04,
        "dominant_zone": "MID",
        "zone_top_ratio": 0.1, "zone_mid_ratio": 0.7, "zone_bot_ratio": 0.2,
        "size_index": 7.8, "feeding_score": 0,
        "status": "GOOD", "is_anomaly": False, "note": "",
    }


def get_growth_result() -> list[dict]:
    # TODO: from yolo_analyzer import get_growth_data
    return [{"fish_id": 1, "size_index": 7.8, "estimated_length": 2.1,
             "growth_rate": 0.05, "growth_stage": "FRY", "recommended_feed_g": 0.01}]


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
                send_sensor(
                    temperature      = sensor_data.get("temp",  22.0),
                    ph               = sensor_data.get("ph",     7.4),
                    dissolved_oxygen = sensor_data.get("do",     6.0),
                    turbidity        = sensor_data.get("turb",  10.0),
                    water_level      = sensor_data.get("level", 100.0),
                )
                result = water_change_detector.update(sensor_data.get("level", 100.0))
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
                sensor_data = serial_reader.read() or {}
                growth_data = get_growth_result()
                if growth_data:
                    feeding_controller.execute_feed(
                        behavior = behavior,
                        sensor   = {"turbidity": sensor_data.get("turb", 10.0)},
                        growth   = growth_data[0],
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
