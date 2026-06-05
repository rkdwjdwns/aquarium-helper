"""
command_poller.py
서버에서 장치 제어 명령을 3~5초마다 polling
GET /api/commands/{tank_id}/

릴레이 채널 매핑:
  2채널 릴레이: CH1=HEATER, CH2=COOLING
  4채널 릴레이: CH3=FILTER, CH4=AIR_PUMP
"""

import time
import threading
import requests
import RPi.GPIO as GPIO
from config import BASE_URL, HEADERS, TANK_ID

# ── 릴레이 핀 설정 ─────────────────────────────────────────
RELAY_PINS = {
    "HEATER":   17,   # 2채널 CH1
    "COOLING":  18,   # 2채널 CH2
    "FILTER":   27,   # 4채널 CH3
    "AIR_PUMP": 22,   # 4채널 CH4
    "FEEDER":   23,
    "LIGHT":    24,
}

GPIO.setmode(GPIO.BCM)
for pin in RELAY_PINS.values():
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)   # 릴레이는 LOW=ON이 일반적


def set_relay(device_type: str, is_on: bool):
    pin = RELAY_PINS.get(device_type)
    if pin:
        GPIO.output(pin, GPIO.LOW if is_on else GPIO.HIGH)


# 이전 상태 저장 (변경 시에만 릴레이 동작)
_prev_states: dict[str, bool] = {}


def apply_commands(devices: list[dict]):
    """서버에서 받은 장치 목록을 릴레이에 적용합니다."""
    for device in devices:
        dtype   = device.get("type")
        is_on   = device.get("is_on", False)
        is_auto = device.get("is_auto", True)

        if not dtype:
            continue

        # 자동 모드일 때만 서버 명령 반영
        if not is_auto:
            continue

        # 상태가 변경된 경우에만 릴레이 동작 (채터링 방지)
        if _prev_states.get(dtype) != is_on:
            set_relay(dtype, is_on)
            _prev_states[dtype] = is_on


def poll_once() -> list[dict] | None:
    """서버에서 제어 명령을 한 번 가져옵니다."""
    try:
        res = requests.get(
            f"{BASE_URL}/api/commands/{TANK_ID}/",
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        return data.get("devices", [])

    except requests.exceptions.Timeout:
        print("[POLLER] 오류: 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[POLLER] 오류: 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[POLLER] HTTP 오류: {e.response.status_code}")
    except Exception as e:
        print(f"[POLLER] 알 수 없는 오류: {e}")

    return None


def start_polling(interval: float = 4.0, daemon: bool = True):
    """
    백그라운드 스레드로 polling을 시작합니다.

    Args:
        interval : polling 주기 (초, 기본 4초)
        daemon   : True면 메인 프로세스 종료 시 같이 종료
    """
    def _loop():
        print(f"[POLLER] 시작 — {interval}초 간격으로 명령 수신")
        while True:
            devices = poll_once()
            if devices is not None:
                apply_commands(devices)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=daemon)
    t.start()
    return t


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    print("명령 polling 시작 (Ctrl+C로 종료)")
    try:
        while True:
            devices = poll_once()
            if devices:
                print(f"[POLLER] 장치 {len(devices)}개 수신")
                apply_commands(devices)
            time.sleep(4)
    except KeyboardInterrupt:
        print("\n[POLLER] 종료")
        GPIO.cleanup()