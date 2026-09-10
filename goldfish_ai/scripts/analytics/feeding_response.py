"""Operational feeding-response score (FRS v2).

FRS v2 was calibrated from real project logs and intentionally removes the old
TOP-zone component because the latest camera/ROI made that signal nearly
constant around feeding times.

Score = 70% activity response + 30% response latency.
It is an operational feeding-response indicator, not a health diagnosis and not
an automatic feeding-amount controller.
"""
from __future__ import annotations

import csv
import math
import statistics
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from scripts.analytics.behavior_v2 import BehaviorV2Analyzer


@dataclass
class FrameData:
    timestamp: float
    fish_id: int
    zone: str
    speed_px_s: float
    activity: float


@dataclass
class FRSResult:
    # Legacy-compatible fields first.
    feeding_ts: float
    datetime_str: str
    s1_response_time: float
    s2_activity_inc: float
    s3_surface_visit: float
    score: float
    pre_avg_speed: float
    post_avg_speed: float
    post_top_ratio: float
    first_surface_sec: Optional[float]
    note: str = ""
    # v2 fields.
    version: str = "v2"
    status: str = "OK"
    pre_samples: int = 0
    post_samples: int = 0
    pre_activity_index: float = 0.0
    post_peak60_activity_index: float = 0.0
    activity_increase_pct: float = 0.0
    response_threshold_index: float = 0.0
    response_latency_sec: float = 0.0
    activity_score: float = 0.0
    latency_score: float = 0.0
    zone_component_used: bool = False


