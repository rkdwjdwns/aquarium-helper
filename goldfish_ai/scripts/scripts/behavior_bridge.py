"""
scripts/behavior_bridge.py — 행동 분석 결과 브릿지
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    demo_pipeline.py의 분석 결과(fish_metrics 버퍼)를
    pi_client/main.py의 get_behavior_result()가 기대하는
    yolo_analyzer.FishAnalyzer.analyze() 반환 형식으로 변환.

    카메라와 YOLO는 demo_pipeline.py 하나만 실행하고,
    pi_client/main.py는 이 브릿지를 통해 결과를 가져간다.

사용 예 (pi_client/main.py에서):
    # 기존 (더미 데이터)
    def get_behavior_result():
        return {"fish_count": 3, ...}  # TODO

    # 교체 후
    from goldfish_ai.scripts.behavior_bridge import BehaviorBridge
    bridge = BehaviorBridge()

    def get_behavior_result():
        return bridge.get_latest()
"""

from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────
# BehaviorBridge
# ─────────────────────────────────────────────────────────────────────────
class BehaviorBridge:
    """
    demo_pipeline.py의 MetricsWriter.recent_rows를 구독해서
    yolo_analyzer.analyze() 반환 형식으로 변환 후 캐싱.

    demo_pipeline.py와 pi_client/main.py 사이의 단방향 데이터 브릿지.
    Thread-safe.
    """

    # yolo_analyzer.py의 반환 형식 기본값
    _EMPTY_RESULT: dict = {
        "fish_count":     0,
        "overlap_frames": 0,
        "activity_level": 0.0,
        "abr_score":      0.0,
        "dominant_zone":  "MID",
        "zone_top_ratio": 0.0,
        "zone_mid_ratio": 1.0,
        "zone_bot_ratio": 0.0,
        "size_index":     0.0,
        "feeding_score":  0,
        "status":         "NORMAL",
        "is_anomaly":     False,
        "note":           "",
    }

    def __init__(self, window_sec: float = 30.0):
        """
        Args:
            window_sec: 분석에 사용할 최근 구간 (초)
                        demo_pipeline의 recent_rows 버퍼와 맞춰야 함
        """
        self.window_sec      = window_sec
        self._lock           = threading.Lock()
        self._latest: dict   = self._EMPTY_RESULT.copy()
        self._last_update    = 0.0
        self._frs_score      = 0      # FRSScheduler가 주입
        self._abr_rate       = 0.0    # ABRAnalyzer가 주입
        self._abr_per_fish   = []     # ABRResult.per_fish_stats

    # ══════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════

    def update(
        self,
        metrics_rows: list[dict],
        abr_rate:     float        = 0.0,
        abr_per_fish: list[dict]   = None,
        frs_score:    int          = 0,
    ):
        """
        demo_pipeline.py의 분석 결과로 내부 캐시 갱신.
        demo_pipeline.py의 메인 루프에서 30초마다 호출.

        Args:
            metrics_rows : MetricsWriter.recent_rows 슬라이스
            abr_rate     : ABRAnalyzer.compute().rate
            abr_per_fish : ABRResult.per_fish_stats
            frs_score    : FeedingResponseAnalyzer score (0~100)
        """
        if not metrics_rows:
            return

        result = self._build_result(
            metrics_rows, abr_rate, abr_per_fish or [], frs_score
        )

        with self._lock:
            self._latest      = result
            self._last_update = time.time()
            self._frs_score   = frs_score
            self._abr_rate    = abr_rate
            self._abr_per_fish = abr_per_fish or []

    def get_latest(self) -> dict:
        """
        pi_client/main.py의 get_behavior_result()에서 호출.
        yolo_analyzer.FishAnalyzer.analyze() 반환 형식과 동일.

        Returns:
            {
                fish_count, overlap_frames, activity_level, abr_score,
                dominant_zone, zone_top_ratio, zone_mid_ratio, zone_bot_ratio,
                size_index, feeding_score, status, is_anomaly, note
            }
        """
        with self._lock:
            return self._latest.copy()

    def get_last_update_sec(self) -> float:
        """마지막 업데이트로부터 경과 시간(초). 30초 이상이면 데이터 낡은 것."""
        return time.time() - self._last_update if self._last_update > 0 else 999.0

    def is_fresh(self, max_age_sec: float = 60.0) -> bool:
        """데이터가 max_age_sec 이내에 업데이트됐으면 True."""
        return self.get_last_update_sec() <= max_age_sec

    # ══════════════════════════════════════════════════════════════════════
    # 변환 로직
    # ══════════════════════════════════════════════════════════════════════

    def _build_result(
        self,
        rows:         list[dict],
        abr_rate:     float,
        abr_per_fish: list[dict],
        frs_score:    int,
    ) -> dict:
        """
        fish_metrics 행 리스트 → yolo_analyzer.analyze() 반환 형식 변환.

        yolo_analyzer.py와 우리 demo_pipeline.py의 차이점:
            yolo_analyzer: 속도를 px/frame 단위로 계산 (FPS 미적용)
            demo_pipeline: 속도를 px/s 단위로 계산 (FPS 적용)
            → 여기서는 demo_pipeline 값(px/s)을 그대로 사용
        """
        # 대표 ID 행만 사용
        repr_rows = [r for r in rows if r.get("is_representative", True)]
        if not repr_rows:
            repr_rows = rows

        # fish_count
        fish_ids   = {r["fish_id"] for r in repr_rows if "fish_id" in r}
        fish_count = len(fish_ids)

        # activity_level (평균 속도 px/s)
        speeds = [r["speed_px_s"] for r in repr_rows
                  if r.get("speed_px_s", 0) > 0]
        activity_level = round(statistics.mean(speeds), 2) if speeds else 0.0

        # overlap_frames
        overlap_frames = sum(
            1 for r in repr_rows if r.get("overlap_count", 0) > 0
        )

        # zone 비율
        zones     = [r.get("zone", "MID") for r in repr_rows]
        n         = max(len(zones), 1)
        top_ratio = round(zones.count("TOP") / n, 3)
        mid_ratio = round(zones.count("MID") / n, 3)
        bot_ratio = round(zones.count("BOT") / n, 3)
        dominant_zone = max(
            {"TOP": top_ratio, "MID": mid_ratio, "BOT": bot_ratio},
            key=lambda k: {"TOP": top_ratio, "MID": mid_ratio,
                           "BOT": bot_ratio}[k]
        )

        # size_index 평균
        sizes      = [r["size_index"] for r in repr_rows if "size_index" in r]
        size_index = round(statistics.mean(sizes), 3) if sizes else 0.0

        # 상태 판정 (yolo_analyzer.py 기준과 동일하게)
        is_anomaly = abr_rate > 0.3 or top_ratio > 0.7

        if abr_rate < 0.05 and activity_level > 5:   status = "EXCELLENT"
        elif abr_rate < 0.1:                          status = "GOOD"
        elif abr_rate < 0.2:                          status = "NORMAL"
        elif abr_rate < 0.3:                          status = "WARNING"
        else:                                         status = "POOR"

        # note (yolo_analyzer.py 기준 + ABR per_fish 요약)
        note = ""
        if top_ratio > 0.7:
            note = "상층 집중 체류 — 산소 부족 또는 먹이 요구 가능성"
        elif bot_ratio > 0.7:
            note = "하층 집중 체류 — 스트레스 또는 수질 이상 가능성"
        elif abr_rate > 0.3:
            note = "이상 행동 감지 — 수질 점검 권장"

        if abr_per_fish:
            top = abr_per_fish[0]
            note += (f" | 최고활동 ID#{top['fish_id']} "
                     f"평균{top['mean_speed_px_s']:.0f}px/s "
                     f"CV={top['cv']:.2f}")

        return {
            "fish_count":     fish_count,
            "overlap_frames": overlap_frames,
            "activity_level": activity_level,
            "abr_score":      round(abr_rate, 4),
            "dominant_zone":  dominant_zone,
            "zone_top_ratio": top_ratio,
            "zone_mid_ratio": mid_ratio,
            "zone_bot_ratio": bot_ratio,
            "size_index":     size_index,
            "feeding_score":  frs_score,
            "status":         status,
            "is_anomaly":     is_anomaly,
            "note":           note,
        }


