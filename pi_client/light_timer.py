"""light_timer.py

Aquarium light controller with two layers:
1) Normal schedule control from server settings.
2) Local AI REST override from calibrated ABR analysis.

AI REST is a temporary supervisory override. It can force the light OFF while the
normal schedule wants it ON. When REST ends, control returns to the schedule.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import requests

from config import BASE_URL, HEADERS, TANK_ID

_DEFAULT_ON_HOUR = 8
_DEFAULT_OFF_HOUR = 16

_last_light_state: bool | None = None
_cached_settings: dict | None = None
_settings_fetched_at: float = 0
_SETTINGS_TTL = 300

_ai_rest_active = False
_ai_rest_reason = ""
_lock = threading.RLock()


def _fetch_settings() -> dict:
    """서버에서 조명 설정값 가져오기 (5분 캐시)."""
    global _cached_settings, _settings_fetched_at
    now = time.time()
    if _cached_settings and (now - _settings_fetched_at) < _SETTINGS_TTL:
        return _cached_settings
    try:
        res = requests.get(
            f"{BASE_URL}/settings/{TANK_ID}/api/",
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        settings = data.get("light") or data
        _cached_settings = settings
        _settings_fetched_at = now
        on = settings.get("on_hour", _DEFAULT_ON_HOUR)
        off = settings.get("off_hour", _DEFAULT_OFF_HOUR)
        print(f"[LIGHT] 서버 설정 로드 - 점등: {on}시 / 소등: {off}시")
        return _cached_settings
    except Exception as e:
        print(
            "[LIGHT] 설정 조회 실패 "
            f"(기본값 사용 - on={_DEFAULT_ON_HOUR}, off={_DEFAULT_OFF_HOUR}): {e}"
        )
        return {}


def _get_hours() -> tuple[int, int, bool]:
    s = _fetch_settings()
    return (
        int(s.get("on_hour", _DEFAULT_ON_HOUR)),
        int(s.get("off_hour", _DEFAULT_OFF_HOUR)),
        bool(s.get("auto", True)),
    )


def should_light_be_on() -> bool:
    """AI override를 제외한 현재 정상 스케줄의 목표 상태."""
    on_hour, off_hour, auto = _get_hours()
    if not auto:
        return False
    return on_hour <= datetime.now().hour < off_hour


def is_ai_rest_active() -> bool:
    with _lock:
        return _ai_rest_active


def get_light_control_status() -> dict:
    on_hour, off_hour, auto = _get_hours()
    schedule_on = bool(auto and on_hour <= datetime.now().hour < off_hour)
    with _lock:
        return {
            "auto": auto,
            "on_hour": on_hour,
            "off_hour": off_hour,
            "schedule_on": schedule_on,
            "ai_rest_active": _ai_rest_active,
            "ai_rest_reason": _ai_rest_reason,
            "effective_target": False if _ai_rest_active and auto else schedule_on,
            "last_light_state": _last_light_state,
        }


def _apply_light(target: bool, reason: str, *, force_refresh: bool = False) -> bool | None:
    global _last_light_state

    if not force_refresh and _last_light_state == target:
        return None

    try:
        from command_poller import set_relay

        set_relay("LIGHT", target)
        _last_light_state = target
        print(
            f"[LIGHT] {datetime.now().strftime('%H:%M:%S')} 조명 -> "
            f"{'ON' if target else 'OFF'} ({reason})"
        )
        return target
    except ImportError:
        # command_poller를 import할 수 없는 배포 형태를 위한 REST fallback.
        try:
            res = requests.post(
                f"{BASE_URL}/api/device-control/{TANK_ID}/",
                json={"device_type": "LIGHT", "is_on": target},
                headers=HEADERS,
                timeout=5,
            )
            res.raise_for_status()
            _last_light_state = target
            print(
                f"[LIGHT] {datetime.now().strftime('%H:%M:%S')} 조명 -> "
                f"{'ON' if target else 'OFF'} (API fallback / {reason})"
            )
            return target
        except Exception as e:
            print(f"[LIGHT] 조명 제어 오류 (API fallback 실패): {e}")
            return None
    except Exception as e:
        print(f"[LIGHT] 조명 제어 오류: {e}")
        return None


def control_light(*, force_refresh: bool = False) -> bool | None:
    """스케줄과 AI REST override를 합쳐 최종 LIGHT 상태를 적용한다."""
    on_hour, off_hour, auto = _get_hours()
    if not auto:
        return None

    schedule_target = on_hour <= datetime.now().hour < off_hour
    with _lock:
        rest_active = _ai_rest_active
        rest_reason = _ai_rest_reason

    if rest_active:
        target = False
        reason = f"AI REST override: {rest_reason or 'ABR 이상행동 지속'}"
    else:
        target = schedule_target
        reason = f"스케줄 {on_hour:02d}:00~{off_hour:02d}:00"

    return _apply_light(target, reason, force_refresh=force_refresh)


def set_ai_rest_mode(active: bool, reason: str = "") -> bool | None:
    """AI REST override를 설정하고 상태 변화 시 즉시 조명에 반영한다."""
    global _ai_rest_active, _ai_rest_reason

    active = bool(active)
    with _lock:
        changed = active != _ai_rest_active
        reason_changed = bool(reason) and reason != _ai_rest_reason
        _ai_rest_active = active
        if active:
            _ai_rest_reason = reason or _ai_rest_reason or "ABR 이상행동 지속"
        else:
            _ai_rest_reason = ""

    if changed:
        print(f"[LIGHT][AI] REST mode -> {'ON' if active else 'OFF'}")
        # Entering REST must turn the light off immediately; releasing REST must
        # immediately restore the current schedule target.
        return control_light(force_refresh=True)

    # Reason-only changes do not need a relay write.
    if reason_changed:
        print(f"[LIGHT][AI] REST reason update: {reason}")
    return None


def get_next_change() -> str:
    on_hour, off_hour, auto = _get_hours()
    if not auto:
        return "조명 자동 제어 꺼짐"
    if is_ai_rest_active():
        return "AI REST 중 - 종료 후 스케줄 복귀"
    hour = datetime.now().hour
    if on_hour <= hour < off_hour:
        return f"소등 예정: {off_hour:02d}:00"
    if hour < on_hour:
        return f"점등 예정: {on_hour:02d}:00"
    return f"점등 예정: 내일 {on_hour:02d}:00"


if __name__ == "__main__":
    print(f"[LIGHT] 현재 시각: {datetime.now().strftime('%H:%M')}")
    print(f"[LIGHT] {get_next_change()}")
    control_light()
