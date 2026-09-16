"""
feeding_controller.py
급이 자동화 판단 로직 — 서버 설정값 연동

제출본 정리:
  - 실제 탁도 센서가 없으므로 TDS를 탁도처럼 사용하지 않는다.
  - 급이 후 탁도/활동량/반응시간을 수식이나 0으로 만들어 저장하지 않는다.
  - 실제 GPIO 급이기 제어가 연결되지 않은 상태에서는 급이 이벤트를
    '실행 완료'로 기록하지 않는다.
"""

import time
import requests
from datetime import datetime
from dataclasses import dataclass, field

from config import BASE_URL, HEADERS, TANK_ID


# ── 성장 단계별 기준 ────────────────────────────
STAGE_CONFIG = {
    'FRY': {
        'length_range': (1.0, 3.0),
        'body_ratio': 0.06,
        'daily_feeds': 5,
        'min_interval': 2.5 * 3600,
        'max_amount_g': 0.05,
    },
    'YOUNG': {
        'length_range': (3.0, 7.0),
        'body_ratio': 0.04,
        'daily_feeds': 3,
        'min_interval': 5.0 * 3600,
        'max_amount_g': 0.3,
    },
    'ADULT': {
        'length_range': (7.0, 99.0),
        'body_ratio': 0.015,
        'daily_feeds': 2,
        'min_interval': 8.0 * 3600,
        'max_amount_g': 1.5,
    },
}

HUNGER_FRS_THRESHOLD  = 60
HUNGER_ZONE_THRESHOLD = 0.4

# ── 서버 설정 캐시 ─────────────────────────────
_cached_feeding_settings: dict | None = None
_feeding_fetched_at: float = 0
_SETTINGS_TTL = 300


def _fetch_feeding_settings() -> dict:
    """서버에서 급이 설정값 가져오기 (5분 캐시)."""
    global _cached_feeding_settings, _feeding_fetched_at

    now = time.time()
    if _cached_feeding_settings and (now - _feeding_fetched_at) < _SETTINGS_TTL:
        return _cached_feeding_settings

    try:
        # BASE_URL 자체가 이미 /monitoring 을 포함하므로 중복 경로를 붙이지 않는다.
        res = requests.get(
            f"{BASE_URL}/settings/{TANK_ID}/api/",
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        _cached_feeding_settings = res.json().get('feeding', {})
        _feeding_fetched_at = now
        print(
            f"[FEEDER] 서버 설정 로드 — "
            f"자동: {_cached_feeding_settings.get('auto', False)} / "
            f"1회: {_cached_feeding_settings.get('amount_g', '미설정')}g"
        )
        return _cached_feeding_settings
    except Exception as e:
        print(f"[FEEDER] 설정 조회 실패 — 자동 급이 판단 중지: {e}")
        return {}


def estimate_weight(length_cm: float) -> float:
    return round(0.01049 * (length_cm ** 3.14), 4)


def get_growth_stage(length_cm: float) -> str:
    if length_cm < 3.0:
        return 'FRY'
    if length_cm < 7.0:
        return 'YOUNG'
    return 'ADULT'


def calc_feed_amount(length_cm: float, fish_count: int = 1) -> dict:
    stage = get_growth_stage(length_cm)
    config = STAGE_CONFIG[stage]
    weight = estimate_weight(length_cm)

    settings = _fetch_feeding_settings()
    server_amount = settings.get('amount_g')

    if server_amount is not None:
        amount_per_fish = float(server_amount)
    else:
        amount_per_fish = round(weight * config['body_ratio'], 4)
        amount_per_fish = min(amount_per_fish, config['max_amount_g'])

    amount_total = round(amount_per_fish * fish_count, 4)
    daily_total = round(amount_total * config['daily_feeds'], 4)

    return {
        "stage": stage,
        "weight_g": weight,
        "amount_per_fish": amount_per_fish,
        "amount_total": amount_total,
        "daily_total": daily_total,
        "daily_feeds": config['daily_feeds'],
        "min_interval_h": config['min_interval'] / 3600,
    }


@dataclass
class FeedingController:
    last_feed_time: datetime | None = None
    today_feed_count: int = 0
    today_feed_total: float = 0.0
    last_reset_date: str = field(
        default_factory=lambda: datetime.now().strftime('%Y-%m-%d')
    )

    def _reset_daily_if_needed(self):
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self.last_reset_date:
            self.today_feed_count = 0
            self.today_feed_total = 0.0
            self.last_reset_date = today

    def _is_hunger_detected(self, behavior: dict) -> bool:
        frs = behavior.get('feeding_score')
        top_ratio = behavior.get('zone_top_ratio')

        if frs is None and top_ratio is None:
            return False

        return (
            (frs is not None and frs >= HUNGER_FRS_THRESHOLD)
            or (
                top_ratio is not None
                and top_ratio >= HUNGER_ZONE_THRESHOLD
            )
        )

    def _can_feed(self, stage: str) -> tuple[bool, str]:
        config = STAGE_CONFIG[stage]

        if self.last_feed_time:
            elapsed = (datetime.now() - self.last_feed_time).total_seconds()
            if elapsed < config['min_interval']:
                remain = int((config['min_interval'] - elapsed) / 60)
                return False, f"급이 간격 미달 ({remain}분 후 가능)"

        if self.today_feed_count >= config['daily_feeds']:
            return False, f"일일 최대 횟수 초과 ({config['daily_feeds']}회)"

        return True, ""

    def should_feed(
        self,
        behavior: dict,
        sensor: dict,
        growth: dict,
    ) -> tuple[bool, str]:
        self._reset_daily_if_needed()

        settings = _fetch_feeding_settings()
        if not settings:
            return False, "서버 급이 설정을 확인할 수 없음"

        auto = bool(settings.get('auto', False))
        if not auto:
            return False, "자동 급이 꺼짐 (서버 설정)"

        length = growth.get('estimated_length')
        if length is None:
            return False, "실제 성장 데이터 없음"

        if not self._is_hunger_detected(behavior):
            return False, "배고픔 미감지"

        stage = get_growth_stage(float(length))
        can_feed, reason = self._can_feed(stage)
        if not can_feed:
            return False, reason

        return True, "자동 급이 조건 충족"

    def execute_feed(self, behavior: dict, sensor: dict, growth: dict) -> bool:
        do_feed, reason = self.should_feed(behavior, sensor, growth)
        print(
            f"[FEEDER] 판단: "
            f"{'급이 조건 충족' if do_feed else '건너뜀'} — {reason}"
        )

        if not do_feed:
            return False

        length = growth.get('estimated_length')
        fish_count = behavior.get('fish_count')

        if length is None or fish_count is None or int(fish_count) <= 0:
            print("[FEEDER] 실제 성장/개체수 데이터가 없어 급이를 실행하지 않습니다.")
            return False

        feed_info = calc_feed_amount(float(length), int(fish_count))

        # 실제 GPIO/서보 구동이 연결되기 전에는 성공 이벤트를 만들지 않는다.
        print(
            "[FEEDER] 급이 조건은 충족했지만 실제 급이기 GPIO 제어가 "
            "연결되지 않아 실행/서버 기록을 생략합니다. "
            f"(계산 급이량: {feed_info['amount_total']}g)"
        )
        return False


if __name__ == "__main__":
    print(
        "feeding_controller.py는 실제 서버 설정/행동/성장 데이터를 사용합니다. "
        "발표용 임의 급이 테스트는 제거했습니다."
    )
