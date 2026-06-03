"""
analytics/abr.py — 이상 행동율 (Abnormal Behavior Rate)
금붕어 자동 사육 AI 시스템 (v2.0)

설계 문서 6.2 기준.

Baseline 기간 데이터로 μ, σ 학습(fit) 후
새 데이터의 이상 행동율(ABR) 계산.

CSV 저장:
    data/abr_baseline.csv   ← Baseline μ, σ
    data/abr_results.csv    ← 분석 결과 이력

사용 예:
    from analytics.abr import ABRAnalyzer

    analyzer = ABRAnalyzer()
    analyzer.fit(baseline_df)
    result = analyzer.compute(df)
    analyzer.save_baseline()
    analyzer.save_result(result)
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import pandas as pd
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logger.warning("[ABR] numpy/pandas 없음 — ABRAnalyzer 비활성화 (pip install numpy pandas)")


# ─────────────────────────────────────────────────────────────────────────
# 결과 구조
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ABRResult:
    """ABR 분석 결과"""
    timestamp:      float         # 분석 시각 (time.time())
    rate:           float         # 이상 행동율 0~1
    n_anomaly:      int           # 이상 프레임 수
    n_total:        int           # 전체 프레임 수
    mu:             float         # Baseline 평균 속도
    sigma:          float         # Baseline 표준편차
    threshold:      float         # 사용한 σ 배수
    valid:          bool          # 유효한 결과 여부
    reason:         str   = ""    # 유효하지 않을 때 사유
    # 개체별 통계 (논문 코드 summary 구조 반영)
    per_fish_stats: Optional[list] = None  # fish_id별 cv, mean, std, tracked_duration_sec


# ─────────────────────────────────────────────────────────────────────────
# 분석기
# ─────────────────────────────────────────────────────────────────────────
class ABRAnalyzer:
    """
    이상 행동율 분석기.

    이상 조건: |speed_px_s - μ| > threshold × σ
    ABR = 이상 프레임 수 / 전체 프레임 수

    설계 문서 미확정 항목:
        - Baseline 수집 기간: 현재 3일 권장 (실측 후 조정)
        - 급이 직후 / 물갈이 직후 구간 Baseline 제외 (미구현 — feeding_events 연동 후)
    """

    # Baseline 최소 샘플 수 (너무 적으면 μ, σ 신뢰 불가)
    MIN_BASELINE_SAMPLES: int = 100

    def __init__(
        self,
        threshold:        float = 2.0,
        baseline_csv:     str   = "data/abr_baseline.csv",
        results_csv:      str   = "data/abr_results.csv",
    ) -> None:
        """
        Args:
            threshold:    이상 판단 σ 배수 (config.yaml analytics.abr.sigma_threshold)
            baseline_csv: Baseline 저장 경로
            results_csv:  분석 결과 이력 저장 경로
        """
        self.threshold    = threshold
        self.baseline_csv = baseline_csv
        self.results_csv  = results_csv

        self._mu:     Optional[float] = None
        self._sigma:  Optional[float] = None
        self._fitted: bool            = False
        self._n_baseline: int         = 0

    # ══════════════════════════════════════════════════════════════════════
    # Baseline 학습
    # ══════════════════════════════════════════════════════════════════════

    def fit(
        self,
        baseline_df:      pd.DataFrame,
        exclude_cols:     Optional[list] = None,
    ) -> "ABRAnalyzer":
        """
        Baseline 데이터로 μ, σ 계산.

        Args:
            baseline_df:  Baseline 기간 fish_metrics DataFrame
                          speed_px_s 컬럼 필수
            exclude_cols: 제외할 조건 컬럼 (미구현 — 추후 feeding_events 연동 후 활용)

        설계 문서 미확정:
            급이 직후 / 물갈이 직후 구간 제외 로직은
            feeding_events.csv 연동 후 구현 예정.
            현재는 전체 구간을 Baseline으로 사용.
        """
        if not NUMPY_AVAILABLE:
            logger.error("[ABR] fit: numpy/pandas 없음 — pip install numpy pandas")
            return self

        if baseline_df.empty:
            logger.warning("[ABR] fit: Baseline 데이터 없음")
            return self

        if "speed_px_s" not in baseline_df.columns:
            logger.error("[ABR] fit: 'speed_px_s' 컬럼 없음")
            return self

        speeds = baseline_df["speed_px_s"].dropna()
        n      = len(speeds)

        if n < self.MIN_BASELINE_SAMPLES:
            logger.warning(
                f"[ABR] Baseline 샘플 부족: {n}개 (최소 {self.MIN_BASELINE_SAMPLES}개). "
                "fit은 수행하지만 신뢰도 낮음."
            )

        self._mu       = float(speeds.mean())
        self._sigma    = float(speeds.std())
        self._n_baseline = n
        self._fitted   = True

        logger.info(
            f"[ABR] Baseline 완료: μ={self._mu:.3f} σ={self._sigma:.3f} "
            f"(n={n}, threshold={self.threshold}σ)"
        )
        return self

    # ══════════════════════════════════════════════════════════════════════
    # 이상 행동율 계산
    # ══════════════════════════════════════════════════════════════════════

    def compute(
        self,
        df:        pd.DataFrame,
        timestamp: Optional[float] = None,
    ) -> ABRResult:
        """
        이상 행동율 계산.

        Args:
            df:        분석 대상 fish_metrics DataFrame
            timestamp: 분석 시각 (None이면 현재 시각)

        Returns:
            ABRResult
        """
        import time
        ts = timestamp or time.time()

        if not NUMPY_AVAILABLE:
            return ABRResult(
                timestamp=ts, rate=0, n_anomaly=0, n_total=0,
                mu=0, sigma=0, threshold=self.threshold,
                valid=False, reason="numpy/pandas 미설치 — pip install numpy pandas",
            )

        if not self._fitted:
            return ABRResult(
                timestamp = ts, rate=0, n_anomaly=0, n_total=0,
                mu=0, sigma=0, threshold=self.threshold,
                valid=False,
                reason="Baseline 미학습 — fit()를 먼저 호출하세요.",
            )

        if df.empty:
            return ABRResult(
                timestamp=ts, rate=0, n_anomaly=0, n_total=0,
                mu=self._mu, sigma=self._sigma, threshold=self.threshold,
                valid=False, reason="분석 데이터 없음",
            )

        if "speed_px_s" not in df.columns:
            return ABRResult(
                timestamp=ts, rate=0, n_anomaly=0, n_total=0,
                mu=self._mu, sigma=self._sigma, threshold=self.threshold,
                valid=False, reason="'speed_px_s' 컬럼 없음",
            )

        speeds    = df["speed_px_s"].dropna()
        n_total   = len(speeds)

        if n_total == 0:
            return ABRResult(
                timestamp=ts, rate=0, n_anomaly=0, n_total=0,
                mu=self._mu, sigma=self._sigma, threshold=self.threshold,
                valid=False, reason="유효한 speed_px_s 값 없음",
            )

        # 이상 조건: |speed - μ| > threshold × σ
        anomaly_mask = (speeds - self._mu).abs() > self.threshold * self._sigma
        n_anomaly    = int(anomaly_mask.sum())
        rate         = n_anomaly / n_total

        # 개체별 통계 (논문 코드 summary 구조 반영)
        per_fish_stats = None
        if "fish_id" in df.columns and "timestamp" in df.columns:
            per_fish_stats = self._calc_per_fish_stats(df)

        return ABRResult(
            timestamp      = ts,
            rate           = round(rate, 4),
            n_anomaly      = n_anomaly,
            n_total        = n_total,
            mu             = round(self._mu, 3),
            sigma          = round(self._sigma, 3),
            threshold      = self.threshold,
            valid          = True,
            per_fish_stats = per_fish_stats,
        )

    # ══════════════════════════════════════════════════════════════════════
    # 개체별 통계
    # ══════════════════════════════════════════════════════════════════════

    def _calc_per_fish_stats(self, df: pd.DataFrame) -> list[dict]:
        """
        fish_id별 속도 통계 계산.
        논문 코드의 summary 구조(mean, std, cv, tracked_duration_sec)를 반영.

        cv (변동계수, Coefficient of Variation) = std / mean
        값이 클수록 속도 변동이 큰 불규칙한 행동 → 이상 행동 판별에 활용.

        Returns:
            list[dict] — fish_id별 통계 딕셔너리 리스트, mean_speed 내림차순 정렬
        """
        stats = []
        for fid, group in df.groupby("fish_id"):
            speeds = group["speed_px_s"].dropna()
            if len(speeds) < 2:
                continue

            mean_spd = float(speeds.mean())
            std_spd  = float(speeds.std())
            cv       = std_spd / mean_spd if mean_spd > 0 else 0.0

            # 추적 지속 시간
            ts_vals = group["timestamp"].dropna()
            tracked_duration_sec = (
                float(ts_vals.max() - ts_vals.min()) if len(ts_vals) >= 2 else 0.0
            )

            # 이상 프레임 수 (개체별)
            anomaly_mask = (speeds - self._mu).abs() > self.threshold * self._sigma
            n_anomaly_fish = int(anomaly_mask.sum())

            stats.append({
                "fish_id":             int(fid),
                "mean_speed_px_s":     round(mean_spd, 3),
                "std_speed_px_s":      round(std_spd, 3),
                "max_speed_px_s":      round(float(speeds.max()), 3),
                "cv":                  round(cv, 4),   # 변동계수
                "valid_frame_count":   len(speeds),
                "tracked_duration_sec": round(tracked_duration_sec, 2),
                "n_anomaly":           n_anomaly_fish,
                "anomaly_rate":        round(n_anomaly_fish / len(speeds), 4),
            })

        # mean_speed 내림차순 정렬 (논문 summary 정렬 방식)
        stats.sort(key=lambda x: x["mean_speed_px_s"], reverse=True)
        return stats

    def save_per_fish_stats_csv(
        self,
        per_fish_stats: list[dict],
        path: str = "data/abr_per_fish.csv",
    ) -> str:
        """개체별 통계를 CSV로 저장."""
        if not per_fish_stats:
            logger.warning("[ABR] per_fish_stats 비어 있음 — 저장 건너뜀")
            return path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fields = list(per_fish_stats[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(per_fish_stats)

        logger.info(f"[ABR] 개체별 통계 저장: {path}")
        return path

    # ══════════════════════════════════════════════════════════════════════
    # 저장 / 로드
    # ══════════════════════════════════════════════════════════════════════

    def save_baseline(self, path: Optional[str] = None) -> str:
        """Baseline μ, σ를 CSV로 저장"""
        if not self._fitted:
            raise RuntimeError("Baseline이 학습되지 않았습니다. fit()을 먼저 호출하세요.")

        save_path = path or self.baseline_csv
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["mu", "sigma", "n_baseline", "threshold"])
            writer.writeheader()
            writer.writerow({
                "mu":          self._mu,
                "sigma":       self._sigma,
                "n_baseline":  self._n_baseline,
                "threshold":   self.threshold,
            })

        logger.info(f"[ABR] Baseline 저장: {save_path}")
        return save_path

    def load_baseline(self, path: Optional[str] = None) -> bool:
        """저장된 Baseline 불러오기. 성공 시 True 반환."""
        load_path = path or self.baseline_csv
        p = Path(load_path)
        if not p.exists():
            logger.warning(f"[ABR] Baseline 파일 없음: {load_path}")
            return False

        with open(load_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._mu         = float(row["mu"])
                self._sigma      = float(row["sigma"])
                self._n_baseline = int(row.get("n_baseline", 0))
                self.threshold   = float(row.get("threshold", self.threshold))
                self._fitted     = True
                break

        logger.info(
            f"[ABR] Baseline 로드: μ={self._mu:.3f} σ={self._sigma:.3f} "
            f"(n={self._n_baseline})"
        )
        return True

    def save_result(self, result: ABRResult, path: Optional[str] = None) -> str:
        """ABR 분석 결과를 CSV에 추가 저장 (이력 관리)"""
        save_path = path or self.results_csv
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        fields     = list(ABRResult.__dataclass_fields__.keys())
        write_header = not Path(save_path).exists()

        with open(save_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(asdict(result))

        return save_path

    # ══════════════════════════════════════════════════════════════════════
    # 상태 조회
    # ══════════════════════════════════════════════════════════════════════

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def baseline_stats(self) -> Optional[dict]:
        if not self._fitted:
            return None
        return {
            "mu":         self._mu,
            "sigma":      self._sigma,
            "n_baseline": self._n_baseline,
            "threshold":  self.threshold,
        }


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    import numpy as np

    logging.basicConfig(level=logging.INFO)

    # 더미 Baseline 데이터 (정상 행동 분포)
    rng = np.random.default_rng(42)
    baseline_speeds = rng.normal(loc=30.0, scale=8.0, size=2000)
    baseline_df = pd.DataFrame({"speed_px_s": baseline_speeds})

    analyzer = ABRAnalyzer(threshold=2.0)
    analyzer.fit(baseline_df)

    # 정상 데이터 테스트
    normal_df = pd.DataFrame({"speed_px_s": rng.normal(30.0, 8.0, 500)})
    result_normal = analyzer.compute(normal_df)
    print(f"\n[정상] ABR={result_normal.rate:.4f} ({result_normal.n_anomaly}/{result_normal.n_total})")

    # 이상 데이터 테스트 (일부 급격한 속도 변화)
    anomaly_speeds = np.concatenate([
        rng.normal(30.0, 8.0, 400),
        rng.normal(120.0, 5.0, 100),   # 이상 행동 (급가속)
    ])
    anomaly_df = pd.DataFrame({"speed_px_s": anomaly_speeds})
    result_anomaly = analyzer.compute(anomaly_df)
    print(f"[이상] ABR={result_anomaly.rate:.4f} ({result_anomaly.n_anomaly}/{result_anomaly.n_total})")

    # 저장 / 로드 테스트
    analyzer.save_baseline("data/abr_baseline_test.csv")
    analyzer.save_result(result_anomaly, "data/abr_results_test.csv")

    analyzer2 = ABRAnalyzer()
    analyzer2.load_baseline("data/abr_baseline_test.csv")
    print(f"\n로드 확인: {analyzer2.baseline_stats}")
