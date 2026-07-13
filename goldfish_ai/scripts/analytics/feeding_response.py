"""
analytics/feeding_response.py — 급이 반응 점수(FRS) 계산 모듈
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    - 급이 이벤트 전후 행동 데이터를 슬라이싱
    - sub-score 3개 계산 → 가중합 → 0~100 정규화 → FRS 반환
    - 결과를 data/frs_history.csv에 누적 저장

FRS 구성:
    S1 (반응 시간)    : 급이 후 첫 수면(TOP zone) 접근까지 걸린 시간
                        빠를수록 높은 점수 (최대 during_sec 기준 역정규화)
    S2 (활동량 증가)  : post 평균 speed / pre 평균 speed 비율
                        증가율이 클수록 높은 점수
    S3 (수면 접근률)  : post 구간 중 TOP zone 프레임 비율
                        비율이 높을수록 높은 점수

    FRS = (w1×S1 + w2×S2 + w3×S3) × 100   (0~100 클리핑)

사용 예:
    from analytics.feeding_response import FeedingResponseAnalyzer
    analyzer = FeedingResponseAnalyzer(cfg["analytics"]["frs"], cfg["storage"])
    frs = analyzer.compute(feeding_ts=event.timestamp, frame_buffer=buf)
    print(f"FRS: {frs.score:.1f}점")
"""

from __future__ import annotations

import csv
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────
# 프레임 단위 행동 데이터 (파이프라인이 매 프레임 push)
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class FrameData:
    timestamp:  float        # Unix time
    fish_id:    int
    zone:       str          # "TOP" / "MID" / "BOT"
    speed_px_s: float
    activity:   float


# ─────────────────────────────────────────────────────────────────────────
# FRS 결과
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class FRSResult:
    feeding_ts:   float       # 급이 이벤트 timestamp
    datetime_str: str
    s1_response_time: float   # 반응 시간 sub-score (0~1)
    s2_activity_inc:  float   # 활동량 증가 sub-score (0~1)
    s3_surface_visit: float   # 수면 접근률 sub-score (0~1)
    score:        float       # 최종 FRS (0~100)
    pre_avg_speed:  float     # 참고값: pre 평균 속도
    post_avg_speed: float     # 참고값: post 평균 속도
    post_top_ratio: float     # 참고값: post TOP zone 비율
    first_surface_sec: Optional[float]  # 첫 수면 접근까지 걸린 시간(초)
    note: str = ""


