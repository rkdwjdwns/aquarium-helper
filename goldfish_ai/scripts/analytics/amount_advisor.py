"""
analytics/amount_advisor.py — 급이량 추천 모듈
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    - frs_history.csv 최근 N회 FRS 점수 읽기
    - 점수 추이 분석 → 급이량 조정 추천 문자열 반환
    - 대시보드 / 터미널 / 서버 전송용

추천 로직:
    최근 amount_history_size(기본 3)회 FRS 평균 기준:

    평균 FRS ≥ 80  → 반응 과잉 (배고픔 심함) → "증량 권장"
    평균 FRS ≤ 40  → 반응 저조 (과급이 의심) → "감량 권장"
    그 외 41~79    → 적정 상태              → "현행 유지"

    단, 데이터가 amount_history_size 미만이면 "데이터 수집 중" 반환.

사용 예:
    from analytics.amount_advisor import AmountAdvisor
    advisor = AmountAdvisor(cfg["analytics"]["frs"], cfg["storage"])
    advice  = advisor.advise()
    print(advice.message)
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────
# 추천 결과
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class AmountAdvice:
    action:       str           # "increase" / "decrease" / "maintain" / "pending"
    message:      str           # 화면 표시용 한국어 메시지
    avg_frs:      Optional[float]  # 판단에 사용된 평균 FRS
    sample_count: int           # 사용된 데이터 수
    timestamp:    str           # 생성 시각


# ─────────────────────────────────────────────────────────────────────────
# 급이량 추천기
# ─────────────────────────────────────────────────────────────────────────
class AmountAdvisor:
    """
    FRS 이력을 읽어 급이량 조정을 추천.

    파이프라인에서 FRS 계산 직후 advise()를 호출하거나,
    대시보드에서 주기적으로 폴링해서 최신 추천을 표시.
    """

    # 추천 임계값
    THRESHOLD_HIGH = 80.0   # 이 이상 → 증량
    THRESHOLD_LOW  = 40.0   # 이 이하 → 감량

    # action → 한국어 메시지 템플릿
    _MESSAGES = {
        "increase": (
            "📈 급이량 증량 권장\n"
            "최근 {n}회 평균 FRS {avg:.1f}점 — 급이 반응이 강합니다.\n"
            "현재 급이량을 소폭 늘려보세요."
        ),
        "decrease": (
            "📉 급이량 감량 권장\n"
            "최근 {n}회 평균 FRS {avg:.1f}점 — 반응이 저조합니다.\n"
            "과급이 가능성이 있으니 급이량을 줄여보세요."
        ),
        "maintain": (
            "✅ 현행 급이량 유지\n"
            "최근 {n}회 평균 FRS {avg:.1f}점 — 적정 상태입니다."
        ),
        "pending": (
            "⏳ 데이터 수집 중\n"
            "추천에 필요한 급이 데이터가 {n}회 중 {collected}회 수집됐습니다.\n"
            "{remain}회 더 기다려주세요."
        ),
    }

    def __init__(self, frs_cfg: dict, storage_cfg: dict):
        """
        Args:
            frs_cfg:     config.yaml analytics.frs 섹션
            storage_cfg: config.yaml storage 섹션
        """
        self.history_size = int(frs_cfg.get("amount_history_size", 3))
        output_dir = Path(storage_cfg.get("output_dir", "data"))
        self.csv_path = output_dir / "frs_history.csv"

    # ══════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════

    def advise(self) -> AmountAdvice:
        """
        최신 FRS 이력 기반으로 급이량 추천 반환.

        Returns:
            AmountAdvice
        """
        scores = self._load_recent_scores()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 데이터 부족
        if len(scores) < self.history_size:
            msg = self._MESSAGES["pending"].format(
                n         = self.history_size,
                collected = len(scores),
                remain    = self.history_size - len(scores),
            )
            return AmountAdvice(
                action       = "pending",
                message      = msg,
                avg_frs      = None,
                sample_count = len(scores),
                timestamp    = now_str,
            )

        avg = sum(scores) / len(scores)

        if avg >= self.THRESHOLD_HIGH:
            action = "increase"
        elif avg <= self.THRESHOLD_LOW:
            action = "decrease"
        else:
            action = "maintain"

        msg = self._MESSAGES[action].format(n=len(scores), avg=avg)
        return AmountAdvice(
            action       = action,
            message      = msg,
            avg_frs      = round(avg, 2),
            sample_count = len(scores),
            timestamp    = now_str,
        )

    def advise_and_print(self) -> AmountAdvice:
        """advise() 결과를 터미널에도 출력."""
        advice = self.advise()
        print(f"\n[AmountAdvisor] {advice.timestamp}")
        print(advice.message)
        return advice

    # ══════════════════════════════════════════════════════════════════════
    # Private
    # ══════════════════════════════════════════════════════════════════════

    def _load_recent_scores(self) -> list[float]:
        """frs_history.csv에서 최근 history_size개 score 반환."""
        if not self.csv_path.exists():
            return []
        scores = []
        with open(self.csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    scores.append(float(row["score"]))
                except (ValueError, KeyError):
                    pass
        # 최신 N개만
        return scores[-self.history_size:]


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os, tempfile

    # 가상 frs_history.csv 생성
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "frs_history.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["feeding_ts", "datetime_str",
                              "s1_response_time", "s2_activity_inc", "s3_surface_visit",
                              "score", "pre_avg_speed", "post_avg_speed",
                              "post_top_ratio", "first_surface_sec", "note"])
            # 시나리오 1: 높은 FRS (증량 권장)
            for score in [82.0, 85.0, 88.0]:
                writer.writerow([0, "2025-01-01 08:00:00",
                                  0.8, 0.8, 0.8, score,
                                  50.0, 150.0, 0.4, 15.0, "테스트"])

        advisor = AmountAdvisor(
            frs_cfg     = {"amount_history_size": 3},
            storage_cfg = {"output_dir": tmpdir},
        )
        print("=== 시나리오 1: 높은 FRS ===")
        advisor.advise_and_print()

        # 시나리오 2: 낮은 FRS (감량 권장)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["feeding_ts", "datetime_str",
                              "s1_response_time", "s2_activity_inc", "s3_surface_visit",
                              "score", "pre_avg_speed", "post_avg_speed",
                              "post_top_ratio", "first_surface_sec", "note"])
            for score in [35.0, 30.0, 38.0]:
                writer.writerow([0, "2025-01-01 18:00:00",
                                  0.2, 0.2, 0.2, score,
                                  80.0, 85.0, 0.05, None, "테스트"])

        print("\n=== 시나리오 2: 낮은 FRS ===")
        advisor.advise_and_print()

        # 시나리오 3: 데이터 부족
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["feeding_ts", "datetime_str",
                              "s1_response_time", "s2_activity_inc", "s3_surface_visit",
                              "score", "pre_avg_speed", "post_avg_speed",
                              "post_top_ratio", "first_surface_sec", "note"])
            writer.writerow([0, "2025-01-01 08:00:00",
                              0.5, 0.5, 0.5, 65.0,
                              60.0, 120.0, 0.25, 20.0, "테스트"])

        print("\n=== 시나리오 3: 데이터 부족 (1/3) ===")
        advisor.advise_and_print()
