"""
analytics/feeding_response.py — 급이 반응 분석
금붕어 자동 사육 AI 시스템 (v2.0)

demo_pipeline.py의 fish_metrics 행 구조와 직접 연동.
FrameData는 pipeline에서 변환 없이 바로 생성 가능하도록 설계.

CSV 저장:
    data/feeding_response.csv

사용 예:
    from analytics.feeding_response import FeedingResponseAnalyzer, FrameData

    analyzer = FeedingResponseAnalyzer()
    result = analyzer.analyze(
        before_frames=before,
        during_frames=during,
        feeding_ts=time.time(),
        sensor_data={"water_temp": 22.5, "ph": 7.2},
    )
    analyzer.save_to_csv()
"""

from __future__ import annotations

import csv
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# 데이터 구조
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class FrameData:
    """
    단일 프레임의 분석 데이터.
    demo_pipeline.py의 fish_metrics 행에서 직접 생성 가능.

    Attributes:
        timestamp:      프레임 타임스탬프 (time.time() 기준, Unix)
        fish_positions: 금붕어별 중심 좌표 [(cx, cy), ...]  px 단위
        fish_speeds:    금붕어별 이동 속도 [speed_px_s, ...]  px/s 단위
                        fish_positions과 인덱스 1:1 대응 필수
        frame_height:   프레임 세로 해상도 — zone/수면 판단에 사용
                        FPS 테스트 확정값 416px를 기본값으로 사용
    """
    timestamp:      float
    fish_positions: list[tuple[float, float]]
    fish_speeds:    list[float]
    frame_height:   int = 416

    def __post_init__(self):
        if len(self.fish_positions) != len(self.fish_speeds):
            raise ValueError(
                f"fish_positions({len(self.fish_positions)})와 "
                f"fish_speeds({len(self.fish_speeds)}) 길이가 다릅니다."
            )
        if self.frame_height <= 0:
            raise ValueError(f"frame_height는 양수여야 합니다: {self.frame_height}")

    @classmethod
    def from_metrics_rows(cls, rows: list[dict]) -> "FrameData":
        """
        demo_pipeline.py의 fish_metrics 행 리스트 → FrameData 변환.

        같은 frame_idx를 공유하는 행들의 리스트를 넘긴다.
        필수 키: timestamp, center_x, center_y, speed_px_s
        선택 키: frame_height (없으면 416 사용)

        Example:
            rows = [
                {"timestamp": 1234.0, "frame_idx": 10,
                 "center_x": 200, "center_y": 80, "speed_px_s": 45.2},
                {"timestamp": 1234.0, "frame_idx": 10,
                 "center_x": 310, "center_y": 200, "speed_px_s": 12.1},
            ]
            fd = FrameData.from_metrics_rows(rows)
        """
        if not rows:
            raise ValueError("rows가 비어 있습니다.")

        required = {"timestamp", "center_x", "center_y", "speed_px_s"}
        missing  = required - rows[0].keys()
        if missing:
            raise KeyError(f"필수 키 누락: {missing}")

        return cls(
            timestamp      = float(rows[0]["timestamp"]),
            fish_positions = [(float(r["center_x"]), float(r["center_y"])) for r in rows],
            fish_speeds    = [float(r["speed_px_s"]) for r in rows],
            frame_height   = int(rows[0].get("frame_height", 416)),
        )


@dataclass
class FeedingRecord:
    """급이 이벤트 1회 기록 (CSV 저장 단위)"""
    feeding_ts:            float
    before_activity_mean:  float
    during_activity_mean:  float
    score:                 int
    status:                str
    response_time_sec:     float
    activity_increase_pct: float
    surface_visits:        int
    water_temp:            Optional[float] = None
    ph:                    Optional[float] = None
    do_mg_l:               Optional[float] = None
    turbidity_ntu:         Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────
