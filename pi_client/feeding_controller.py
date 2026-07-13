"""
feeding_controller.py
급이 자동화 로직 — 서버 설정값 연동

서버 설정 페이지에서 변경한 급이량/급이 시간이 자동으로 반영됩니다.
"""

import time
import requests
from datetime import datetime, date
from dataclasses import dataclass, field

from config         import BASE_URL, HEADERS, TANK_ID
from feeding_sender import send_feeding

# ── 성장 단계별 기준 (고정값) ──────────────────
STAGE_CONFIG = {
    'FRY':   {'length_range': (1.0, 3.0), 'body_ratio': 0.06, 'daily_feeds': 5, 'min_interval': 2.5*3600, 'max_amount_g': 0.05},
    'YOUNG': {'length_range': (3.0, 7.0), 'body_ratio': 0.04, 'daily_feeds': 3, 'min_interval': 5.0*3600, 'max_amount_g': 0.3},
    'ADULT': {'length_range': (7.0, 99.), 'body_ratio': 0.015,'daily_feeds': 2, 'min_interval': 8.0*3600, 'max_amount_g': 1.5},
}

OVERFEEDING_TURBIDITY = 80.0
DELTA_NTU_THRESHOLD   = 30.0
HUNGER_FRS_THRESHOLD  = 60
HUNGER_ZONE_THRESHOLD = 0.4

# ── 서버 설정 캐시 ─────────────────────────────
_cached_feeding_settings: dict | None = None
_feeding_fetched_at: float = 0
_SETTINGS_TTL = 300


def _fetch_feeding_settings() -> dict:
    """서버에서 급이 설정값 가져오기 (5분 캐시)"""
    global _cached_feeding_settings, _feeding_fetched_at
    now = time.time()
    if _cached_feeding_settings and (now - _feeding_fetched_at) < _SETTINGS_TTL:
        return _cached_feeding_settings
    try:
        res = requests.get(
            f"{BASE_URL}/monitoring/settings/{TANK_ID}/api/",
            headers=HEADERS, timeout=5,
        )
        res.raise_for_status()
        _cached_feeding_settings = res.json().get('feeding', {})
        _feeding_fetched_at      = now
        print(f"[FEEDER] 서버 설정 로드 — "
              f"자동: {_cached_feeding_settings.get('auto', True)} / "
              f"1회: {_cached_feeding_settings.get('amount_g', 0.1)}g")
        return _cached_feeding_settings
    except Exception as e:
        print(f"[FEEDER] 설정 조회 실패 (기본값 사용): {e}")
        return {}


def estimate_weight(length_cm: float) -> float:
    return round(0.01049 * (length_cm ** 3.14), 4)


def get_growth_stage(length_cm: float) -> str:
    if length_cm < 3.0:  return 'FRY'
    elif length_cm < 7.0: return 'YOUNG'
    return 'ADULT'


def calc_feed_amount(length_cm: float, fish_count: int = 1) -> dict:
    stage   = get_growth_stage(length_cm)
    config  = STAGE_CONFIG[stage]
    weight  = estimate_weight(length_cm)

    # 서버 설정의 1회 급이량이 있으면 우선 사용
    s = _fetch_feeding_settings()
    server_amount = s.get('amount_g')

    if server_amount:
        amount_per_fish = float(server_amount)
    else:
        amount_per_fish = round(weight * config['body_ratio'], 4)
        amount_per_fish = min(amount_per_fish, config['max_amount_g'])

    amount_total = round(amount_per_fish * fish_count, 4)
    daily_total  = round(amount_total * config['daily_feeds'], 4)

    return {
        "stage":           stage,
        "weight_g":        weight,
        "amount_per_fish": amount_per_fish,
        "amount_total":    amount_total,
        "daily_total":     daily_total,
        "daily_feeds":     config['daily_feeds'],
        "min_interval_h":  config['min_interval'] / 3600,
    }