class FeedingResponseAnalyzer:
    CSV_FIELDS = [
        "feeding_ts", "datetime_str", "version", "status",
        "score", "pre_samples", "post_samples",
        "pre_activity_index", "post_peak60_activity_index",
        "activity_increase_pct", "response_threshold_index",
        "response_latency_sec", "activity_score", "latency_score",
        "zone_component_used",
        # legacy transport/debug fields
        "s1_response_time", "s2_activity_inc", "s3_surface_visit",
        "pre_avg_speed", "post_avg_speed", "post_top_ratio",
        "first_surface_sec", "note",
    ]

    def __init__(self, frs_cfg: dict, storage_cfg: dict):
        self.version = str(frs_cfg.get("version", "v2"))
        self.pre_sec = float(frs_cfg.get("before_sec", 300.0))
        self.post_sec = float(frs_cfg.get("during_sec", 300.0))
        self.fps_ref = float(frs_cfg.get("fps_ref", 14.0))
        self.expected_fish_count = max(1, int(frs_cfg.get("quality_expected_fish_count", 2)))
        self.activity_weight = float(frs_cfg.get("activity_weight", 0.7))
        self.latency_weight = float(frs_cfg.get("latency_weight", 0.3))
        weight_sum = self.activity_weight + self.latency_weight
        if weight_sum <= 0:
            self.activity_weight, self.latency_weight, weight_sum = 0.7, 0.3, 1.0
        self.activity_weight /= weight_sum
        self.latency_weight /= weight_sum
        self.activity_full_response_pct = float(frs_cfg.get("activity_full_response_pct", 50.0))
        self.latency_max_sec = float(frs_cfg.get("latency_max_sec", self.post_sec))
        self.min_pre_bins = int(frs_cfg.get("min_pre_bins", 24))
        self.min_post_bins = int(frs_cfg.get("min_post_bins", 24))
        self.baseline_csv = str(frs_cfg.get("baseline_csv", "data/activity_baseline_v2.csv"))
        self.last_skip_reason = ""

        output_dir = Path(storage_cfg.get("output_dir", "data"))
        self.csv_path = output_dir / "frs_history.csv"
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        # Keep enough rows for the 5m pre + 5m post windows with multiple fish.
        maxlen = int((self.pre_sec + self.post_sec + 120.0) * self.fps_ref * self.expected_fish_count * 1.5)
        self._buffer: deque[FrameData] = deque(maxlen=maxlen)
        self._computed_feeding_ts = self._load_computed_keys()
        self._baseline = BehaviorV2Analyzer(
            {"quality_expected_fish_count": self.expected_fish_count},
            baseline_csv=self.baseline_csv,
        ).baseline

    def push(self, frame_data: FrameData):
        self._buffer.append(frame_data)

    def push_from_features(self, timestamp: float, features: dict):
        for fid, feat in features.items():
            self._buffer.append(FrameData(
                timestamp=float(timestamp),
                fish_id=int(fid),
                zone=str(feat.get("zone", "MID")),
                speed_px_s=float(feat.get("speed_px_s", 0.0)),
                activity=float(feat.get("activity", 0.0)),
            ))

    def is_ready(self, feeding_ts: float) -> bool:
        return time.time() >= feeding_ts + self.post_sec

    def compute(self, feeding_ts: float, note: str = "") -> Optional[FRSResult]:
        self.last_skip_reason = ""
        key = round(float(feeding_ts), 4)
        if key in self._computed_feeding_ts:
            self.last_skip_reason = "already_computed"
            return None
        if time.time() < feeding_ts + self.post_sec:
            self.last_skip_reason = "post_window_incomplete"
            return None

        pre_frames = self._slice(feeding_ts - self.pre_sec, feeding_ts)
        post_frames = self._slice(feeding_ts, feeding_ts + self.post_sec)
        pre_bins = self._activity_bins(pre_frames)
        post_bins = self._activity_bins(post_frames)
        pre_ready = [b for b in pre_bins if b["ready"]]
        post_ready = [b for b in post_bins if b["ready"]]

        if len(pre_ready) < self.min_pre_bins or len(post_ready) < self.min_post_bins:
            self.last_skip_reason = (
                f"insufficient_5s_bins(pre={len(pre_ready)},post={len(post_ready)})"
            )
            return None

        pre_idx = statistics.median(b["activity_index"] for b in pre_ready)
        rolling60 = self._rolling_median(post_ready, window_sec=60, min_bins=6)
        if not rolling60:
            self.last_skip_reason = "post_rolling60_insufficient"
            return None
        post_peak = max(v for _, v in rolling60)
        act_pct = ((post_peak / pre_idx) - 1.0) * 100.0 if pre_idx > 1e-9 else 0.0

        hour = BehaviorV2Analyzer._local_hour(feeding_ts)
        base = self._baseline.get(hour, {})
        med = float(base.get("activity_median", 0.0) or 0.0)
        q75 = float(base.get("activity_q75", med) or med)
        q75_index = 100.0 * q75 / med if med > 1e-9 else 115.0
        threshold = max(pre_idx * 1.15, q75_index)

        rolling30 = self._rolling_median(post_ready, window_sec=30, min_bins=3)
        latency = self.latency_max_sec
        for ts, value in rolling30:
            if value >= threshold:
                latency = max(0.0, min(self.latency_max_sec, ts - feeding_ts))
                break

        activity_score = self._clip100(
            act_pct / max(self.activity_full_response_pct, 1e-9) * 100.0
        )
        latency_score = self._clip100(
            (self.latency_max_sec - latency) / max(self.latency_max_sec, 1e-9) * 100.0
        )
        score = self._clip100(
            self.activity_weight * activity_score + self.latency_weight * latency_score
        )

        pre_avg_speed = self._avg_speed(pre_frames)
        post_avg_speed = self._avg_speed(post_frames)
        result = FRSResult(
            feeding_ts=round(feeding_ts, 4),
            datetime_str=datetime.fromtimestamp(feeding_ts).strftime("%Y-%m-%d %H:%M:%S"),
            # Legacy compatibility: these fields now carry the two v2 components.
            s1_response_time=round(latency_score / 100.0, 4),
            s2_activity_inc=round(activity_score / 100.0, 4),
            s3_surface_visit=0.0,
            score=round(score, 2),
            pre_avg_speed=round(pre_avg_speed, 2),
            post_avg_speed=round(post_avg_speed, 2),
            post_top_ratio=0.0,
            first_surface_sec=round(latency, 2),
            note=(note + " | FRS v2: activity 70% + latency 30%; zone excluded").strip(" |"),
            version="v2",
            status="OK",
            pre_samples=len(pre_ready),
            post_samples=len(post_ready),
            pre_activity_index=round(pre_idx, 3),
            post_peak60_activity_index=round(post_peak, 3),
            activity_increase_pct=round(act_pct, 3),
            response_threshold_index=round(threshold, 3),
            response_latency_sec=round(latency, 1),
            activity_score=round(activity_score, 2),
            latency_score=round(latency_score, 2),
            zone_component_used=False,
        )
        self._save_csv(result)
        self._computed_feeding_ts.add(key)
        print(
            f"[FRS v2] score={result.score:.1f} activity={result.activity_score:.1f} "
            f"latency={result.response_latency_sec:.0f}s ({result.datetime_str})"
        )
        return result

    def load_history(self) -> list[FRSResult]:
        if not self.csv_path.exists():
            return []
        out: list[FRSResult] = []
        with open(self.csv_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    out.append(self._row_to_result(row))
                except Exception:
                    continue
        return out

    def _row_to_result(self, row: dict) -> FRSResult:
        # New v2 history.
        if row.get("version") == "v2" or "activity_score" in row:
            return FRSResult(
                feeding_ts=float(row.get("feeding_ts", 0) or 0),
                datetime_str=row.get("datetime_str", ""),
                s1_response_time=float(row.get("s1_response_time", 0) or 0),
                s2_activity_inc=float(row.get("s2_activity_inc", 0) or 0),
                s3_surface_visit=float(row.get("s3_surface_visit", 0) or 0),
                score=float(row.get("score", 0) or 0),
                pre_avg_speed=float(row.get("pre_avg_speed", 0) or 0),
                post_avg_speed=float(row.get("post_avg_speed", 0) or 0),
                post_top_ratio=float(row.get("post_top_ratio", 0) or 0),
                first_surface_sec=self._optional_float(row.get("first_surface_sec")),
                note=row.get("note", ""),
                version=row.get("version", "v2"),
                status=row.get("status", "OK"),
                pre_samples=int(float(row.get("pre_samples", 0) or 0)),
                post_samples=int(float(row.get("post_samples", 0) or 0)),
                pre_activity_index=float(row.get("pre_activity_index", 0) or 0),
                post_peak60_activity_index=float(row.get("post_peak60_activity_index", 0) or 0),
                activity_increase_pct=float(row.get("activity_increase_pct", 0) or 0),
                response_threshold_index=float(row.get("response_threshold_index", 0) or 0),
                response_latency_sec=float(row.get("response_latency_sec", 0) or 0),
                activity_score=float(row.get("activity_score", 0) or 0),
                latency_score=float(row.get("latency_score", 0) or 0),
                zone_component_used=str(row.get("zone_component_used", "false")).lower() == "true",
            )
        # Old v1 history remains readable for AmountAdvisor/history screens.
        return FRSResult(
            feeding_ts=float(row.get("feeding_ts", 0) or 0),
            datetime_str=row.get("datetime_str", ""),
            s1_response_time=float(row.get("s1_response_time", 0) or 0),
            s2_activity_inc=float(row.get("s2_activity_inc", 0) or 0),
            s3_surface_visit=float(row.get("s3_surface_visit", 0) or 0),
            score=float(row.get("score", 0) or 0),
            pre_avg_speed=float(row.get("pre_avg_speed", 0) or 0),
            post_avg_speed=float(row.get("post_avg_speed", 0) or 0),
            post_top_ratio=float(row.get("post_top_ratio", 0) or 0),
            first_surface_sec=self._optional_float(row.get("first_surface_sec")),
            note=row.get("note", "legacy FRS"),
            version="v1",
        )

    def _activity_bins(self, frames: list[FrameData]) -> list[dict]:
        grouped: dict[int, list[FrameData]] = defaultdict(list)
        for f in frames:
            grouped[int(f.timestamp // 5) * 5].append(f)
        out = []
        for ts in sorted(grouped):
            g = grouped[ts]
            # Same timestamp is one video frame; it may contain multiple fish.
            counts: dict[float, int] = defaultdict(int)
            for f in g:
                counts[round(f.timestamp, 3)] += 1
            fc = list(counts.values())
            if not fc:
                continue
            min_detected = max(1, self.expected_fish_count - 1)
            pct_ge = sum(c >= min_detected for c in fc) / len(fc)
            pct_gt = sum(c > self.expected_fish_count for c in fc) / len(fc)
            good = pct_ge >= 0.50 and pct_gt < 0.10
            fair = pct_ge >= 0.10 and pct_gt < 0.25
            ready = len(fc) >= 10 and (good or fair)
            act = statistics.median(max(0.0, f.activity) for f in g)
            hour = BehaviorV2Analyzer._local_hour(ts)
            base = self._baseline.get(hour, {})
            med = float(base.get("activity_median", 0.0) or 0.0)
            idx = 100.0 * act / med if med > 1e-9 else 0.0
            out.append({"ts": float(ts), "activity": act, "activity_index": min(250.0, max(0.0, idx)), "ready": ready})
        return out

    @staticmethod
    def _rolling_median(bins: list[dict], window_sec: int, min_bins: int) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for i, b in enumerate(bins):
            values = [
                x["activity_index"] for x in bins[: i + 1]
                if 0 <= b["ts"] - x["ts"] < window_sec
            ]
            if len(values) >= min_bins:
                out.append((b["ts"], float(statistics.median(values))))
        return out

    def _slice(self, start_ts: float, end_ts: float) -> list[FrameData]:
        return [f for f in self._buffer if start_ts <= f.timestamp < end_ts]

    @staticmethod
    def _avg_speed(frames: list[FrameData]) -> float:
        return statistics.mean(max(0.0, f.speed_px_s) for f in frames) if frames else 0.0

    @staticmethod
    def _clip100(value: float) -> float:
        return min(100.0, max(0.0, float(value)))

    @staticmethod
    def _optional_float(value) -> Optional[float]:
        if value in (None, "", "None", "nan"):
            return None
        return float(value)

    def _load_computed_keys(self) -> set[float]:
        if not self.csv_path.exists():
            return set()
        keys: set[float] = set()
        try:
            with open(self.csv_path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    try:
                        keys.add(round(float(row.get("feeding_ts", 0)), 4))
                    except Exception:
                        pass
        except Exception:
            pass
        return keys

    def _save_csv(self, result: FRSResult):
        exists = self.csv_path.exists() and self.csv_path.stat().st_size > 0
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow(asdict(result))