# 분석기
# ─────────────────────────────────────────────────────────────────────────
class FeedingResponseAnalyzer:
    """
    급이 반응 평가기.

    설계 문서 6.1 기준.
    가중치(w_*)는 config.yaml FRS 가중치와 대응하며
    실측 후 조정 가능하도록 생성자 파라미터로 노출.
    """

    # 수면 근접 판단: zone_top_ratio(0.3)보다 좁게 (먹이 탐색 특화)
    SURFACE_THRESHOLD_RATIO: float = 0.15
    # 활동 급증 판단 배율
    ACTIVITY_SURGE_RATIO:    float = 1.3

    def __init__(
        self,
        w_response_time: float = 0.30,   # 미확정 — config.yaml FRS.w1
        w_activity:      float = 0.40,   # 미확정 — config.yaml FRS.w2
        w_surface:       float = 0.30,   # 미확정 — config.yaml FRS.w3
        before_sec:      float = 60.0,
        during_sec:      float = 300.0,
        csv_path:        str   = "data/feeding_response.csv",
    ) -> None:
        total = w_response_time + w_activity + w_surface
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"가중치 합이 1.0이어야 합니다. 현재: {total:.3f}")

        self.w_response_time = w_response_time
        self.w_activity      = w_activity
        self.w_surface       = w_surface
        self.before_sec      = before_sec
        self.during_sec      = during_sec
        self.csv_path        = csv_path
        self._records: list[FeedingRecord] = []

    # ══════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════

    def analyze(
        self,
        before_frames: list[FrameData],
        during_frames: list[FrameData],
        feeding_ts:    float,
        sensor_data:   Optional[dict] = None,
    ) -> dict:
        """
        급이 반응 종합 평가.

        Args:
            before_frames: 급이 전 구간 FrameData 리스트
            during_frames: 급이 중 구간 FrameData 리스트
            feeding_ts:    급이 이벤트 시각 (time.time())
            sensor_data:   {"water_temp", "ph", "do_mg_l", "turbidity_ntu"}

        Returns:
            score, status, comment, response_time_sec,
            activity_increase_percent, surface_visits,
            sub_scores, recommendations
        """
        if not before_frames:
            return self._empty_result("before_frames가 비어 있습니다.")
        if not during_frames:
            return self._empty_result("during_frames가 비어 있습니다.")

        rt   = self._calc_response_time(before_frames, during_frames)
        ai   = self._calc_activity_increase(before_frames, during_frames)
        sv   = self._count_surface_visits(during_frames)
        dur  = self._duration(during_frames)

        sub  = self._calc_sub_scores(rt, ai, sv, dur)
        score = self._calc_score(sub)
        status, comment = self._evaluate_status(score)

        sd = sensor_data or {}
        self._records.append(FeedingRecord(
            feeding_ts            = feeding_ts,
            before_activity_mean  = round(self._mean_speed(before_frames), 3),
            during_activity_mean  = round(self._mean_speed(during_frames), 3),
            score                 = score,
            status                = status,
            response_time_sec     = round(rt, 2),
            activity_increase_pct = round(ai, 1),
            surface_visits        = sv,
            water_temp            = sd.get("water_temp"),
            ph                    = sd.get("ph"),
            do_mg_l               = sd.get("do_mg_l"),
            turbidity_ntu         = sd.get("turbidity_ntu"),
        ))

        return {
            "score":                     score,
            "status":                    status,
            "comment":                   comment,
            "response_time_sec":         round(rt, 2),
            "activity_increase_percent": round(ai, 1),
            "surface_visits":            sv,
            "sub_scores":                sub,
            "recommendations":           self._recommendations(score, sub),
        }

    def build_frames_from_pipeline(
        self,
        metrics_rows: list[dict],
        feeding_ts:   float,
    ) -> tuple[list[FrameData], list[FrameData]]:
        """
        demo_pipeline.py의 fish_metrics 버퍼에서
        before/during FrameData 리스트를 자동 생성.

        Args:
            metrics_rows: fish_metrics 전체 버퍼 (list[dict])
            feeding_ts:   급이 이벤트 시각

        Returns:
            (before_frames, during_frames)
        """
        before_rows = [
            r for r in metrics_rows
            if feeding_ts - self.before_sec <= r["timestamp"] < feeding_ts
        ]
        during_rows = [
            r for r in metrics_rows
            if feeding_ts <= r["timestamp"] < feeding_ts + self.during_sec
        ]
        return (
            self._rows_to_frames(before_rows),
            self._rows_to_frames(during_rows),
        )

    def save_to_csv(self, path: Optional[str] = None) -> str:
        """
        누적된 급이 기록을 CSV에 추가 저장 후 내부 버퍼 초기화.
        파일이 없으면 헤더 포함 생성, 있으면 append.
        """
        save_path = path or self.csv_path
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        fields = list(FeedingRecord.__dataclass_fields__.keys())
        write_header = not Path(save_path).exists()

        with open(save_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if write_header:
                writer.writeheader()
            for r in self._records:
                writer.writerow(asdict(r))

        n = len(self._records)
        self._records.clear()
        logger.info(f"[FRS] {n}건 저장 → {save_path}")
        return save_path

    # ══════════════════════════════════════════════════════════════════════
    # Private — 지표 계산
    # ══════════════════════════════════════════════════════════════════════

    def _calc_response_time(self, before: list[FrameData], during: list[FrameData]) -> float:
        baseline  = max(self._mean_speed(before), 0.1)
        threshold = baseline * self.ACTIVITY_SURGE_RATIO
        t0        = during[0].timestamp

        for frame in during:
            if self._mean_speed([frame]) >= threshold:
                return max(0.0, frame.timestamp - t0)
        return self._duration(during)

    def _calc_activity_increase(self, before: list[FrameData], during: list[FrameData]) -> float:
        m_before = self._mean_speed(before)
        m_during = self._mean_speed(during)
        return (m_during - m_before) / max(m_before, 0.1) * 100.0

    def _count_surface_visits(self, during: list[FrameData]) -> int:
        visits, in_zone = 0, False
        for frame in during:
            if not frame.fish_positions:
                in_zone = False
                continue
            threshold_y = frame.frame_height * self.SURFACE_THRESHOLD_RATIO
            near = any(y < threshold_y for _, y in frame.fish_positions)
            if near and not in_zone:
                visits += 1
                in_zone = True
            elif not near:
                in_zone = False
        return visits

    # ══════════════════════════════════════════════════════════════════════
    # Private — 점수 산출
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _calc_sub_scores(rt: float, ai: float, sv: int, dur: float) -> dict:
        if rt <= 5:       rt_s = 100
        elif rt <= 15:    rt_s = 80
        elif rt <= 30:    rt_s = 60
        elif rt <= 60:    rt_s = 40
        else:             rt_s = 20

        if ai >= 100:     ac_s = 100
        elif ai >= 50:    ac_s = 80
        elif ai >= 20:    ac_s = 60
        elif ai >= 0:     ac_s = 40
        else:             ac_s = 20

        vpm = sv / max(dur / 60.0, 0.01)
        if vpm >= 3.0:    sv_s = 100
        elif vpm >= 2.0:  sv_s = 80
        elif vpm >= 1.0:  sv_s = 60
        elif vpm >= 0.5:  sv_s = 40
        else:             sv_s = 20

        return {"response_time_score": rt_s, "activity_score": ac_s, "surface_score": sv_s}

    def _calc_score(self, sub: dict) -> int:
        raw = (
            sub["response_time_score"] * self.w_response_time
            + sub["activity_score"]    * self.w_activity
            + sub["surface_score"]     * self.w_surface
        )
        return int(round(min(max(raw, 0), 100)))

    # ══════════════════════════════════════════════════════════════════════
    # Private — 평가 & 권장사항
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _evaluate_status(score: int) -> tuple[str, str]:
        if score >= 80:   return "excellent", "매우 건강한 식욕"
        elif score >= 60: return "good",      "정상적인 식욕"
        elif score >= 40: return "fair",      "식욕 약간 저하"
        else:             return "poor",      "식욕 부진 — 건강 체크 필요"

    def _recommendations(self, score: int, sub: dict) -> list[str]:
        if score >= 80:
            return ["건강 상태 양호 — 현재 환경 유지"]

        recs = []
        if score >= 60:
            recs.append("활동성 관찰 지속")
            if sub["surface_score"] < 60:
                recs.append("수면 접근 빈도 낮음 — 먹이 부유 시간 확인")
            return recs

        if sub["response_time_score"] < 60:
            recs.append("반응 속도 저하 — 급이 시간대 또는 주기 재검토")
        if sub["activity_score"] < 60:
            recs.append("활동 증가폭 낮음 — 수온(20~24°C) 및 DO 수준 확인")
        if sub["surface_score"] < 60:
            recs.append("수면 탐색 부족 — 먹이 크기·종류 변경 고려")
        if score < 40:
            recs.append("수질 전반 점검 (pH, NH₃, NO₂) 권장")
            recs.append("급이량 20~30% 감량 후 반응 재평가")
            recs.append("이상 행동(선회, 급부상) 여부 병행 관찰")

        return recs or ["관찰 지속"]

    # ══════════════════════════════════════════════════════════════════════
    # Private — 유틸
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _mean_speed(frames: list[FrameData]) -> float:
        speeds = [s for f in frames for s in f.fish_speeds]
        return float(np.mean(speeds)) if speeds else 0.0

    @staticmethod
    def _duration(frames: list[FrameData]) -> float:
        if len(frames) < 2:
            return 0.0
        return frames[-1].timestamp - frames[0].timestamp

    @staticmethod
    def _rows_to_frames(rows: list[dict]) -> list[FrameData]:
        """fish_metrics 행을 frame_idx 기준으로 그루핑해 FrameData 리스트 반환."""
        grouped: dict = defaultdict(list)
        for r in rows:
            key = r.get("frame_idx", r["timestamp"])
            grouped[key].append(r)

        frames = []
        for key in sorted(grouped):
            try:
                frames.append(FrameData.from_metrics_rows(grouped[key]))
            except (KeyError, ValueError) as e:
                logger.warning(f"[FRS] 행 변환 실패 key={key}: {e}")
        return frames

    @staticmethod
    def _empty_result(reason: str = "데이터 부족") -> dict:
        return {
            "score": 0, "status": "unknown", "comment": reason,
            "response_time_sec": -1.0, "activity_increase_percent": 0.0,
            "surface_visits": 0,
            "sub_scores": {"response_time_score": 0, "activity_score": 0, "surface_score": 0},
            "recommendations": ["충분한 프레임 데이터 수집 후 재시도"],
        }


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import random

    rng = random.Random(42)
    FPS = 14

    def _make_frames(n_sec, base_speed, t_offset, near_surface=False):
        frames = []
        for i in range(n_sec * FPS):
            noise = rng.uniform(0.8, 1.2)
            y_val = rng.uniform(0, 60) if near_surface else rng.uniform(100, 380)
            frames.append(FrameData(
                timestamp      = t_offset + i / FPS,
                fish_positions = [(rng.uniform(0, 416), y_val) for _ in range(3)],
                fish_speeds    = [base_speed * noise for _ in range(3)],
                frame_height   = 416,
            ))
        return frames

    before = _make_frames(60,  base_speed=8.0,  t_offset=0.0)
    during = _make_frames(120, base_speed=22.0, t_offset=60.0, near_surface=True)

    analyzer = FeedingResponseAnalyzer()
    result   = analyzer.analyze(
        before_frames = before,
        during_frames = during,
        feeding_ts    = 60.0,
        sensor_data   = {"water_temp": 22.5, "ph": 7.2,
                         "do_mg_l": 6.8, "turbidity_ntu": 15.0},
    )

    print("=" * 55)
    for k, v in result.items():
        print(f"  {k:<35}: {v}")
    print("=" * 55)

    path = analyzer.save_to_csv("data/feeding_response_test.csv")
    print(f"\n  저장: {path}")