# ─────────────────────────────────────────────────────────────────────────
# FRS 계산기
# ─────────────────────────────────────────────────────────────────────────
class FeedingResponseAnalyzer:
    """
    매 프레임 FrameData를 push() 로 받아 원형 버퍼에 보관.
    급이 이벤트 발생 후 post_window_sec 경과 시 compute()로 FRS 계산.

    버퍼 크기:
        (pre_window_sec + post_window_sec) × fps_ref 만큼 보관.
        오래된 데이터는 자동 삭제.
    """

    CSV_FIELDS = [
        "feeding_ts", "datetime_str",
        "s1_response_time", "s2_activity_inc", "s3_surface_visit",
        "score",
        "pre_avg_speed", "post_avg_speed", "post_top_ratio",
        "first_surface_sec", "note",
    ]

    def __init__(self, frs_cfg: dict, storage_cfg: dict):
        """
        Args:
            frs_cfg:     config.yaml analytics.frs 섹션
            storage_cfg: config.yaml storage 섹션
        """
        raw_w1 = float(frs_cfg.get("w1", 0.33))
        raw_w2 = float(frs_cfg.get("w2", 0.33))
        raw_w3 = float(frs_cfg.get("w3", 0.34))
        weight_sum = raw_w1 + raw_w2 + raw_w3
        if weight_sum <= 0:
            raw_w1, raw_w2, raw_w3, weight_sum = 0.33, 0.33, 0.34, 1.0
        # 설정 오타로 가중치 합이 1이 아니어도 최종 점수가 왜곡되지 않게 정규화한다.
        self.w1 = raw_w1 / weight_sum
        self.w2 = raw_w2 / weight_sum
        self.w3 = raw_w3 / weight_sum
        self.pre_sec = float(frs_cfg.get("before_sec", 60.0))
        self.post_sec = float(frs_cfg.get("during_sec", 180.0))
        self.fps_ref = float(frs_cfg.get("fps_ref", 14.0))
        self.expected_fish_count = max(1, int(frs_cfg.get("expected_fish_count", 2)))
        self.min_pre_coverage_ratio = min(1.0, max(0.0, float(
            frs_cfg.get("min_pre_coverage_ratio", 0.8)
        )))
        self.min_post_coverage_ratio = min(1.0, max(0.0, float(
            frs_cfg.get("min_post_coverage_ratio", 0.8)
        )))
        self.min_detected_fish_ratio = min(1.0, max(0.0, float(
            frs_cfg.get("min_detected_fish_ratio", 0.5)
        )))
        # 실제 Pi 처리 FPS가 fps_ref보다 낮아도 정상적인 연속 관측이면 계산할 수 있게 한다.
        # 단, 지나치게 희소한 데이터로 점수를 만드는 것은 막는다.
        self.min_frame_rate_ratio = min(1.0, max(0.05, float(
            frs_cfg.get("min_frame_rate_ratio", 0.35)
        )))
        self.last_skip_reason = ""

        output_dir = Path(storage_cfg.get("output_dir", "data"))
        self.csv_path = output_dir / "frs_history.csv"
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        # 원형 버퍼: 프레임당 여러 마리 데이터가 push되므로 expected_fish_count를 반영한다.
        maxlen = int((self.pre_sec + self.post_sec) * self.fps_ref * self.expected_fish_count * 1.5)
        self._buffer: deque[FrameData] = deque(maxlen=maxlen)
        self._computed_feeding_ts: set[float] = self._load_computed_keys()

    # ══════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════

    def push(self, frame_data: FrameData):
        """매 프레임 호출. 파이프라인 features dict → FrameData로 변환 후 전달."""
        self._buffer.append(frame_data)

    def push_from_features(
        self,
        timestamp: float,
        features: dict,
    ):
        """
        demo_pipeline.py의 features dict를 직접 받아 push.

        Args:
            timestamp: 현재 프레임 Unix time
            features:  {fish_id: {zone, speed_px_s, activity, ...}, ...}
        """
        for fid, feat in features.items():
            self._buffer.append(FrameData(
                timestamp  = timestamp,
                fish_id    = int(fid),
                zone       = feat.get("zone",       "MID"),
                speed_px_s = float(feat.get("speed_px_s", 0.0)),
                activity   = float(feat.get("activity",   0.0)),
            ))

    def compute(
        self,
        feeding_ts: float,
        note: str = "",
    ) -> Optional[FRSResult]:
        """
        급이 이벤트 timestamp 기준으로 FRS 계산.

        pre  구간: [feeding_ts - pre_sec,  feeding_ts)
        post 구간: [feeding_ts,            feeding_ts + post_sec]

        버퍼에 post 구간 데이터가 충분히 쌓이지 않은 경우 None 반환.

        Returns:
            FRSResult or None
        """
        self.last_skip_reason = ""
        key = round(feeding_ts, 4)
        if key in self._computed_feeding_ts:
            self.last_skip_reason = "already_computed"
            return None

        now = time.time()
        # post 구간이 아직 완료되지 않음
        if now < feeding_ts + self.post_sec:
            self.last_skip_reason = "post_window_incomplete"
            return None

        pre_frames  = self._slice(feeding_ts - self.pre_sec,  feeding_ts)
        post_frames = self._slice(feeding_ts,                  feeding_ts + self.post_sec)

        if not pre_frames or not post_frames:
            self.last_skip_reason = "pre_or_post_empty"
            return None

        if not self._coverage_ok(
            pre_frames, self.pre_sec, self.min_pre_coverage_ratio
        ):
            self.last_skip_reason = "pre_coverage_insufficient"
            return None
        if not self._coverage_ok(
            post_frames, self.post_sec, self.min_post_coverage_ratio
        ):
            self.last_skip_reason = "post_coverage_insufficient"
            return None

        # ── sub-score 계산 ─────────────────────────────────────────────

        # S1: 반응 시간 — 급이 후 첫 TOP zone 접근까지 걸린 시간 (역정규화)
        first_surface_sec = self._first_top_zone_sec(
            pre_frames, post_frames, feeding_ts
        )
        if first_surface_sec is None:
            s1 = 0.0   # post 구간 내 수면 접근 없음
        else:
            # 빠를수록 1에 가깝게 (post_sec 기준 선형 역정규화)
            s1 = max(0.0, 1.0 - first_surface_sec / self.post_sec)

        # S2: 활동량 증가율 — post/pre 평균 speed 비율
        pre_avg_speed  = self._avg_speed(pre_frames)
        post_avg_speed = self._avg_speed(post_frames)
        if pre_avg_speed < 1e-6:
            # pre 구간에 움직임 없으면 post 활동 자체를 점수화
            s2 = min(1.0, post_avg_speed / 200.0)
        else:
            ratio = post_avg_speed / pre_avg_speed
            # ratio 1.0(변화없음)→0점, 3.0(3배 증가)→1점으로 클리핑
            s2 = min(1.0, max(0.0, (ratio - 1.0) / 2.0))

        # S3: 수면 접근률 — post 구간 TOP zone 프레임 비율
        post_top_ratio = self._top_zone_ratio(post_frames)
        s3 = post_top_ratio   # 이미 0~1

        # ── 최종 FRS ──────────────────────────────────────────────────
        score = min(100.0, max(0.0, (self.w1 * s1 + self.w2 * s2 + self.w3 * s3) * 100))

        result = FRSResult(
            feeding_ts        = round(feeding_ts, 4),
            datetime_str      = datetime.fromtimestamp(feeding_ts).strftime("%Y-%m-%d %H:%M:%S"),
            s1_response_time  = round(s1,              4),
            s2_activity_inc   = round(s2,              4),
            s3_surface_visit  = round(s3,              4),
            score             = round(score,           2),
            pre_avg_speed     = round(pre_avg_speed,   2),
            post_avg_speed    = round(post_avg_speed,  2),
            post_top_ratio    = round(post_top_ratio,  4),
            first_surface_sec = round(first_surface_sec, 2) if first_surface_sec is not None else None,
            note              = note,
        )
        self._save_csv(result)
        self._computed_feeding_ts.add(key)
        print(f"[FRS] 계산 완료  score={score:.1f}  "
              f"S1={s1:.2f} S2={s2:.2f} S3={s3:.2f}  "
              f"({result.datetime_str})")
        return result

    def is_ready(self, feeding_ts: float) -> bool:
        """post 구간 데이터가 충분히 쌓였는지 확인."""
        return time.time() >= feeding_ts + self.post_sec

    def load_history(self) -> list[FRSResult]:
        """CSV 전체를 FRSResult 리스트로 반환 (AmountAdvisor용)."""
        if not self.csv_path.exists():
            return []
        results = []
        with open(self.csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    results.append(FRSResult(
                        feeding_ts        = float(row["feeding_ts"]),
                        datetime_str      = row["datetime_str"],
                        s1_response_time  = float(row["s1_response_time"]),
                        s2_activity_inc   = float(row["s2_activity_inc"]),
                        s3_surface_visit  = float(row["s3_surface_visit"]),
                        score             = float(row["score"]),
                        pre_avg_speed     = float(row["pre_avg_speed"]),
                        post_avg_speed    = float(row["post_avg_speed"]),
                        post_top_ratio    = float(row["post_top_ratio"]),
                        first_surface_sec = float(row["first_surface_sec"]) if row.get("first_surface_sec") else None,
                        note              = row.get("note", ""),
                    ))
                except (ValueError, KeyError, TypeError):
                    continue
        return results

    # ══════════════════════════════════════════════════════════════════════
    # Private
    # ══════════════════════════════════════════════════════════════════════

    def _slice(self, start_ts: float, end_ts: float) -> list[FrameData]:
        return [f for f in self._buffer if start_ts <= f.timestamp < end_ts]

    def _avg_speed(self, frames: list[FrameData]) -> float:
        # 정지(0px/s)도 급이 반응 분석에 의미가 있으므로 평균에서 제외하지 않는다.
        speeds = [max(0.0, f.speed_px_s) for f in frames]
        return sum(speeds) / len(speeds) if speeds else 0.0

    def _coverage_ok(
        self,
        frames: list[FrameData],
        window_sec: float,
        required_ratio: float,
    ) -> bool:
        if not frames:
            return False
        timestamps = sorted({round(frame.timestamp, 4) for frame in frames})
        if not timestamps:
            return False

        # 1) 분석 구간의 시간 범위가 실제로 채워졌는지 확인한다.
        observed_span = max(0.0, timestamps[-1] - timestamps[0])
        required_span = max(
            0.0,
            window_sec * required_ratio - 1.0 / max(self.fps_ref, 1.0),
        )
        if observed_span < required_span:
            return False

        # 2) fps_ref(목표 FPS)를 고정 행 수로 강제하면 실제 Pi가 9~12 FPS일 때
        #    충분한 데이터가 있어도 실패한다. 대신 최소 관측 FPS만 검사한다.
        minimum_unique_frames = max(
            2,
            int(
                window_sec
                * self.fps_ref
                * self.min_frame_rate_ratio
                * required_ratio
            ),
        )
        if len(timestamps) < minimum_unique_frames:
            return False

        # 3) 각 관측 프레임에 평균적으로 몇 마리가 포함됐는지 검사한다.
        average_detected_fish = len(frames) / len(timestamps)
        minimum_detected_fish = (
            self.expected_fish_count * self.min_detected_fish_ratio
        )
        return average_detected_fish >= minimum_detected_fish

    def _top_zone_ratio(self, frames: list[FrameData]) -> float:
        if not frames:
            return 0.0
        top_count = sum(1 for f in frames if f.zone == "TOP")
        return top_count / len(frames)

    def _first_top_zone_sec(
        self,
        pre_frames: list[FrameData],
        post_frames: list[FrameData],
        feeding_ts: float,
    ) -> Optional[float]:
        """급이 후 최초의 비TOP→TOP 진입까지 걸린 시간.

        급이 직전부터 이미 TOP에 있던 개체를 0초 반응으로 처리하면 FRS가
        과대평가될 수 있으므로, 개체별 직전 zone을 이어받아 TOP 진입 전이를 찾는다.
        pre 데이터가 없는 신규 ID는 첫 TOP 관측을 진입으로 허용한다.
        """
        previous_zone: dict[int, str] = {}
        for frame in sorted(pre_frames, key=lambda item: item.timestamp):
            previous_zone[frame.fish_id] = frame.zone

        for frame in sorted(post_frames, key=lambda item: item.timestamp):
            previous = previous_zone.get(frame.fish_id)
            if frame.zone == "TOP" and previous != "TOP":
                return max(0.0, frame.timestamp - feeding_ts)
            previous_zone[frame.fish_id] = frame.zone
        return None

    def _load_computed_keys(self) -> set[float]:
        """재시작 후에도 같은 feeding_ts가 중복 저장되지 않도록 기존 CSV 키를 로드."""
        if not self.csv_path.exists():
            return set()
        keys: set[float] = set()
        with open(self.csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    keys.add(round(float(row["feeding_ts"]), 4))
                except (ValueError, KeyError, TypeError):
                    pass
        return keys

    def _save_csv(self, result: FRSResult):
        write_header = not self.csv_path.exists()
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            if write_header:
                writer.writeheader()
            row = asdict(result)
            row["first_surface_sec"] = result.first_surface_sec if result.first_surface_sec is not None else ""
            writer.writerow(row)


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import random

    frs_cfg = {
        "w1": 0.33, "w2": 0.33, "w3": 0.34,
        "before_sec": 60.0, "during_sec": 180.0, "fps_ref": 14.0,
    }
    storage_cfg = {"output_dir": "data"}

    analyzer = FeedingResponseAnalyzer(frs_cfg, storage_cfg)
    now = time.time()

    # pre 구간 데이터 생성 (조용한 상태)
    for i in range(60 * 14):
        ts = now - 240 + i / 14.0
        analyzer.push(FrameData(ts, fish_id=1, zone="MID",
                                speed_px_s=random.uniform(10, 50), activity=30.0))

    # 급이 이벤트 시각
    feeding_ts = now - 180

    # post 구간 데이터 생성 (활성화 + 수면 접근)
    for i in range(180 * 14):
        ts = feeding_ts + i / 14.0
        zone = "TOP" if i > 20 * 14 else "MID"
        analyzer.push(FrameData(ts, fish_id=1, zone=zone,
                                speed_px_s=random.uniform(80, 300), activity=150.0))

    result = analyzer.compute(feeding_ts=feeding_ts, note="테스트")
    if result:
        print(f"\n최종 FRS: {result.score}점")
        print(f"  S1(반응시간): {result.s1_response_time}")
        print(f"  S2(활동증가): {result.s2_activity_inc}")
        print(f"  S3(수면접근): {result.s3_surface_visit}")
        print(f"  첫 수면 접근: {result.first_surface_sec}초")
