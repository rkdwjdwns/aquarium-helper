"""Runtime behavior normalization for the aquarium dashboard (project v2).

This module applies the rules calibrated from the latest stable camera/ROI session:
- 5-second behavior buckets
- hourly activity baseline normalization
- GOOD/FAIR/POOR detection quality
- P01-P99 hourly abnormal activity rule
- 5-minute ABR

It deliberately does not treat tracker IDs as long-term fish identities.
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:  # pragma: no cover - old Python fallback
    KST = None


def _f(value, default=0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _i(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _median(values: Iterable[float], default=0.0) -> float:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(statistics.median(vals)) if vals else float(default)


class BehaviorV2Analyzer:
    def __init__(self, cfg: Optional[dict] = None, baseline_csv: Optional[str] = None):
        cfg = cfg or {}
        self.bucket_sec = int(cfg.get("bucket_sec", 5))
        self.min_frames = int(cfg.get("min_frames_per_bin", 10))
        self.quality_expected_fish = int(cfg.get("quality_expected_fish_count", 2))
        self.index_clip_max = float(cfg.get("index_clip_max", 250.0))
        self.abr_window_sec = int(cfg.get("abr_window_sec", 300))
        self.abr_min_bins = int(cfg.get("abr_min_bins", 12))
        self.abr_warning_pct = float(cfg.get("abr_warning_pct", 13.0))
        self.quality_window_sec = int(cfg.get("quality_window_sec", 600))
        self.baseline_csv = Path(baseline_csv or cfg.get("baseline_csv", "data/activity_baseline_v2.csv"))
        self.baseline = self._load_baseline(self.baseline_csv)

    @staticmethod
    def _load_baseline(path: Path) -> dict[int, dict]:
        result: dict[int, dict] = {}
        if not path.exists():
            return result
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    hour = _i(row.get("hour"), -1)
                    if 0 <= hour <= 23:
                        result[hour] = {k: _f(v) if k != "hour" else hour for k, v in row.items()}
        except Exception:
            return {}
        return result

    def reload_baseline(self) -> bool:
        self.baseline = self._load_baseline(self.baseline_csv)
        return bool(self.baseline)

    @staticmethod
    def _local_hour(epoch: float) -> int:
        if KST is not None:
            return datetime.fromtimestamp(epoch, tz=KST).hour
        return datetime.fromtimestamp(epoch).hour

    def _quality(self, frame_counts: list[int]) -> tuple[str, float, float, float]:
        if not frame_counts:
            return "POOR", 0.0, 0.0, 0.0
        # Current operating baseline contains two fish. GOOD therefore requires
        # both expected fish to be detected in at least half of the frames while
        # suppressing frequent over-detections.
        min_detected = max(1, self.quality_expected_fish)
        n = len(frame_counts)
        pct_ge = sum(1 for c in frame_counts if c >= min_detected) / n
        pct_eq = sum(1 for c in frame_counts if c == self.quality_expected_fish) / n
        pct_gt = sum(1 for c in frame_counts if c > self.quality_expected_fish) / n
        if pct_ge >= 0.50 and pct_gt < 0.10:
            q = "GOOD"
        elif pct_ge >= 0.10 and pct_gt < 0.25:
            q = "FAIR"
        else:
            q = "POOR"
        return q, pct_ge, pct_eq, pct_gt

    def aggregate(self, rows: list[dict]) -> list[dict]:
        grouped: dict[int, list[dict]] = defaultdict(list)
        for row in rows:
            ts = _f(row.get("timestamp"), float("nan"))
            if not math.isfinite(ts):
                continue
            bin_epoch = int(ts // self.bucket_sec) * self.bucket_sec
            grouped[bin_epoch].append(row)

        out: list[dict] = []
        for bin_epoch in sorted(grouped):
            g = grouped[bin_epoch]
            activity = [_f(r.get("activity"), float("nan")) for r in g]
            activity = [v for v in activity if math.isfinite(v)]
            speeds = [_f(r.get("speed_px_s"), float("nan")) for r in g]
            speeds = [v for v in speeds if math.isfinite(v)]

            zones = [str(r.get("zone", "MID")).upper() for r in g]
            z_n = max(1, len(zones))

            per_frame: dict[int, int] = defaultdict(int)
            for r in g:
                per_frame[_i(r.get("frame_idx"), -1)] += 1
            per_frame.pop(-1, None)
            frame_counts = list(per_frame.values())
            quality, pct_ge, pct_eq, pct_gt = self._quality(frame_counts)
            frame_count = len(frame_counts)
            sample_valid = frame_count >= self.min_frames
            behavior_ready = sample_valid and quality in {"GOOD", "FAIR"}

            hour = self._local_hour(bin_epoch)
            base = self.baseline.get(hour, {})
            act = _median(activity)
            med = _f(base.get("activity_median"), 0.0)
            q25 = _f(base.get("activity_q25"), med)
            q75 = _f(base.get("activity_q75"), med)
            p01 = _f(base.get("activity_p01"), q25)
            p99 = _f(base.get("activity_p99"), q75)

            if med > 1e-9:
                activity_index = max(0.0, min(self.index_clip_max, 100.0 * act / med))
                if act < q25:
                    state = "LOW"
                elif act > q75:
                    state = "HIGH"
                else:
                    state = "NORMAL"
                abnormal = bool(act < p01 or act > p99)
            else:
                activity_index = 0.0
                state = "UNKNOWN"
                abnormal = False

            out.append({
                "timestamp": float(bin_epoch),
                "hour": hour,
                "detection_rows": len(g),
                "frame_count": frame_count,
                "fish_count_mean": round(statistics.mean(frame_counts), 3) if frame_counts else 0.0,
                "fish_count_median": round(_median(frame_counts), 3),
                "pct_frames_ge2": round(pct_ge, 4),
                "pct_frames_eq_expected": round(pct_eq, 4),
                "pct_frames_gt_expected": round(pct_gt, 4),
                "behavior_quality": quality,
                "behavior_sample_valid": sample_valid,
                "behavior_ready": behavior_ready,
                "activity_median": round(act, 3),
                "speed_px_s_median": round(_median(speeds), 3),
                "baseline_activity_median": round(med, 3),
                "activity_index": round(activity_index, 2),
                "activity_state": state if behavior_ready else "UNKNOWN",
                "abnormal_activity_flag": abnormal if behavior_ready else False,
                "top_ratio": round(zones.count("TOP") / z_n, 4),
                "mid_ratio": round(zones.count("MID") / z_n, 4),
                "bot_ratio": round(zones.count("BOT") / z_n, 4),
            })
        return out

    def summarize(self, rows: list[dict], sensor_ready: bool = True) -> dict:
        bins = self.aggregate(rows)
        if not bins:
            return {
                "dashboard_ready": False,
                "analysis_quality": "POOR",
                "activity_state": "UNKNOWN",
                "activity_index": 0.0,
                "abr_5min_pct": None,
                "zone_dist": {"TOP": 0.0, "MID": 0.0, "BOT": 0.0},
                "activity_series": [],
                "bins": [],
            }

        # The newest bucket may still be receiving frames when data_api polls.
        # Use the previous completed 5-second bucket for display/ABR to avoid
        # READY/WAIT flicker caused only by a partial current bucket.
        newest_ts = bins[-1]["timestamp"]
        complete_bins = [b for b in bins if b["timestamp"] <= newest_ts - self.bucket_sec]
        if not complete_bins:
            complete_bins = bins
        latest = complete_bins[-1]
        last_ts = latest["timestamp"]

        abr_bins = [b for b in complete_bins if last_ts - b["timestamp"] <= self.abr_window_sec and b["behavior_ready"]]
        if len(abr_bins) >= self.abr_min_bins:
            abr_pct = 100.0 * sum(1 for b in abr_bins if b["abnormal_activity_flag"]) / len(abr_bins)
            abr_pct = round(abr_pct, 2)
        else:
            abr_pct = None

        quality_bins = [b for b in complete_bins if last_ts - b["timestamp"] <= self.quality_window_sec]
        n_q = max(1, len(quality_bins))
        good_pct = 100.0 * sum(1 for b in quality_bins if b["behavior_quality"] == "GOOD") / n_q
        usable_pct = 100.0 * sum(1 for b in quality_bins if b["behavior_ready"]) / n_q
        if usable_pct >= 80.0 and good_pct >= 50.0:
            analysis_quality = "GOOD"
        elif usable_pct >= 50.0:
            analysis_quality = "FAIR"
        else:
            analysis_quality = "POOR"

        zone_bins = [b for b in complete_bins if last_ts - b["timestamp"] <= 60 and b["behavior_ready"]]
        if not zone_bins:
            zone_bins = [latest]
        zone_dist = {
            "TOP": round(100.0 * statistics.mean(b["top_ratio"] for b in zone_bins), 1),
            "MID": round(100.0 * statistics.mean(b["mid_ratio"] for b in zone_bins), 1),
            "BOT": round(100.0 * statistics.mean(b["bot_ratio"] for b in zone_bins), 1),
        }

        series = [
            {
                "t": int(b["timestamp"]),
                "v": b["activity_index"] if b["behavior_ready"] else None,
                "state": b["activity_state"],
                "quality": b["behavior_quality"],
            }
            for b in complete_bins[-60:]
        ]

        dashboard_ready = bool(sensor_ready and latest["behavior_ready"])
        return {
            "dashboard_ready": dashboard_ready,
            "analysis_quality": analysis_quality,
            "analysis_good_pct": round(good_pct, 1),
            "analysis_usable_pct": round(usable_pct, 1),
            "activity_state": latest["activity_state"] if dashboard_ready else "UNKNOWN",
            "activity_index": latest["activity_index"] if dashboard_ready else None,
            "raw_activity": latest["activity_median"],
            "baseline_activity_median": latest["baseline_activity_median"],
            "abr_5min_pct": abr_pct,
            "abr_warning_pct": self.abr_warning_pct,
            "abnormal_activity_flag": latest["abnormal_activity_flag"] if dashboard_ready else False,
            "zone_dist": zone_dist,
            "activity_series": series,
            "fish_count_estimate_dev": latest["fish_count_median"],
            "speed_px_s_median_dev": latest["speed_px_s_median"],
            "behavior_quality": latest["behavior_quality"],
            "frame_count_5s": latest["frame_count"],
            "abr_valid_bins": len(abr_bins),
            "bins": bins,
        }