# ─────────────────────────────────────────────────────────────────────────
# 싱글턴 인스턴스 (pi_client/main.py에서 import해서 사용)
# ─────────────────────────────────────────────────────────────────────────
_bridge_instance: Optional[BehaviorBridge] = None

def get_bridge(window_sec: float = 30.0) -> BehaviorBridge:
    """
    싱글턴 BehaviorBridge 반환.
    demo_pipeline.py와 pi_client/main.py가 같은 인스턴스를 공유.
    """
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = BehaviorBridge(window_sec=window_sec)
    return _bridge_instance


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import random

    bridge = get_bridge()

    # 더미 fish_metrics 행 생성
    rng   = random.Random(42)
    zones = ["TOP", "MID", "MID", "BOT", "MID"]
    dummy_rows = [
        {
            "fish_id":          i % 3 + 1,
            "speed_px_s":       rng.uniform(5, 40),
            "activity":         rng.uniform(10, 30),
            "zone":             rng.choice(zones),
            "size_index":       rng.uniform(0.8, 1.5),
            "overlap_count":    0,
            "is_representative": True,
        }
        for i in range(100)
    ]

    bridge.update(
        metrics_rows = dummy_rows,
        abr_rate     = 0.05,
        frs_score    = 78,
    )

    result = bridge.get_latest()
    print("\n[BehaviorBridge] 변환 결과:")
    for k, v in result.items():
        print(f"  {k:<20}: {v}")

    print(f"\n  데이터 신선도: {bridge.get_last_update_sec():.1f}초 전 업데이트")
    print(f"  is_fresh(60s): {bridge.is_fresh(60)}")
