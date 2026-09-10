"""Behavior bridge using the calibrated project-v2 behavior rules.

The bridge keeps the legacy return fields required by pi_client/backend while also
exposing normalized activity, 5-minute ABR, and AI analysis quality for new code.
Tracker IDs are not interpreted as persistent fish identities.
"""
from __future__ import annotations

import statistics
import threading
import time
from typing import Optional

from scripts.analytics.behavior_v2 import BehaviorV2Analyzer


class BehaviorBridge:
    _EMPTY_RESULT = {
        "fish_count": 0,
        "overlap_frames": 0,
        "activity_level": 0.0,
        "activity_index": None,
        "activity_state": "UNKNOWN",
        "abr_score": 0.0,
        "abr_5min_pct": None,
        "dominant_zone": "MID",
        "zone_top_ratio": 0.0,
        "zone_mid_ratio": 1.0,
        "zone_bot_ratio": 0.0,
        "size_index": 0.0,
        "feeding_score": 0,
        "status": "NORMAL",
        "is_anomaly": False,
        "dashboard_ready": False,
        "analysis_quality": "POOR",
        "analysis_good_pct": 0.0,
        "analysis_usable_pct": 0.0,
        "note": "",
    }

    def __init__(
        self,
        window_sec: float = 600.0,
        activity_cfg: Optional[dict] = None,
        baseline_csv: str = "data/activity_baseline_v2.csv",
    ):
        self.window_sec = float(window_sec)
        self._lock = threading.Lock()
        self._latest = self._EMPTY_RESULT.copy()
        self._last_update = 0.0
        self._analyzer = BehaviorV2Analyzer(activity_cfg or {}, baseline_csv=baseline_csv)

    def update(
        self,
        metrics_rows: list[dict],
        abr_rate: float = 0.0,          # legacy argument, ignored by v2
        abr_per_fish: list[dict] | None = None,  # legacy argument, ignored
        frs_score: int = 0,
    ):
        if not metrics_rows:
            return
        result = self._build_result(metrics_rows, frs_score)
        with self._lock:
            self._latest = result
            self._last_update = time.time()

    def get_latest(self) -> dict:
        with self._lock:
            return self._latest.copy()

    def get_last_update_sec(self) -> float:
        return time.time() - self._last_update if self._last_update > 0 else 999.0

    def is_fresh(self, max_age_sec: float = 60.0) -> bool:
        return self.get_last_update_sec() <= max_age_sec

    def _build_result(self, rows: list[dict], frs_score: int) -> dict:
        # Keep only the configured recent window so long-running buffers do not
        # affect the current status.
        try:
            last_ts = max(float(r.get("timestamp", 0)) for r in rows)
            recent = [r for r in rows if last_ts - float(r.get("timestamp", 0)) <= self.window_sec]
        except Exception:
            recent = rows

        v2 = self._analyzer.summarize(recent, sensor_ready=True)
        zone = v2.get("zone_dist", {"TOP": 0.0, "MID": 100.0, "BOT": 0.0})
        dominant = max(zone, key=zone.get) if zone else "MID"

        # Legacy backend field. This is a current 5-second detection estimate,
        # not a long-term count based on tracker IDs.
        fish_count = int(round(float(v2.get("fish_count_estimate_dev", 0.0) or 0.0)))
        overlap_frames = sum(1 for r in recent[-500:] if float(r.get("overlap_count", 0) or 0) > 0)
        sizes = [float(r.get("size_index", 0) or 0) for r in recent[-500:] if float(r.get("size_index", 0) or 0) > 0]
        size_index = round(statistics.median(sizes), 3) if sizes else 0.0

        abr_pct = v2.get("abr_5min_pct")
        abr_fraction = float(abr_pct) / 100.0 if abr_pct is not None else 0.0
        warning_pct = float(v2.get("abr_warning_pct", 13.0))
        is_anomaly = bool(
            v2.get("dashboard_ready")
            and abr_pct is not None
            and float(abr_pct) > warning_pct
        )

        if v2.get("analysis_quality") == "POOR":
            status = "WARNING"
        elif is_anomaly:
            status = "WARNING"
        elif v2.get("activity_state") == "NORMAL":
            status = "GOOD"
        else:
            status = "NORMAL"

        note_parts = [
            f"Activity {v2.get('activity_state', 'UNKNOWN')}"
            + (f" ({v2.get('activity_index'):.0f})" if v2.get("activity_index") is not None else ""),
            f"AI quality {v2.get('analysis_quality', 'POOR')}"
            f" / usable {v2.get('analysis_usable_pct', 0):.0f}%",
        ]
        if abr_pct is not None:
            note_parts.append(f"ABR5m {float(abr_pct):.1f}%")

        return {
            "fish_count": fish_count,
            "overlap_frames": overlap_frames,
            "activity_level": float(v2.get("raw_activity", 0.0) or 0.0),
            "activity_index": v2.get("activity_index"),
            "activity_state": v2.get("activity_state", "UNKNOWN"),
            "abr_score": round(abr_fraction, 4),
            "abr_5min_pct": abr_pct,
            "dominant_zone": dominant,
            "zone_top_ratio": round(float(zone.get("TOP", 0.0)) / 100.0, 4),
            "zone_mid_ratio": round(float(zone.get("MID", 0.0)) / 100.0, 4),
            "zone_bot_ratio": round(float(zone.get("BOT", 0.0)) / 100.0, 4),
            "size_index": size_index,
            "feeding_score": int(frs_score or 0),
            "status": status,
            "is_anomaly": is_anomaly,
            "dashboard_ready": bool(v2.get("dashboard_ready")),
            "analysis_quality": v2.get("analysis_quality", "POOR"),
            "analysis_good_pct": float(v2.get("analysis_good_pct", 0.0) or 0.0),
            "analysis_usable_pct": float(v2.get("analysis_usable_pct", 0.0) or 0.0),
            "note": " | ".join(note_parts),
        }


_bridge_instance: Optional[BehaviorBridge] = None


def get_bridge(
    window_sec: float = 600.0,
    activity_cfg: Optional[dict] = None,
    baseline_csv: str = "data/activity_baseline_v2.csv",
) -> BehaviorBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = BehaviorBridge(
            window_sec=window_sec,
            activity_cfg=activity_cfg,
            baseline_csv=baseline_csv,
        )
    return _bridge_instance
