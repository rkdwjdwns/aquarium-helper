"""
command_poller.py
서버에서 장치 제어 명령을 3~5초마다 polling 하여 릴레이를 제어합니다.
GET /api/commands/{tank_id}/

[릴레이 채널 매핑]
- 4채널 릴레이: CH1=HEATER, CH2=COOLING, CH3=AIR_PUMP, CH4=LIGHT
"""

import time
import threading
import requests
import lgpio
from config import BASE_URL, HEADERS, TANK_ID

# 릴레이 핀 번호 (BCM 기준)
RELAY_PINS = {
    "HEATER":   17,
    "COOLING":  27,
    "AIR_PUMP": 22,
    "LIGHT":    23,
}

_gpio_handle = None
_prev_states: dict[str, bool] = {}

def _init_gpio():
    """GPIO 초기화 및 핀 설정"""
    global _gpio_handle
    if _gpio_handle is not None:
        return
    
    try:
        _gpio_handle = lgpio.gpiochip_open(0)  # gpiochip0 사용
        for pin in RELAY_PINS.values():
            lgpio.gpio_claim_output(_gpio_handle, pin, 1)  # 1=HIGH=OFF (활성 LOW 릴레이 기준)
        print("[RELAY] GPIO 초기화 완료")
    except Exception as e:
        print(f"[RELAY] GPIO 초기화 실패: {e}")


def apply_commands(devices: list[dict]):
    """서버에서 수신한 장치 명령을 실제 릴레이에 적용"""
    for device in devices:
        dtype   = device.get("type")
        is_on   = device.get("is_on", False)
        is_auto = device.get("is_auto", True)

        if not dtype:
            continue
            
        # 조명 제어는 light_timer.py가 전담하므로 스킵
        if dtype == "LIGHT":
            continue
            
        # 수동 제어(is_auto=False) 상태인 경우 해당 장치 스킵
        if not is_auto:
            continue
            
        # 이전 상태와 다를 때만 릴레이 제어 수행
        if _prev_states.get(dtype) != is_on:
            set_relay(dtype, is_on)
            _prev_states[dtype] = is_on

def poll_once() -> list[dict] | None:
    """서버로부터 장치 제어 명령을 1회 Polling"""
    try:
        res = requests.get(
            f"{BASE_URL}/api/commands/{TANK_ID}/",
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        return res.json().get("devices", [])
        
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
    """백그라운드 스레드에서 Polling 작업을 시작"""
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

if __name__ == "__main__":
    print("명령 polling 시작 (Ctrl+C로 종료)")
    try3
        while True:
            devices = poll_once()
            if devices:
                print(f"[POLLER] 장치 {len(devices)}개 수신")
                apply_commands(devices)
            time.sleep(4)
    except KeyboardInterrupt:
        print("\n[POLLER] 프로그램 종료")
    finally:
        # 프로그램 종료 시 리소스 해제
        if _gpio_handle:
            lgpio.gpiochip_close(_gpio_handle)
            print("[RELAY] GPIO 리소스 해제 완료")