@dataclass
class FeedingController:
    last_feed_time:   datetime | None = None
    today_feed_count: int             = 0
    today_feed_total: float           = 0.0
    last_reset_date:  str             = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d'))

    def _reset_daily_if_needed(self):
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self.last_reset_date:
            self.today_feed_count = 0
            self.today_feed_total = 0.0
            self.last_reset_date  = today

    def _is_hunger_detected(self, behavior: dict) -> bool:
        frs       = behavior.get('feeding_score', 0)
        top_ratio = behavior.get('zone_top_ratio', 0.0)
        return frs >= HUNGER_FRS_THRESHOLD or top_ratio >= HUNGER_ZONE_THRESHOLD

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

    def should_feed(self, behavior: dict, sensor: dict, growth: dict) -> tuple[bool, str]:
        self._reset_daily_if_needed()

        # 서버 설정에서 자동 급이 여부 확인
        s    = _fetch_feeding_settings()
        auto = s.get('auto', True)
        if not auto:
            return False, "자동 급이 꺼짐 (서버 설정)"

        length = growth.get('estimated_length', 2.0)
        stage  = get_growth_stage(length)

        turbidity = sensor.get('turbidity', 0.0)
        if turbidity > OVERFEEDING_TURBIDITY:
            return False, f"탁도 과다 ({turbidity} NTU)"

        if not self._is_hunger_detected(behavior):
            return False, "배고픔 미감지"

        can, reason = self._can_feed(stage)
        if not can:
            return False, reason

        return True, "자동 급이 조건 충족"

    def execute_feed(self, behavior: dict, sensor: dict, growth: dict) -> bool:
        do_feed, reason = self.should_feed(behavior, sensor, growth)
        print(f"[FEEDER] 판단: {'✅ 급이' if do_feed else '⏭️ 건너뜀'} — {reason}")

        if not do_feed:
            return False

        length    = growth.get('estimated_length', 2.0)
        fish_cnt  = behavior.get('fish_count', 1)
        feed_info = calc_feed_amount(length, fish_cnt)

        turb_before = sensor.get('turbidity', 0.0)

        # TODO: GPIO 급이기 제어
        # GPIO.output(FEEDER_PIN, GPIO.LOW); time.sleep(0.5); GPIO.output(FEEDER_PIN, GPIO.HIGH)
        print(f"[FEEDER] 급이 실행 — {feed_info['amount_total']}g ({feed_info['stage']})")

        time.sleep(5)

        turb_after   = turb_before + (feed_info['amount_total'] * 3.0)
        delta_ntu    = round(turb_after - turb_before, 2)
        is_overfeeding = delta_ntu > DELTA_NTU_THRESHOLD

        result = send_feeding(
            trigger          = "AUTO",
            amount_g         = feed_info['amount_total'],
            growth_stage     = feed_info['stage'],
            turbidity_before = turb_before,
            turbidity_after  = turb_after,
            is_overfeeding   = is_overfeeding,
            rt_seconds       = 0.0,
            ar_ratio         = 0.0,
            sf_ratio         = behavior.get('zone_top_ratio', 0.0),
            frs_score        = behavior.get('feeding_score', 0),
            activity_before  = behavior.get('activity_level', 0.0),
            activity_during  = 0.0,
            activity_after   = 0.0,
        )

        if result:
            self.last_feed_time   = datetime.now()
            self.today_feed_count += 1
            self.today_feed_total  = round(self.today_feed_total + feed_info['amount_total'], 4)
            print(f"[FEEDER] 완료 | 오늘 {self.today_feed_count}회 / {self.today_feed_total}g")
            if is_overfeeding:
                print(f"[FEEDER] ⚠️ 과급여 감지 — 탁도 변화: +{delta_ntu} NTU")
        return True


if __name__ == "__main__":
    print("=" * 45)
    print(" 급이 자동화 테스트")
    print("=" * 45)
    for length in [1.5, 3.0, 5.0, 7.0]:
        info = calc_feed_amount(length, fish_count=2)
        print(f"  체장 {length:4.1f}cm → {info['stage']:5s} | "
              f"1회:{info['amount_total']:.4f}g | 일{info['daily_feeds']}회")
