"""
water_change_detector.py
수위 센서로 환수 자동 감지 및 서버 기록

감지 원리:
  1. 평소 수위 기준값(BASELINE) 대비 급격한 수위 감소 감지
  2. 일정 시간 후 수위가 다시 회복되면 '환수 완료'로 판정
  3. 서버에 자동으로 환수 완료 기록

수위 변화 패턴:
  정상:  100% 유지
  환수:  100% → 70% (물 빼기) → 100% (물 채우기) 완료
"""

import time
import requests
from datetime import datetime, date
from config import BASE_URL, HEADERS, TANK_ID

# ── 환수 감지 설정 ─────────────────────────────
WATER_CHANGE_DROP    = 15.0    # 수위 감소 기준 (%) — 이 이상 떨어지면 환수 시작으로 판단
WATER_CHANGE_RECOVER = 10.0    # 수위 회복 기준 (%) — 감소분의 이 이상 회복되면 환수 완료
CONFIRM_DELAY_SEC    = 120     # 수위 회복 후 확인 대기 시간 (초)


class WaterChangeDetector:
    """
    수위 변화를 감지해 자동으로 환수 완료를 기록합니다.

    사용법:
        detector = WaterChangeDetector()

        # 센서 데이터가 올 때마다 호출
        detector.update(water_level=95.0)
    """

    def __init__(self):
        self.baseline      = None    # 평소 수위 기준값
        self.min_level     = None    # 환수 중 최저 수위
        self.state         = "NORMAL"  # NORMAL → DRAINING → REFILLING → DONE
        self.drain_time    = None    # 물 빼기 시작 시각
        self.recover_time  = None    # 물 회복 시작 시각
        self.today_changed = False   # 오늘 이미 기록했는지

    def _reset_today(self):
        """날짜가 바뀌면 오늘 기록 초기화"""
        if self.today_changed and date.today() != self._last_date:
            self.today_changed = False
        self._last_date = date.today()

    def update(self, water_level: float) -> str | None:
        """
        수위값을 받아 환수 상태를 업데이트합니다.

        Returns:
            'WATER_CHANGE_DETECTED': 환수 완료 감지됨
            None: 일반 상태
        """
        # 기준값 초기 설정 (첫 10회 평균)
        if self.baseline is None:
            self.baseline = water_level
            return None

        # 기준값 점진적 업데이트 (정상 상태일 때만)
        if self.state == "NORMAL" and water_level > self.baseline - 5:
            self.baseline = self.baseline * 0.95 + water_level * 0.05

        drop = self.baseline - water_level   # 현재 수위 감소량

        # ── 상태 머신 ──────────────────────────
        if self.state == "NORMAL":
            if drop >= WATER_CHANGE_DROP:
                self.state      = "DRAINING"
                self.min_level  = water_level
                self.drain_time = datetime.now()
                print(f"[WATER] 환수 시작 감지 — 수위 {self.baseline:.0f}% → {water_level:.0f}%")

        elif self.state == "DRAINING":
            if water_level < self.min_level:
                self.min_level = water_level   # 최저점 갱신

            # 물이 다시 올라오기 시작하면
            recover = water_level - self.min_level
            if recover >= WATER_CHANGE_RECOVER:
                self.state        = "REFILLING"
                self.recover_time = datetime.now()
                print(f"[WATER] 물 채우기 시작 — 최저 {self.min_level:.0f}% → {water_level:.0f}%")

        elif self.state == "REFILLING":
            # 수위가 기준값에 근접하면 환수 완료
            if water_level >= self.baseline - 5:
                elapsed = (datetime.now() - self.drain_time).seconds
                print(f"[WATER] 환수 완료 감지! (소요 시간: {elapsed//60}분 {elapsed%60}초)")
                self.state = "NORMAL"
                self.min_level = None

                if not self.today_changed:
                    result = self._record_water_change()
                    if result:
                        self.today_changed = True
                        return "WATER_CHANGE_DETECTED"

        return None

    def _record_water_change(self) -> bool:
        """서버에 환수 완료를 자동 기록합니다."""
        try:
            res = requests.post(
                f"{BASE_URL}/monitoring/water-change/{TANK_ID}/",
                headers={k: v for k, v in HEADERS.items() if k != "Content-Type"},
                timeout=5,
            )
            res.raise_for_status()
            print(f"[WATER] 환수 완료 서버 기록 성공 — {date.today()}")
            return True
        except Exception as e:
            print(f"[WATER] 환수 기록 오류: {e}")
            return False


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    detector = WaterChangeDetector()

    print("[TEST] 환수 시뮬레이션 시작")

    # 정상 수위
    for _ in range(5):
        detector.update(100.0)

    # 물 빼기 (100% → 65%)
    print("\n--- 물 빼기 ---")
    for level in [95, 85, 75, 68, 65]:
        result = detector.update(float(level))
        print(f"  수위: {level}% | 상태: {detector.state}")

    # 물 채우기 (65% → 100%)
    print("\n--- 물 채우기 ---")
    for level in [70, 80, 90, 97, 100]:
        result = detector.update(float(level))
        print(f"  수위: {level}% | 상태: {detector.state}")
        if result == "WATER_CHANGE_DETECTED":
            print("  ✅ 환수 완료 감지!")
