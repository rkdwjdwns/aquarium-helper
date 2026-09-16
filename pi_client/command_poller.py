"""
command_poller.py — 서버 장치 상태를 Raspberry Pi 릴레이에 반영.

현재 졸업작품에서 실제 제어 대상으로 확정한 장치는 HEATER / COOLING / LIGHT이다.
- HEATER, COOLING: 서버 명령 polling으로 적용
- LIGHT: local light_timer + AI REST가 단독으로 소유하여 서버 polling에서 제외

AIR_PUMP / FEEDER는 서버에 과거 데이터가 남아 있어도 Pi에서 실행하지 않는다.
AIR_PUMP는 실제 수조에서 상시 가동이다.
"""
import threading
import time
import requests
from config import BASE_URL, HEADERS, TANK_ID

ALLOWED_DEVICES = {"HEATER", "COOLING", "FILTER", "LIGHT"}
POLLABLE_DEVICES = {"HEATER", "COOLING", "FILTER"}  # LIGHT is owned locally by light_timer + AI REST

# 실제 GPIO 사용 시 환경에 맞게 주석 해제/검증한다.
# import RPi.GPIO as GPIO
# RELAY_PINS = {"HEATER": 17, "COOLING": 18, "LIGHT": 24}
# GPIO.setmode(GPIO.BCM)
# for pin in RELAY_PINS.values():
#     GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
# def set_relay(device_type: str, is_on: bool):
#     pin = RELAY_PINS.get(device_type)
#     if pin is not None:
#         GPIO.output(pin, GPIO.LOW if is_on else GPIO.HIGH)


def set_relay(device_type: str, is_on: bool):
    """장치 ON/OFF. 현재 저장소 기본은 GPIO 연결 전 시뮬레이션 출력."""
    if device_type not in ALLOWED_DEVICES:
        return
    state = "ON" if is_on else "OFF"
    print(f"  [RELAY] {device_type:<10} -> {state}")


_prev_states: dict[str, bool] = {}


def apply_commands(devices: list[dict]):
    """서버가 소유하는 HEATER/COOLING 자동 상태만 반영한다."""
    for device in devices:
        dtype = str(device.get("type") or "").upper()
        if dtype not in POLLABLE_DEVICES:
            continue
        is_on = bool(device.get("is_on", False))
        is_auto = bool(device.get("is_auto", True))
        if not is_auto:
            continue
        if _prev_states.get(dtype) != is_on:
            set_relay(dtype, is_on)
            _prev_states[dtype] = is_on


def poll_once() -> list[dict] | None:
    try:
        res = requests.get(
            f"{BASE_URL}/api/commands/{TANK_ID}/",
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        return res.json().get("devices", [])
    except requests.exceptions.Timeout:
        print("[POLLER] 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[POLLER] 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[POLLER] HTTP 오류: {e.response.status_code}")
    except Exception as e:
        print(f"[POLLER] 오류: {e}")
    return None


def start_polling(interval: float = 4.0, daemon: bool = True):
    def _loop():
        print(f"[POLLER] 시작 - {interval}초 간격, 서버 polling 장치={sorted(POLLABLE_DEVICES)}")
        while True:
            devices = poll_once()
            if devices is not None:
                apply_commands(devices)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=daemon)
    t.start()
    return t


if __name__ == "__main__":
    print("명령 polling 시작 (Ctrl+C 종료)")
    try:
        while True:
            devices = poll_once()
            if devices is not None:
                apply_commands(devices)
            time.sleep(4)
    except KeyboardInterrupt:
        print("\n[POLLER] 종료")
