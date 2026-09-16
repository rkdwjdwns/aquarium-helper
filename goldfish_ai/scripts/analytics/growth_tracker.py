"""
analytics/growth_tracker.py — 물고기 성장 추적
금붕어 자동 사육 AI 시스템 (v2.0)

기능:
    - 개체별 크기(cm) 기록 및 이상치 필터
    - bbox → cm 변환 (px_to_cm_ratio 실측 필요)
    - 최근 N일 성장률 계산 및 성장 상태 평가
    - 성어 도달 예측 / 미래 크기 예측 (선형 회귀)
    - 개체별/다개체 성장 곡선 시각화 (matplotlib 선택적)
    - CSV 저장 / 로드
    - 환경 데이터 연동 확장 포인트

주의:
    - fish_id는 ByteTrack에서 부여한 ID를 그대로 사용
    - px_to_cm_ratio는 미확정 — 카메라 고정 후 기준 물체로 실측 필수
      (예: 수조 30cm 폭이 300px이면 ratio = 0.1)
"""

from __future__ import annotations

import csv
import logging
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# matplotlib는 Pi 5에 없을 수 있으므로 선택적 import
try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("[GrowthTracker] matplotlib 없음 — 시각화 기능 비활성화")


# ─────────────────────────────────────────────────────────────────────────
# 데이터 구조
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class GrowthRecord:
    """개별 성장 기록"""
    fish_id:        int
    timestamp:      datetime
    size_cm:        float
    bbox_width_px:  Optional[float] = None
    bbox_height_px: Optional[float] = None
    bbox_area_px:   Optional[float] = None
    confidence:     Optional[float] = None
    note:           str = ""


@dataclass
class EnvironmentRecord:
    """환경 데이터 기록 (성장-환경 상관관계 분석용 확장 포인트)"""
    fish_id:          int
    timestamp:        datetime
    temperature:      Optional[float] = None
    ph:               Optional[float] = None
    dissolved_oxygen: Optional[float] = None
    note:             str = ""


