"""
light_timer.py
시간대별 조명 자동 제어 — 서버 설정값 연동

서버 설정 페이지에서 변경한 점등/소등 시각이 자동으로 반영됩니다.

수정 내역:
  - toggle-device 대신 command_poller의 set_relay() 직접 호출로 변경
    → 토글 방식은 현재 상태를 모르면 반대로 동작하는 버그 발생
  - _last_light_state 초기화 시 현재 시각 기준 올바른 상태로 초기화
    → run.py 시작 시 불필요한 토글 방지
  - 서버 설정 조회 실패 시 config.yaml 기본값(on=8, off=20) 사용
"""

import time
import requests
from datetime import datetime
from config import BASE_URL, HEADERS, TANK_ID

_DEFAULT_ON_HOUR  = 8
_DEFAULT_OFF_HOUR = 20

_last_light_state:    bool | None = None   # None = 아직 미확인
_cached_settings:     dict | None = None
_settings_fetched_at: float       = 0
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
        data = res.json()
        # 서버 응답이 {"light": {...}} 또는 {"on_hour": ..., "off_hour": ...} 두 형태 모두 처리
        settings = data.get('light') or data
        _cached_settings     = settings
        _settings_fetched_at = now
        on  = settings.get('on_hour',  _DEFAULT_ON_HOUR)
        off = settings.get('off_hour', _DEFAULT_OFF_HOUR)
        print(f"[LIGHT] 서버 설정 로드 — 점등: {on}시 / 소등: {off}시")
        return _cached_settings
    except Exception as e:
        print(f"[LIGHT] 설정 조회 실패 (기본값 사용 — on={_DEFAULT_ON_HOUR}, off={_DEFAULT_OFF_HOUR}): {e}")
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
    """
    현재 시각 기준으로 조명 ON/OFF를 판단하고 set_relay()로 직접 제어.

    toggle-device 방식 대신 set_relay()를 사용하여 현재 상태에 관계없이
    올바른 상태로 강제 설정합니다. (멱등성 보장)
    """
    global _last_light_state
    on_hour, off_hour, auto = _get_hours()

    if not auto:
        return None   # 수동 모드면 무시

    target = on_hour <= datetime.now().hour < off_hour

    # 상태가 변경될 때만 릴레이 제어 (채터링 방지)
    if _last_light_state == target:
        return None

    try:
        from command_poller import set_relay
        set_relay("LIGHT", target)
        _last_light_state = target
        print(f"[LIGHT] {datetime.now().strftime('%H:%M')} 조명 → {'ON' if target else 'OFF'} "
              f"(설정: {on_hour}~{off_hour}시)")
        return target
    except ImportError:
        # command_poller를 import할 수 없는 경우 REST API fallback
        try:
            res = requests.post(
                f"{BASE_URL}/monitoring/api/device-control/{TANK_ID}/",
                json={"device_type": "LIGHT", "is_on": target},
                headers=HEADERS, timeout=5,
            )
            res.raise_for_status()
            _last_light_state = target
            print(f"[LIGHT] {datetime.now().strftime('%H:%M')} 조명 → {'ON' if target else 'OFF'} "
                  f"(API fallback, 설정: {on_hour}~{off_hour}시)")
            return target
        except Exception as e:
            print(f"[LIGHT] 조명 제어 오류 (API fallback 실패): {e}")
            return None
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
