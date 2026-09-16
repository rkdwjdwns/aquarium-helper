"""
analytics/activity_pattern.py — 활동 패턴 분석
금붕어 자동 사육 AI 시스템 (v2.0)

원본 SQL 기반 설계를 CSV 방식으로 전환.
로직(Baseline, z-score, 이상 탐지, 시각화)은 동일하게 유지.

변경 사항 (원본 대비):
    - SQLite → CSV 파일 직접 로드
    - zone 판단 기준: frame_height 480px 하드코딩 → config 기반 (416px)
    - zone_top/bottom_ratio: 1/3, 2/3 하드코딩 → config.yaml 값 사용
    - Baseline 없을 때 명시적 경고 및 빈 DataFrame 반환
    - Baseline CSV 저장/로드 지원
    - 시각화 matplotlib 선택적 import

CSV 저장:
    data/activity_baseline.csv
    data/activity_pattern_report_날짜.csv
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("[ActivityPattern] matplotlib 없음 — 시각화 기능 비활성화")


# ─────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class AnalyzerConfig:
    """
    활동 패턴 분석기 설정.
    config.yaml 값과 동기화해서 사용할 것.
    """
    csv_dir:             str   = "data"           # fish_metrics CSV 디렉토리
    metrics_prefix:      str   = "fish_metrics"   # CSV 파일명 prefix
    frame_width:         int   = 416              # FPS 테스트 확정값
    frame_height:        int   = 416              # FPS 테스트 확정값
    zone_top_ratio:      float = 0.3              # config.yaml zone.top_ratio
    zone_bottom_ratio:   float = 0.7              # config.yaml zone.bottom_ratio
    anomaly_z_threshold: float = 2.0              # config.yaml analytics.abr.sigma_threshold
    baseline_csv:        str   = "data/activity_baseline.csv"


# ─────────────────────────────────────────────────────────────────────────
# 분석기
# ─────────────────────────────────────────────────────────────────────────
class MultiDayActivityAnalyzer:
    """
    CSV에서 여러 날의 fish_metrics 데이터를 로드해
    날짜별/시간대별 활동 패턴과 이상 패턴을 분석.

    원본 SQL 버전과 동일한 public API 유지.
    """

    def __init__(self, config: AnalyzerConfig) -> None:
        self.config = config

    # ══════════════════════════════════════════════════════════════════════
    # 데이터 로드
    # ══════════════════════════════════════════════════════════════════════

    def load_data(
        self,
        start_date: Optional[str]       = None,
        end_date:   Optional[str]       = None,
        csv_paths:  Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        fish_metrics CSV에서 데이터 로드.

        Args:
            start_date: 'YYYY-MM-DD' 시작 날짜 필터 (선택)
            end_date:   'YYYY-MM-DD' 종료 날짜 필터 (선택)
            csv_paths:  파일 경로 직접 지정 (미지정 시 csv_dir 자동 탐색)

        Returns:
            timestamp, fish_id, activity, center_x, center_y,
            size, date, hour, zone 컬럼 포함 DataFrame
        """
        if csv_paths is None:
            csv_paths = sorted(
                str(p) for p in
                Path(self.config.csv_dir).glob(f"{self.config.metrics_prefix}_*.csv")
            )

        if not csv_paths:
            logger.warning(f"[ActivityPattern] CSV 파일 없음: {self.config.csv_dir}")
            return pd.DataFrame()

        frames = []
        for path in csv_paths:
            try:
                frames.append(pd.read_csv(path))
            except Exception as e:
                logger.warning(f"[ActivityPattern] CSV 로드 실패: {path} → {e}")

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)

        # timestamp (Unix float) → datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", errors="coerce")
        df = df.dropna(subset=["timestamp"])

        if df.empty:
            logger.warning("[ActivityPattern] 유효한 timestamp 행 없음")
            return df

        df["date"] = df["timestamp"].dt.strftime("%Y-%m-%d")
        df["hour"] = df["timestamp"].dt.hour

        # 날짜 필터
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]

        if df.empty:
            logger.warning(f"[ActivityPattern] 날짜 필터 후 데이터 없음 ({start_date} ~ {end_date})")
            return df

        # zone: CSV에 이미 있으면 그대로 사용, 없으면 config 기반 재계산
        if "zone" not in df.columns:
            df["zone"] = df["center_y"].apply(self._classify_zone)
        # else: fish_metrics CSV의 zone 컬럼을 그대로 신뢰 (파이프라인 기준 일관성 유지)

        # 컬럼 통일: activity / speed_px_s
        if "activity" not in df.columns:
            if "speed_px_s" in df.columns:
                df["activity"] = df["speed_px_s"]
            else:
                logger.error("[ActivityPattern] 'activity' 또는 'speed_px_s' 컬럼 없음")
                return pd.DataFrame()

        # 컬럼 통일: size / size_index
        if "size" not in df.columns:
            if "size_index" in df.columns:
                df["size"] = df["size_index"]
            else:
                logger.warning("[ActivityPattern] 'size' 컬럼 없음 — 0으로 채움")
                df["size"] = 0.0

        logger.info(
            f"[ActivityPattern] 로드 완료: {len(df)}행, "
            f"{df['date'].nunique()}일, 파일 {len(csv_paths)}개"
        )
        return df.reset_index(drop=True)

    def _classify_zone(self, center_y: float) -> str:
        """
        Y 위치 기준 TOP/MID/BOT 분류.
        config.yaml zone 설정값 사용 (원본 1/3, 2/3 하드코딩 교체).
        """
        h = self.config.frame_height
        if center_y < h * self.config.zone_top_ratio:
            return "TOP"
        if center_y < h * self.config.zone_bottom_ratio:
            return "MID"
        return "BOT"

    # ══════════════════════════════════════════════════════════════════════
    # 날짜별/시간대별 요약
    # ══════════════════════════════════════════════════════════════════════

    def build_daily_hourly_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        날짜별/시간대별 요약 생성.

        반환 컬럼:
            date, hour, avg_activity, std_activity, avg_size,
            fish_count, top_ratio, mid_ratio, bot_ratio
        """
        if df.empty:
            return pd.DataFrame()

        grouped = (
            df.groupby(["date", "hour"])
            .agg(
                avg_activity=("activity", "mean"),
                std_activity=("activity", "std"),
                avg_size    =("size",     "mean"),
                fish_count  =("fish_id",  "nunique"),
            )
            .reset_index()
        )
        grouped["std_activity"] = grouped["std_activity"].fillna(0.0)

        # zone 비율
        zone_counts  = (df.groupby(["date", "hour", "zone"]).size()
                        .reset_index(name="count"))
        total_counts = (df.groupby(["date", "hour"]).size()
                        .reset_index(name="total_count"))
        zone_ratios  = zone_counts.merge(total_counts, on=["date", "hour"], how="left")
        zone_ratios["ratio"] = zone_ratios["count"] / zone_ratios["total_count"]

        zone_pivot = (
            zone_ratios.pivot_table(
                index=["date", "hour"], columns="zone",
                values="ratio", fill_value=0.0,
            ).reset_index()
        )
        for col in ["TOP", "MID", "BOT"]:
            if col not in zone_pivot.columns:
                zone_pivot[col] = 0.0

        zone_pivot = zone_pivot.rename(columns={
            "TOP": "top_ratio", "MID": "mid_ratio", "BOT": "bot_ratio"
        })

        summary = grouped.merge(zone_pivot, on=["date", "hour"], how="left")
        for col in ["top_ratio", "mid_ratio", "bot_ratio"]:
            if col not in summary.columns:
                summary[col] = 0.0

        return summary.sort_values(["date", "hour"]).reset_index(drop=True)

    # ══════════════════════════════════════════════════════════════════════
    # Baseline 생성 / 저장 / 로드
    # ══════════════════════════════════════════════════════════════════════

    def build_hourly_baseline(self, daily_hourly_df: pd.DataFrame) -> pd.DataFrame:
        """
        여러 날 기준 시간대별 Baseline 생성.

        반환 컬럼:
            hour, baseline_activity_mean, baseline_activity_std,
            baseline_size_mean, baseline_size_std,
            baseline_top_ratio_mean, baseline_mid_ratio_mean,
            baseline_bot_ratio_mean, sample_days
        """
        if daily_hourly_df.empty:
            logger.warning("[ActivityPattern] Baseline 생성 실패: 입력 데이터 없음")
            return pd.DataFrame()

        sample_days = daily_hourly_df["date"].nunique()
        if sample_days < 2:
            logger.warning(
                f"[ActivityPattern] Baseline 데이터 {sample_days}일치 — "
                "최소 2일 이상 권장 (설계 문서: 3일)"
            )

        baseline = (
            daily_hourly_df.groupby("hour")
            .agg(
                baseline_activity_mean=("avg_activity", "mean"),
                baseline_activity_std =("avg_activity", "std"),
                baseline_size_mean    =("avg_size",     "mean"),
                baseline_size_std     =("avg_size",     "std"),
                baseline_top_ratio_mean=("top_ratio",   "mean"),
                baseline_mid_ratio_mean=("mid_ratio",   "mean"),
                baseline_bot_ratio_mean=("bot_ratio",   "mean"),
                sample_days           =("date",         "nunique"),
            )
            .reset_index()
        )
        baseline["baseline_activity_std"] = baseline["baseline_activity_std"].fillna(0.0)
        baseline["baseline_size_std"]     = baseline["baseline_size_std"].fillna(0.0)

        logger.info(f"[ActivityPattern] Baseline 생성: {sample_days}일치, {len(baseline)}시간대")
        return baseline.sort_values("hour").reset_index(drop=True)

    def save_baseline_to_csv(
        self,
        baseline_df: pd.DataFrame,
        path:        Optional[str] = None,
    ) -> str:
        """Baseline CSV 저장"""
        save_path = path or self.config.baseline_csv
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        baseline_df.to_csv(save_path, index=False, encoding="utf-8")
        logger.info(f"[ActivityPattern] Baseline 저장: {save_path}")
        return save_path

    def load_baseline_from_csv(self, path: Optional[str] = None) -> pd.DataFrame:
        """저장된 Baseline 불러오기"""
        load_path = path or self.config.baseline_csv
        p = Path(load_path)
        if not p.exists():
            logger.warning(f"[ActivityPattern] Baseline 파일 없음: {load_path}")
            return pd.DataFrame()
        df = pd.read_csv(load_path, encoding="utf-8")
        logger.info(f"[ActivityPattern] Baseline 로드: {load_path} ({len(df)}시간대)")
        return df

    # ══════════════════════════════════════════════════════════════════════
    # 이상 탐지
    # ══════════════════════════════════════════════════════════════════════

    def detect_daily_anomalies(
        self,
        daily_hourly_df: pd.DataFrame,
        baseline_df:     pd.DataFrame,
        target_date:     Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Baseline 시간대 평균과 비교해 이상 패턴 탐지.

        z = (날짜 시간대 avg_activity - Baseline 평균) / Baseline 표준편차

        Args:
            daily_hourly_df: build_daily_hourly_summary() 결과
            baseline_df:     build_hourly_baseline() 또는 load_baseline_from_csv() 결과
            target_date:     특정 날짜만 분석 ('YYYY-MM-DD'), None이면 전체

        Returns:
            원본 컬럼 + activity_z_score, size_z_score,
            activity_diff, size_diff, anomaly_type, is_anomaly
        """
        if daily_hourly_df.empty:
            logger.warning("[ActivityPattern] detect: daily_hourly_df 비어 있음")
            return pd.DataFrame()

        if baseline_df.empty:
            logger.error(
                "[ActivityPattern] Baseline 없음 — 이상 탐지 불가. "
                "build_hourly_baseline() 또는 load_baseline_from_csv()를 먼저 호출하세요."
            )
            return pd.DataFrame()

        compare_df = daily_hourly_df.merge(baseline_df, on="hour", how="left")

        if target_date:
            compare_df = compare_df[compare_df["date"] == target_date].copy()
            if compare_df.empty:
                logger.warning(f"[ActivityPattern] target_date={target_date} 데이터 없음")
                return pd.DataFrame()

        def _z(value, mean, std):
            return 0.0 if (std == 0 or pd.isna(std)) else (value - mean) / std

        compare_df = compare_df.copy()
        compare_df["activity_z_score"] = compare_df.apply(
            lambda r: _z(r["avg_activity"],
                         r["baseline_activity_mean"],
                         r["baseline_activity_std"]), axis=1)

        compare_df["size_z_score"] = compare_df.apply(
            lambda r: _z(r["avg_size"],
                         r["baseline_size_mean"],
                         r["baseline_size_std"]), axis=1)

        compare_df["activity_diff"] = (
            compare_df["avg_activity"] - compare_df["baseline_activity_mean"]
        )
        compare_df["size_diff"] = (
            compare_df["avg_size"] - compare_df["baseline_size_mean"]
        )

        thresh = self.config.anomaly_z_threshold
        compare_df["anomaly_type"] = compare_df["activity_z_score"].apply(
            lambda z: "high_activity" if z >= thresh
                      else ("low_activity" if z <= -thresh else "normal")
        )
        compare_df["is_anomaly"] = compare_df["anomaly_type"] != "normal"

        n_anomaly = int(compare_df["is_anomaly"].sum())
        logger.info(f"[ActivityPattern] 이상 탐지: {n_anomaly}건 / {len(compare_df)}시간대")

        return compare_df.sort_values(["date", "hour"]).reset_index(drop=True)

    def find_repeated_anomaly_hours(
        self, anomalies_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        여러 날 동안 반복적으로 이상이 발생한 시간대 탐지.
        예: 매일 오전 8시에 활동량이 유난히 높거나 낮은 패턴.
        """
        if anomalies_df.empty:
            return pd.DataFrame()

        only = anomalies_df[anomalies_df["is_anomaly"]].copy()
        if only.empty:
            logger.info("[ActivityPattern] 반복 이상 시간대 없음")
            return pd.DataFrame()

        return (
            only.groupby(["hour", "anomaly_type"])
            .agg(
                anomaly_days          =("date",              "nunique"),
                mean_activity_z_score =("activity_z_score",  "mean"),
                mean_activity_diff    =("activity_diff",      "mean"),
            )
            .reset_index()
            .sort_values(["anomaly_days", "hour"], ascending=[False, True])
            .reset_index(drop=True)
        )

    # ══════════════════════════════════════════════════════════════════════
    # 전체 리포트
    # ══════════════════════════════════════════════════════════════════════

    def generate_report(
        self,
        start_date:  Optional[str]       = None,
        end_date:    Optional[str]       = None,
        target_date: Optional[str]       = None,
        csv_paths:   Optional[List[str]] = None,
        save_report: bool                = False,
    ) -> Dict[str, Any]:
        """
        전체 분석 리포트 생성.

        Args:
            save_report: True면 daily_comparison을 CSV로 저장

        Returns:
            raw_data, daily_hourly_summary, hourly_baseline,
            daily_comparison, repeated_anomaly_hours, summary
        """
        raw_df = self.load_data(
            start_date=start_date, end_date=end_date, csv_paths=csv_paths
        )
        if raw_df.empty:
            return {
                "raw_data": pd.DataFrame(),
                "daily_hourly_summary": pd.DataFrame(),
                "hourly_baseline": pd.DataFrame(),
                "daily_comparison": pd.DataFrame(),
                "repeated_anomaly_hours": pd.DataFrame(),
                "summary": {"message": "조건에 맞는 데이터가 없습니다."},
            }

        daily_hourly = self.build_daily_hourly_summary(raw_df)
        baseline     = self.build_hourly_baseline(daily_hourly)
        comparison   = self.detect_daily_anomalies(
            daily_hourly_df=daily_hourly,
            baseline_df=baseline,
            target_date=target_date,
        )
        repeated = self.find_repeated_anomaly_hours(comparison)

        summary = {
            "total_rows":    len(raw_df),
            "total_days":    raw_df["date"].nunique(),
            "date_range":    {
                "start": raw_df["date"].min(),
                "end":   raw_df["date"].max(),
            },
            "target_date":   target_date,
            "anomaly_count": int(comparison["is_anomaly"].sum())
                             if not comparison.empty else 0,
        }

        if save_report and not comparison.empty:
            ts_str    = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = (
                Path(self.config.csv_dir)
                / f"activity_pattern_report_{ts_str}.csv"
            )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            comparison.to_csv(report_path, index=False, encoding="utf-8")
            logger.info(f"[ActivityPattern] 리포트 저장: {report_path}")

        return {
            "raw_data":               raw_df,
            "daily_hourly_summary":   daily_hourly,
            "hourly_baseline":        baseline,
            "daily_comparison":       comparison,
            "repeated_anomaly_hours": repeated,
            "summary":                summary,
        }

    # ══════════════════════════════════════════════════════════════════════
    # 시각화
    # ══════════════════════════════════════════════════════════════════════

    def visualize_target_date_vs_baseline(
        self,
        comparison_df: pd.DataFrame,
        target_date:   str,
        save_path:     str = "data/target_date_vs_baseline.png",
    ) -> None:
        """특정 날짜 활동량 vs Baseline 비교 시각화"""
        if not MATPLOTLIB_AVAILABLE:
            logger.warning("[ActivityPattern] matplotlib 없음 — 시각화 불가")
            return
        if comparison_df.empty:
            return

        target_df = comparison_df[comparison_df["date"] == target_date].copy()
        if target_df.empty:
            logger.warning(f"[ActivityPattern] {target_date} 데이터 없음")
            return

        plt.figure(figsize=(12, 6))
        plt.plot(target_df["hour"], target_df["avg_activity"],
                 marker="o", linewidth=2, label=f"{target_date}")
        plt.plot(target_df["hour"], target_df["baseline_activity_mean"],
                 marker="o", linewidth=2, linestyle="--", label="Baseline 평균")

        anomaly_df = target_df[target_df["is_anomaly"]]
        if not anomaly_df.empty:
            plt.scatter(anomaly_df["hour"], anomaly_df["avg_activity"],
                        s=100, color="red", zorder=5, label="이상 시간대")

        plt.xlabel("시간")
        plt.ylabel("평균 활동량 (px/s)")
        plt.title(f"{target_date} 활동 패턴 vs Baseline")
        plt.xticks(range(24))
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150)
        plt.close()
        logger.info(f"[ActivityPattern] 시각화 저장: {save_path}")

    def visualize_baseline_pattern(
        self,
        baseline_df: pd.DataFrame,
        save_path:   str = "data/baseline_pattern.png",
    ) -> None:
        """Baseline 시간대별 평균 활동량 시각화"""
        if not MATPLOTLIB_AVAILABLE:
            return
        if baseline_df.empty:
            return

        plt.figure(figsize=(12, 6))
        plt.plot(baseline_df["hour"], baseline_df["baseline_activity_mean"],
                 marker="o", linewidth=2)
        plt.fill_between(baseline_df["hour"],
                         baseline_df["baseline_activity_mean"], alpha=0.3)
        plt.xlabel("시간")
        plt.ylabel("기준 평균 활동량 (px/s)")
        plt.title("여러 날 기준 시간대별 평균 활동 패턴")
        plt.xticks(range(24))
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150)
        plt.close()
        logger.info(f"[ActivityPattern] Baseline 시각화 저장: {save_path}")


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 예시
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    config   = AnalyzerConfig(
        csv_dir             = "data",
        frame_height        = 416,
        zone_top_ratio      = 0.3,
        zone_bottom_ratio   = 0.7,
        anomaly_z_threshold = 2.0,
    )
    analyzer = MultiDayActivityAnalyzer(config)

    report = analyzer.generate_report(
        start_date  = "2026-05-01",
        end_date    = "2026-05-07",
        target_date = "2026-05-07",
        save_report = True,
    )

    print("\n[분석 요약]")
    print(report["summary"])

    if not report["hourly_baseline"].empty:
        print("\n[Baseline 시간대 평균 (상위 5개)]")
        print(report["hourly_baseline"].head())

    if not report["daily_comparison"].empty:
        print("\n[특정 날짜 비교]")
        cols = ["date", "hour", "avg_activity", "baseline_activity_mean",
                "activity_z_score", "anomaly_type", "is_anomaly"]
        print(report["daily_comparison"][cols].head(24))

    print("\n[반복 이상 시간대]")
    print(report["repeated_anomaly_hours"])