# ─────────────────────────────────────────────────────────────────────────
# 성장 추적기
# ─────────────────────────────────────────────────────────────────────────
class GrowthTracker:
    """물고기 성장 추적기"""

    def __init__(
        self,
        adult_size_cm:     float = 20.0,
        min_valid_size_cm: float = 0.5,
        max_valid_size_cm: float = 100.0,
        min_confidence:    float = 0.0,
        max_size_ratio:    float = 3.0,
    ) -> None:
        """
        Args:
            adult_size_cm:     성어 기준 크기 (cm) — 코멧 기준 20cm
            min_valid_size_cm: 유효 최소 크기 (cm)
            max_valid_size_cm: 유효 최대 크기 (cm)
            min_confidence:    이 값 미만 confidence 기록 무시 (0.0 = 필터 없음)
            max_size_ratio:    직전 기록 대비 허용 변화 배율
                               3.0이면 3배 초과 or 1/3 미만 시 이상치로 필터
        """
        self.adult_size_cm     = adult_size_cm
        self.min_valid_size_cm = min_valid_size_cm
        self.max_valid_size_cm = max_valid_size_cm
        self.min_confidence    = min_confidence
        self.max_size_ratio    = max_size_ratio

        self.growth_records:      Dict[int, List[GrowthRecord]]      = {}
        self.environment_records: Dict[int, List[EnvironmentRecord]] = {}

    # ══════════════════════════════════════════════════════════════════════
    # 기록
    # ══════════════════════════════════════════════════════════════════════

    def record_size(
        self,
        fish_id:        int,
        size_cm:        float,
        timestamp:      Optional[datetime] = None,
        bbox_width_px:  Optional[float]    = None,
        bbox_height_px: Optional[float]    = None,
        confidence:     Optional[float]    = None,
        note:           str                = "",
    ) -> bool:
        """크기(cm) 직접 기록. 반환: 기록 성공 여부"""
        if not self._is_valid_size(size_cm):
            logger.debug(f"[Growth] fish_id={fish_id} 크기 범위 초과: {size_cm}cm")
            return False

        if self.min_confidence > 0.0:
            if confidence is None or confidence < self.min_confidence:
                logger.debug(f"[Growth] fish_id={fish_id} confidence 미달: {confidence}")
                return False

        timestamp = timestamp or datetime.now()

        # 이상치 필터: 직전 기록 대비 max_size_ratio 초과 변화 무시
        existing = self.growth_records.get(fish_id, [])
        if existing:
            last_size = existing[-1].size_cm
            if last_size > 0:
                ratio = size_cm / last_size
                if ratio > self.max_size_ratio or ratio < (1.0 / self.max_size_ratio):
                    logger.debug(
                        f"[Growth] fish_id={fish_id} 이상치 필터: "
                        f"직전={last_size:.2f} → 현재={size_cm:.2f} (ratio={ratio:.2f})"
                    )
                    return False

        bbox_area_px = (
            bbox_width_px * bbox_height_px
            if bbox_width_px is not None and bbox_height_px is not None
            else None
        )

        record = GrowthRecord(
            fish_id        = fish_id,
            timestamp      = timestamp,
            size_cm        = round(size_cm, 3),
            bbox_width_px  = bbox_width_px,
            bbox_height_px = bbox_height_px,
            bbox_area_px   = bbox_area_px,
            confidence     = confidence,
            note           = note,
        )

        if fish_id not in self.growth_records:
            self.growth_records[fish_id] = []
        self.growth_records[fish_id].append(record)
        self.growth_records[fish_id].sort(key=lambda r: r.timestamp)
        return True

    def record_from_bbox(
        self,
        fish_id:        int,
        bbox_width_px:  float,
        bbox_height_px: float,
        px_to_cm_ratio: float,
        timestamp:      Optional[datetime] = None,
        confidence:     Optional[float]    = None,
        note:           str                = "",
    ) -> bool:
        """
        Bounding Box 픽셀값 → cm 환산 후 기록.

        크기 추정:
            어류는 수평으로 헤엄치므로 bbox_width_px 기준 사용.

        Args:
            px_to_cm_ratio: 1px 당 cm 환산 비율
                            ※ 미확정 — 카메라 고정 후 기준 물체로 실측 필수

        주의:
            단순 비율 방식. 카메라 각도/거리/렌즈 왜곡 보정 미포함.
        """
        if bbox_width_px <= 0:
            logger.warning(f"[Growth] fish_id={fish_id} bbox_width_px <= 0: {bbox_width_px}")
            return False
        if bbox_height_px <= 0:
            logger.warning(f"[Growth] fish_id={fish_id} bbox_height_px <= 0: {bbox_height_px}")
            return False
        if px_to_cm_ratio <= 0:
            logger.error(
                f"[Growth] px_to_cm_ratio <= 0: {px_to_cm_ratio}. "
                "카메라 고정 후 실측값을 입력하세요."
            )
            return False

        return self.record_size(
            fish_id        = fish_id,
            size_cm        = bbox_width_px * px_to_cm_ratio,
            timestamp      = timestamp,
            bbox_width_px  = bbox_width_px,
            bbox_height_px = bbox_height_px,
            confidence     = confidence,
            note           = note,
        )

    def attach_environment_data(
        self,
        fish_id:          int,
        temperature:      Optional[float]   = None,
        ph:               Optional[float]   = None,
        dissolved_oxygen: Optional[float]   = None,
        timestamp:        Optional[datetime] = None,
        note:             str               = "",
    ) -> None:
        """환경 데이터 연동 확장 포인트. 현재는 저장만 수행."""
        timestamp = timestamp or datetime.now()
        record = EnvironmentRecord(
            fish_id=fish_id, timestamp=timestamp,
            temperature=temperature, ph=ph,
            dissolved_oxygen=dissolved_oxygen, note=note,
        )
        if fish_id not in self.environment_records:
            self.environment_records[fish_id] = []
        self.environment_records[fish_id].append(record)
        self.environment_records[fish_id].sort(key=lambda r: r.timestamp)

    # ══════════════════════════════════════════════════════════════════════
    # 조회
    # ══════════════════════════════════════════════════════════════════════

    def get_records(self, fish_id: int) -> List[GrowthRecord]:
        return self.growth_records.get(fish_id, [])

    def get_recent_records(self, fish_id: int, days: int = 30) -> List[GrowthRecord]:
        cutoff = datetime.now() - timedelta(days=days)
        return [r for r in self.get_records(fish_id) if r.timestamp >= cutoff]

    def get_environment_records(self, fish_id: int) -> List[EnvironmentRecord]:
        return self.environment_records.get(fish_id, [])

    # ══════════════════════════════════════════════════════════════════════
    # 계산
    # ══════════════════════════════════════════════════════════════════════

    def calculate_growth(
        self,
        fish_id:     int,
        days:        int = 7,
        window_days: int = 3,
    ) -> Optional[dict]:
        """
        최근 N일 성장률 계산.

        Args:
            fish_id:     분석 대상 개체 ID
            days:        분석 기간 (일)
            window_days: 이동 평균 윈도우 (일 기준)

        Returns:
            dict 또는 None (기록 2개 미만 시)

            Keys:
                fish_id, current_size_cm, growth_per_day,
                growth_percent, status, insight,
                days_to_adult, moving_avg_size
        """
        records = self.get_recent_records(fish_id, days=days)
        if len(records) < 2:
            logger.info(f"[Growth] fish_id={fish_id} 기록 부족 ({len(records)}개, 최소 2개 필요)")
            return None

        current_size = records[-1].size_cm
        first_size   = records[0].size_cm
        elapsed_days = (
            (records[-1].timestamp - records[0].timestamp).total_seconds() / 86400.0
        )

        # 1시간(1/24일) 미만 간격은 일별 성장률 의미 없음
        growth_per_day = (
            (current_size - first_size) / elapsed_days
            if elapsed_days >= (1.0 / 24.0)
            else 0.0
        )
        growth_percent = (
            (current_size - first_size) / first_size * 100.0
            if first_size > 0 else 0.0
        )

        moving_avg    = self._moving_average_by_days(records, window_days)
        days_to_adult = self._days_to_adult(current_size, growth_per_day)
        status        = self._evaluate_growth(growth_per_day, growth_percent)
        insight       = self._generate_insight(current_size, growth_per_day,
                                               growth_percent, days_to_adult)

        return {
            "fish_id":         fish_id,
            "current_size_cm": round(current_size, 3),
            "growth_per_day":  round(growth_per_day, 4),
            "growth_percent":  round(growth_percent, 2),
            "status":          status,
            "insight":         insight,
            "days_to_adult":   days_to_adult,
            "moving_avg_size": round(moving_avg, 3) if moving_avg is not None else None,
        }

    def predict_future_size(
        self,
        fish_id:    int,
        days_ahead: int = 7,
    ) -> Optional[dict]:
        """
        선형 회귀 기반 미래 크기 예측.
        numpy 없이 statistics 모듈만 사용.

        Returns:
            dict 또는 None (기록 2개 미만 시)
        """
        records = self.get_records(fish_id)
        if len(records) < 2:
            return None

        t0 = records[0].timestamp
        x  = [(r.timestamp - t0).total_seconds() / 86400.0 for r in records]
        y  = [r.size_cm for r in records]
        n  = len(x)

        x_m   = statistics.mean(x)
        y_m   = statistics.mean(y)
        denom = sum((xi - x_m) ** 2 for xi in x)

        if denom == 0:
            return None

        slope     = sum((x[i] - x_m) * (y[i] - y_m) for i in range(n)) / denom
        intercept = y_m - slope * x_m

        x_future       = x[-1] + days_ahead
        predicted_size = max(intercept + slope * x_future, 0.0)
        predicted_date = records[-1].timestamp + timedelta(days=days_ahead)

        return {
            "fish_id":           fish_id,
            "current_size_cm":   round(records[-1].size_cm, 3),
            "predicted_size_cm": round(predicted_size, 3),
            "days_ahead":        days_ahead,
            "predicted_date":    predicted_date.strftime("%Y-%m-%d"),
        }

    # ══════════════════════════════════════════════════════════════════════
    # CSV 저장 / 로드
    # ══════════════════════════════════════════════════════════════════════

    def save_to_csv(self, file_path: str = "data/growth_records.csv") -> str:
        """성장 기록 CSV 저장"""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fields = [
            "fish_id", "timestamp", "size_cm",
            "bbox_width_px", "bbox_height_px", "bbox_area_px",
            "confidence", "note",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for records in self.growth_records.values():
                for r in records:
                    row = asdict(r)
                    row["timestamp"] = r.timestamp.isoformat()
                    writer.writerow(row)

        logger.info(f"[Growth] 저장: {path}")
        return str(path)

    def load_from_csv(self, file_path: str = "data/growth_records.csv") -> None:
        """
        CSV에서 성장 기록 불러오기.
        로드 시 이상치 필터 미적용 (저장된 기록은 검증된 데이터로 간주).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"파일 없음: {file_path}")

        self.growth_records.clear()

        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fish_id = int(row["fish_id"])
                record  = GrowthRecord(
                    fish_id        = fish_id,
                    timestamp      = datetime.fromisoformat(row["timestamp"]),
                    size_cm        = float(row["size_cm"]),
                    bbox_width_px  = self._to_float(row.get("bbox_width_px")),
                    bbox_height_px = self._to_float(row.get("bbox_height_px")),
                    bbox_area_px   = self._to_float(row.get("bbox_area_px")),
                    confidence     = self._to_float(row.get("confidence")),
                    note           = row.get("note", ""),
                )
                if fish_id not in self.growth_records:
                    self.growth_records[fish_id] = []
                self.growth_records[fish_id].append(record)

        for fish_id in self.growth_records:
            self.growth_records[fish_id].sort(key=lambda r: r.timestamp)

        n = sum(len(v) for v in self.growth_records.values())
        logger.info(f"[Growth] {n}건 로드: {file_path}")

    # ══════════════════════════════════════════════════════════════════════
    # 시각화
    # ══════════════════════════════════════════════════════════════════════

    def visualize_growth(
        self,
        fish_id:         int,
        save_path:       str  = "data/growth_curve.png",
        show_adult_line: bool = True,
        show_prediction: bool = False,
        prediction_days: int  = 7,
    ) -> Optional[str]:
        """개체 성장 곡선 저장. matplotlib 없으면 None 반환."""
        if not MATPLOTLIB_AVAILABLE:
            logger.warning("[Growth] matplotlib 없음 — 시각화 불가")
            return None

        records = self.get_records(fish_id)
        if len(records) < 2:
            return None

        dates = [r.timestamp for r in records]
        sizes = [r.size_cm   for r in records]

        plt.figure(figsize=(10, 6))
        plt.plot(dates, sizes, marker="o", linewidth=2, label="측정값")
        plt.xlabel("날짜")
        plt.ylabel("크기 (cm)")
        plt.title(f"Fish #{fish_id} 성장 곡선")
        plt.grid(True, alpha=0.3)

        if show_adult_line:
            plt.axhline(y=self.adult_size_cm, linestyle="--",
                        label=f"성어 기준 ({self.adult_size_cm}cm)")

        if show_prediction:
            pred = self.predict_future_size(fish_id=fish_id, days_ahead=prediction_days)
            if pred:
                future_date = dates[-1] + timedelta(days=prediction_days)
                plt.plot([dates[-1], future_date],
                         [sizes[-1], pred["predicted_size_cm"]],
                         linestyle=":", marker="x", linewidth=2,
                         label=f"{prediction_days}일 예측")

        plt.legend()
        plt.xticks(rotation=30)
        plt.tight_layout()
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150)
        plt.close()
        return save_path

    def visualize_multi_growth(
        self,
        fish_ids:  List[int],
        save_path: str = "data/multi_growth_curve.png",
    ) -> Optional[str]:
        """여러 개체 성장 곡선 비교"""
        if not MATPLOTLIB_AVAILABLE:
            return None

        has_data = False
        plt.figure(figsize=(12, 6))
        for fish_id in fish_ids:
            records = self.get_records(fish_id)
            if len(records) < 2:
                continue
            has_data = True
            plt.plot([r.timestamp for r in records],
                     [r.size_cm   for r in records],
                     marker="o", linewidth=2, label=f"Fish #{fish_id}")

        if not has_data:
            plt.close()
            return None

        plt.xlabel("날짜"); plt.ylabel("크기 (cm)")
        plt.title("개체별 성장 곡선 비교")
        plt.grid(True, alpha=0.3); plt.legend()
        plt.xticks(rotation=30); plt.tight_layout()
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150)
        plt.close()
        return save_path

    # ══════════════════════════════════════════════════════════════════════
    # Private — 유틸
    # ══════════════════════════════════════════════════════════════════════

    def _moving_average_by_days(
        self, records: List[GrowthRecord], window_days: int
    ) -> Optional[float]:
        """최근 N일 이내 기록의 평균 크기 (날짜 기준)"""
        if not records:
            return None
        cutoff = records[-1].timestamp - timedelta(days=window_days)
        window = [r for r in records if r.timestamp >= cutoff]
        return sum(r.size_cm for r in window) / len(window) if window else None

    def _days_to_adult(self, current_size_cm: float, growth_per_day: float) -> Optional[int]:
        remaining = self.adult_size_cm - current_size_cm
        if remaining <= 0:  return 0
        if growth_per_day <= 0: return None
        return int(round(remaining / growth_per_day))

    @staticmethod
    def _evaluate_growth(growth_per_day: float, growth_percent: float) -> str:
        if growth_per_day < 0:   return "decreasing"
        if growth_per_day == 0:  return "stagnant"
        if growth_percent >= 10: return "excellent"
        if growth_percent >= 5:  return "good"
        if growth_percent >= 1:  return "normal"
        return "slow"

    def _generate_insight(
        self, current_size: float, growth_per_day: float,
        growth_percent: float, days_to_adult: Optional[int],
    ) -> str:
        if growth_per_day < 0:
            return "최근 측정 기준 크기 감소 감지 — 측정 오차 또는 건강 이상 확인 필요."
        if growth_per_day == 0:
            return "최근 기간 동안 성장 정체 관찰."
        if days_to_adult == 0:
            return "이미 성어 크기에 도달했거나 그 이상으로 추정."
        if days_to_adult is None:
            return "현재 성장 속도로는 성어 도달 시점 예측 어려움."
        if growth_percent >= 10:
            return f"성장세 양호 — 약 {days_to_adult}일 후 성어 크기 도달 예상."
        if growth_percent >= 1:
            return f"완만한 성장 — 약 {days_to_adult}일 후 성어 크기 도달 예상."
        return "성장 속도 느림 — 급이량, 수질, 수온 등 환경 요인 점검 권장."

    def _is_valid_size(self, size_cm: float) -> bool:
        return self.min_valid_size_cm <= size_cm <= self.max_valid_size_cm

    @staticmethod
    def _to_float(value: Optional[str]) -> Optional[float]:
        if value in (None, "", "None"):
            return None
        try:
            return float(value)
        except ValueError:
            return None


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tracker   = GrowthTracker(adult_size_cm=20.0)
    base_time = datetime(2026, 5, 1)

    for fish_id in [1, 2, 3]:
        size = 1.0 + fish_id * 0.1
        for day in range(7):
            tracker.record_size(
                fish_id   = fish_id,
                size_cm   = round(size + day * 0.05, 3),
                timestamp = base_time + timedelta(days=day),
            )

    for fish_id in [1, 2, 3]:
        result = tracker.calculate_growth(fish_id=fish_id, days=7)
        if result:
            print(f"\nFish #{fish_id}")
            for k, v in result.items():
                print(f"  {k:<20}: {v}")

    pred = tracker.predict_future_size(fish_id=1, days_ahead=7)
    print(f"\n[예측] {pred}")

    path = tracker.save_to_csv("data/growth_records_test.csv")
    print(f"\n저장: {path}")

    tracker2 = GrowthTracker()
    tracker2.load_from_csv(path)
    print(f"로드 확인: fish_id=1 기록 {len(tracker2.get_records(1))}개")
