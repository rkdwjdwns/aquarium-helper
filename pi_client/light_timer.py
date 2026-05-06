"""
light_timer.py
시간대별 조명 자동 제어 — 서버 설정값 연동

서버 설정 페이지에서 변경한 점등/소등 시각이 자동으로 반영됩니다.
"""

import time
import requests
from datetime import datetime
from config import BASE_URL, HEADERS, TANK_ID

_DEFAULT_ON_HOUR  = 8
_DEFAULT_OFF_HOUR = 20

_last_light_state:   bool | None = None
_cached_settings:    dict | None = None
_settings_fetched_at: float      = 0
_SETTINGS_TTL = 300   # 5분마다 서버 재조회


def _fetch_settings() -> dict:
    """서버에서 조명 설정값 가져오기 (5분 캐시)"""
    global _cached_settings, _settings_fetched_at
    now = time.time()
    if _cached_settings and (now - _settings_fetched_at) < _SETTINGS_TTL:
        return _cached_settings
    try:
        res = requests.get(
            f"{BASE_URL}/monitoring/settings/{TANK_ID}/api/",
            headers=HEADERS, timeout=5,
        )
        res.raise_for_status()
        _cached_settings     = res.json().get('light', {})
        _settings_fetched_at = now
        on  = _cached_settings.get('on_hour',  _DEFAULT_ON_HOUR)
        off = _cached_settings.get('off_hour', _DEFAULT_OFF_HOUR)
        print(f"[LIGHT] 서버 설정 로드 — 점등: {on}시 / 소등: {off}시")
        return _cached_settings
    except Exception as e:
        print(f"[LIGHT] 설정 조회 실패 (기본값 사용): {e}")
        return {}


def _get_hours() -> tuple[int, int, bool]:
    s = _fetch_settings()
    return (
        s.get('on_hour',  _DEFAULT_ON_HOUR),
        s.get('off_hour', _DEFAULT_OFF_HOUR),
        s.get('auto',     True),
    )


def should_light_be_on() -> bool:
    on_hour, off_hour, _ = _get_hours()
    return on_hour <= datetime.now().hour < off_hour


def control_light() -> bool | None:
    global _last_light_state
    on_hour, off_hour, auto = _get_hours()

    if not auto:
        return None   # 수동 모드면 무시

    target = on_hour <= datetime.now().hour < off_hour
    if _last_light_state == target:
        return None

    try:
        headers = {k: v for k, v in HEADERS.items() if k != "Content-Type"}
        res     = requests.post(
            f"{BASE_URL}/monitoring/toggle-device/{TANK_ID}/",
            data={"device_type": "LIGHT"}, headers=headers, timeout=5,
        )
        if res.json().get("is_on") != target:
            requests.post(
                f"{BASE_URL}/monitoring/toggle-device/{TANK_ID}/",
                data={"device_type": "LIGHT"}, headers=headers, timeout=5,
            )
        _last_light_state = target
        print(f"[LIGHT] {datetime.now().strftime('%H:%M')} 조명 → {'ON' if target else 'OFF'} "
              f"(설정: {on_hour}~{off_hour}시)")
        return target
    except Exception as e:
        print(f"[LIGHT] 조명 제어 오류: {e}")
        return None


def get_next_change() -> str:
    on_hour, off_hour, auto = _get_hours()
    if not auto:
        return "조명 자동 제어 꺼짐"
    hour = datetime.now().hour
    if on_hour <= hour < off_hour:
        return f"소등 예정: {off_hour:02d}:00"
    elif hour < on_hour:
        return f"점등 예정: {on_hour:02d}:00"
    return f"점등 예정: 내일 {on_hour:02d}:00"


if __name__ == "__main__":
    print(f"[LIGHT] 현재 시각: {datetime.now().strftime('%H:%M')}")
    print(f"[LIGHT] {get_next_change()}")
    control_light()
