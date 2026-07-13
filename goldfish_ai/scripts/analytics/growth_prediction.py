"""
scripts/analytics/growth_prediction.py

Goldfish AI 성장 추정/예측 모듈.

설계 원칙
- 매 프레임 bbox의 장축 길이(bbox_long_side_px)를 관측한다.
- ByteTrack raw ID는 장기 고유 ID가 아니므로 위치 기반 안정 ID(Fish #1~#N)로 매핑한다.
- 단일 프레임 값을 바로 저장하지 않고, 일정 시간 동안 수집한 측정값의 중앙값을 기록한다.
- camera.px_to_cm_ratio로 px를 cm로 환산한다.
- 충분한 기간의 기록이 쌓이면 von Bertalanffy Growth Function(vBGF)을 적합한다.
- scipy가 없거나 적합이 실패하면 grid-search vBGF, 최종적으로 선형 추세를 fallback으로 사용한다.

vBGF
    L(t) = L_inf * (1 - exp(-k * (t - t0)))

주의
- px_to_cm_ratio가 0이면 체장 환산과 예측을 수행하지 않는다.
- 성장 예측은 최소 기록 수뿐 아니라 최소 관측 기간(min_span_days)도 충족해야 한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    from scipy.optimize import curve_fit  # type: ignore
except Exception:  # pragma: no cover
    curve_fit = None


@dataclass
class GrowthRecord:
    timestamp: float
    datetime_str: str
    fish_id: int
    day: float
    length_cm: float
    raw_size_px: float
    sample_count: int
    source: str = "pipeline"


@dataclass
class GrowthPredictionResult:
    fish_id: int
    model_status: str
    status: str
    estimated_stage: str
    record_count: int
    span_days: float
    current_length_cm: Optional[float]
    current_raw_size_px: Optional[float]
    daily_growth_cm: Optional[float]
    predicted_l_inf_cm: Optional[float]
    predicted_length_30d_cm: Optional[float]
    predicted_length_90d_cm: Optional[float]
    k: Optional[float]
    t0: Optional[float]
    r2: Optional[float]
    rmse_cm: Optional[float]
    ci95_cm: Optional[float]
    validation_mode: str
    validation_count: int
    linear_slope_cm_day: Optional[float]
    linear_r2: Optional[float]
    first_day: Optional[float]
    last_day: Optional[float]
    message: str


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_timestamp(value: Any) -> Optional[float]:
    numeric = _safe_float(value)
    if numeric is not None and numeric > 1_000_000_000:
        return numeric

    text = str(value or "").strip()
    if not text:
        return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d_%H%M%S",
    ):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _r2_score(actual: list[float], predicted: list[float]) -> Optional[float]:
    if len(actual) < 2 or len(actual) != len(predicted):
        return None
    mean_y = sum(actual) / len(actual)
    total = sum((value - mean_y) ** 2 for value in actual)
    residual = sum((value - pred) ** 2 for value, pred in zip(actual, predicted))
    if total <= 1e-12:
        return 1.0 if residual <= 1e-12 else 0.0
    return 1.0 - residual / total


def _rmse(actual: list[float], predicted: list[float]) -> Optional[float]:
    if not actual or len(actual) != len(predicted):
        return None
    return math.sqrt(
        sum((value - pred) ** 2 for value, pred in zip(actual, predicted))
        / len(actual)
    )


def _linear_fit(
    days: list[float], lengths: list[float]
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if len(days) < 2:
        return None, None, None

    mean_x = sum(days) / len(days)
    mean_y = sum(lengths) / len(lengths)
    denominator = sum((value - mean_x) ** 2 for value in days)
    if denominator <= 1e-12:
        return None, None, None

    slope = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(days, lengths)
    ) / denominator
    intercept = mean_y - slope * mean_x
    predicted = [slope * value + intercept for value in days]
    return slope, intercept, _r2_score(lengths, predicted)


def _vbgf(day: float, l_inf: float, k: float, t0: float) -> float:
    exponent = _clamp(-k * (day - t0), -60.0, 60.0)
    return l_inf * (1.0 - math.exp(exponent))


def _vbgf_values(
    days: list[float], l_inf: float, k: float, t0: float
) -> list[float]:
    return [_vbgf(day, l_inf, k, t0) for day in days]


def _quantile(values: list[float], q: float) -> float:
    """numpy 없이 선형 보간 분위수를 계산한다."""
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(float(value) for value in values)
    q = _clamp(float(q), 0.0, 1.0)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


class StableFishIdentityMapper:
    """ByteTrack raw ID를 Fish #1~#N 안정 표시 ID로 완화해서 매핑한다."""

    def __init__(
        self,
        max_fish: int,
        max_lost_sec: float = 10.0,
        max_match_distance_px: float = 120.0,
    ):
        self.max_fish = max(1, int(max_fish))
        self.max_lost_sec = max(0.1, float(max_lost_sec))
        self.max_match_distance_px = max(1.0, float(max_match_distance_px))
        self.raw_to_stable: dict[int, int] = {}
        self.slots: dict[int, dict[str, Any]] = {
            stable_id: {"center": None, "last_seen": -1.0, "raw_id": None}
            for stable_id in range(1, self.max_fish + 1)
        }

    @staticmethod
    def _center(feature: dict[str, Any]) -> Optional[tuple[float, float]]:
        x = _safe_float(feature.get("center_x"))
        y = _safe_float(feature.get("center_y"))
        return (x, y) if x is not None and y is not None else None

    @staticmethod
    def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def assign(
        self, features: dict[int, dict[str, Any]], timestamp: float
    ) -> dict[int, int]:
        assignments: dict[int, int] = {}
        used_slots: set[int] = set()

        # 기존 raw ID는 가장 우선해서 유지한다.
        for raw_id in features:
            raw_id = int(raw_id)
            stable_id = self.raw_to_stable.get(raw_id)
            if stable_id is not None and stable_id not in used_slots:
                assignments[raw_id] = stable_id
                used_slots.add(stable_id)

        # 새 raw ID와 최근 사라진 slot의 거리 조합을 만든 뒤 가까운 순서로 배정한다.
        candidates: list[tuple[float, int, int]] = []
        for raw_id, feature in features.items():
            raw_id = int(raw_id)
            if raw_id in assignments:
                continue
            center = self._center(feature)
            if center is None:
                continue
            for stable_id, slot in self.slots.items():
                if stable_id in used_slots or slot["center"] is None:
                    continue
                if timestamp - float(slot["last_seen"]) > self.max_lost_sec:
                    continue
                distance = self._distance(center, slot["center"])
                if distance <= self.max_match_distance_px:
                    candidates.append((distance, raw_id, stable_id))

        for _, raw_id, stable_id in sorted(candidates):
            if raw_id in assignments or stable_id in used_slots:
                continue
            assignments[raw_id] = stable_id
            used_slots.add(stable_id)

        # 남은 raw ID는 비어 있는 slot, 이후 가장 오래된 slot 순으로 배정한다.
        for raw_id in features:
            raw_id = int(raw_id)
            if raw_id in assignments:
                continue

            empty_slots = [
                stable_id
                for stable_id, slot in self.slots.items()
                if stable_id not in used_slots and slot["center"] is None
            ]
            if empty_slots:
                stable_id = min(empty_slots)
            else:
                available = [
                    (float(slot["last_seen"]), stable_id)
                    for stable_id, slot in self.slots.items()
                    if stable_id not in used_slots
                ]
                if not available:
                    continue
                stable_id = min(available)[1]

            assignments[raw_id] = stable_id
            used_slots.add(stable_id)

        # slot 및 역매핑 갱신
        for raw_id, stable_id in assignments.items():
            previous_raw = self.slots[stable_id].get("raw_id")
            if previous_raw is not None and int(previous_raw) != raw_id:
                self.raw_to_stable.pop(int(previous_raw), None)

            for old_raw, old_stable in list(self.raw_to_stable.items()):
                if old_stable == stable_id and old_raw != raw_id:
                    self.raw_to_stable.pop(old_raw, None)

            self.raw_to_stable[raw_id] = stable_id
            self.slots[stable_id] = {
                "center": self._center(features[raw_id]),
                "last_seen": timestamp,
                "raw_id": raw_id,
            }

        return assignments


class GrowthPredictionAnalyzer:
    def __init__(
        self,
        *,
        enabled: bool = True,
        expected_fish_count: int = 2,
        px_to_cm_ratio: float = 0.0,
        measurement_field: str = "bbox_long_side_px",
        allow_size_index_fallback: bool = False,
        frame_width_px: int = 416,
        frame_height_px: int = 234,
        min_records: int = 7,
        min_span_days: float = 7.0,
        fit_aggregation_days: float = 1.0,
        history_csv: str = "data/growth_records.csv",
        result_csv: str = "data/growth_prediction.csv",
        holdout_ratio: float = 0.2,
        confidence_interval_z: float = 1.96,
        min_l_inf_cm: float = 8.0,
        max_l_inf_cm: float = 40.0,
        default_l_inf_cm: float = 20.0,
        max_daily_growth_cm: float = 0.3,
        max_measurement_jump_cm: float = 1.0,
        aggregation_window_sec: int = 3600,
        min_samples_per_record: int = 30,
        aggregation_quantile: float = 0.75,
        max_overlap_iou: float = 0.15,
        fry_max_cm: float = 3.0,
        juvenile_max_cm: float = 7.0,
        stable_id_max_lost_sec: float = 10.0,
        stable_id_max_distance_px: float = 120.0,
        source_name: str = "pipeline",
    ):
        self.enabled = bool(enabled)
        self.expected_fish_count = max(1, int(expected_fish_count))
        self.px_to_cm_ratio = float(px_to_cm_ratio or 0.0)
        self.measurement_field = str(measurement_field)
        self.allow_size_index_fallback = bool(allow_size_index_fallback)
        self.frame_width_px = max(1, int(frame_width_px))
        self.frame_height_px = max(1, int(frame_height_px))
        self.min_records = max(3, int(min_records))
        self.min_span_days = max(0.0, float(min_span_days))
        # vBGF에는 시간별 상관 관측을 그대로 넣지 않고, 기본 1일 단위 대표값으로 집계한다.
        self.fit_aggregation_days = max(0.25, float(fit_aggregation_days))
        self.history_csv = Path(history_csv)
        self.result_csv = Path(result_csv)
        self.holdout_ratio = _clamp(float(holdout_ratio), 0.0, 0.5)
        self.confidence_interval_z = max(0.0, float(confidence_interval_z))
        self.min_l_inf_cm = float(min_l_inf_cm)
        self.max_l_inf_cm = float(max_l_inf_cm)
        self.default_l_inf_cm = float(default_l_inf_cm)
        self.max_daily_growth_cm = max(0.0, float(max_daily_growth_cm))
        self.max_measurement_jump_cm = max(0.0, float(max_measurement_jump_cm))
        self.aggregation_window_sec = max(1, int(aggregation_window_sec))
        self.min_samples_per_record = max(1, int(min_samples_per_record))
        # 정면/대각선 자세에서 bbox 장축이 짧아지는 편향을 줄이기 위해
        # 이상치 제거 후 상위 분위수(기본 75%)를 대표 체장 픽셀값으로 사용한다.
        self.aggregation_quantile = _clamp(float(aggregation_quantile), 0.5, 0.95)
        self.max_overlap_iou = _clamp(float(max_overlap_iou), 0.0, 1.0)
        self.fry_max_cm = max(0.0, float(fry_max_cm))
        self.juvenile_max_cm = max(self.fry_max_cm, float(juvenile_max_cm))
        self.source_name = source_name

        self.history_csv.parent.mkdir(parents=True, exist_ok=True)
        self.result_csv.parent.mkdir(parents=True, exist_ok=True)

        self.identity_mapper = StableFishIdentityMapper(
            self.expected_fish_count,
            max_lost_sec=stable_id_max_lost_sec,
            max_match_distance_px=stable_id_max_distance_px,
        )
        self._samples: dict[int, list[tuple[float, float]]] = {
            fish_id: [] for fish_id in range(1, self.expected_fish_count + 1)
        }
        self._window_start: dict[int, float] = {}
        self._calibration_warning_printed = False

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "GrowthPredictionAnalyzer":
        camera = config.get("camera", {}) if isinstance(config.get("camera"), dict) else {}
        pipeline = config.get("pipeline", {}) if isinstance(config.get("pipeline"), dict) else {}
        growth = (
            config.get("growth_prediction", {})
            if isinstance(config.get("growth_prediction"), dict)
            else {}
        )
        growth_stage = (
            config.get("growth_stage", {})
            if isinstance(config.get("growth_stage"), dict)
            else {}
        )
        fry_cfg = growth_stage.get("fry", {}) if isinstance(growth_stage.get("fry"), dict) else {}
        juvenile_cfg = growth_stage.get("juvenile", {}) if isinstance(growth_stage.get("juvenile"), dict) else {}

        # demo_pipeline의 평탄화 cfg도 허용한다.
        px_to_cm_ratio = camera.get(
            "px_to_cm_ratio", config.get("px_to_cm_ratio", 0.0)
        )
        expected_fish_count = growth.get(
            "expected_fish_count",
            pipeline.get(
                "expected_fish_count", config.get("expected_fish_count", 2)
            ),
        )

        frame_width = growth.get("frame_width_px", config.get("imgsz", 416))
        frame_height = growth.get("frame_height_px", config.get("frame_height_px", 234))

        return cls(
            enabled=growth.get("enabled", True),
            expected_fish_count=int(expected_fish_count),
            px_to_cm_ratio=float(px_to_cm_ratio or 0.0),
            measurement_field=growth.get("measurement_field", "bbox_long_side_px"),
            allow_size_index_fallback=growth.get("allow_size_index_fallback", False),
            frame_width_px=int(frame_width),
            frame_height_px=int(frame_height),
            min_records=int(growth.get("min_records", 7)),
            min_span_days=float(growth.get("min_span_days", 7.0)),
            fit_aggregation_days=float(growth.get("fit_aggregation_days", 1.0)),
            history_csv=str(growth.get("history_csv", "data/growth_records.csv")),
            result_csv=str(growth.get("result_csv", "data/growth_prediction.csv")),
            holdout_ratio=float(growth.get("holdout_ratio", 0.2)),
            confidence_interval_z=float(growth.get("confidence_interval_z", 1.96)),
            min_l_inf_cm=float(growth.get("min_l_inf_cm", 8.0)),
            max_l_inf_cm=float(growth.get("max_l_inf_cm", 40.0)),
            default_l_inf_cm=float(growth.get("default_l_inf_cm", 20.0)),
            max_daily_growth_cm=float(growth.get("max_daily_growth_cm", 0.3)),
            max_measurement_jump_cm=float(growth.get("max_measurement_jump_cm", 1.0)),
            aggregation_window_sec=int(growth.get("aggregation_window_sec", 3600)),
            min_samples_per_record=int(growth.get("min_samples_per_record", 30)),
            aggregation_quantile=float(growth.get("aggregation_quantile", 0.75)),
            max_overlap_iou=float(growth.get("max_overlap_iou", 0.15)),
            fry_max_cm=float(fry_cfg.get("length_max_cm", 3.0)),
            juvenile_max_cm=float(juvenile_cfg.get("length_max_cm", 7.0)),
            stable_id_max_lost_sec=float(growth.get("stable_id_max_lost_sec", 10.0)),
            stable_id_max_distance_px=float(
                growth.get("stable_id_max_distance_px", 120.0)
            ),
        )

    def estimate_raw_size_px(self, feature: dict[str, Any]) -> Optional[float]:
        ordered_fields = [
            self.measurement_field,
            "bbox_long_side_px",
            "bbox_width_px",
            "bbox_diagonal_px",
        ]
        for field in ordered_fields:
            value = _safe_float(feature.get(field))
            if value is not None and value > 0:
                return value

        if self.allow_size_index_fallback:
            size_index = _safe_float(feature.get("size_index"))
            if size_index is not None and size_index > 0:
                area_px = (
                    size_index / 100.0 * self.frame_width_px * self.frame_height_px
                )
                return math.sqrt(max(area_px, 0.0))

        return None

    def append_from_features(
        self,
        timestamp: float,
        features: dict[int, dict[str, Any]],
        *,
        display_id_map: Optional[dict[int, int]] = None,
        force: bool = False,
    ) -> list[GrowthRecord]:
        """매 프레임 호출한다. 실제 CSV 기록은 aggregation_window_sec마다 수행한다."""
        if not self.enabled or not features:
            return []

        if self.px_to_cm_ratio <= 0:
            if not self._calibration_warning_printed:
                print(
                    "[Growth] camera.px_to_cm_ratio=0 — 체장 기록/예측 대기 중"
                )
                self._calibration_warning_printed = True
            return []

        mapping = display_id_map or self.identity_mapper.assign(features, timestamp)
        saved: list[GrowthRecord] = []

        for raw_id, feature in features.items():
            raw_id = int(raw_id)
            stable_id = mapping.get(raw_id)
            if stable_id is None:
                continue

            overlap = _safe_float(feature.get("overlap_iou"), 0.0) or 0.0
            if overlap > self.max_overlap_iou:
                continue

            raw_size_px = self.estimate_raw_size_px(feature)
            if raw_size_px is None:
                continue

            self._samples[stable_id].append((timestamp, raw_size_px))
            self._window_start.setdefault(stable_id, timestamp)

            elapsed = timestamp - self._window_start[stable_id]
            if force or elapsed >= self.aggregation_window_sec:
                record = self._flush_one(stable_id, timestamp, force=force)
                if record is not None:
                    saved.append(record)

        return saved

    def flush_pending(self, timestamp: Optional[float] = None, force: bool = True) -> list[GrowthRecord]:
        now = float(timestamp or datetime.now().timestamp())
        saved: list[GrowthRecord] = []
        for fish_id in range(1, self.expected_fish_count + 1):
            record = self._flush_one(fish_id, now, force=force)
            if record is not None:
                saved.append(record)
        return saved

    def _flush_one(
        self, fish_id: int, timestamp: float, *, force: bool
    ) -> Optional[GrowthRecord]:
        samples = self._samples.get(fish_id, [])
        if not samples:
            return None
        if len(samples) < self.min_samples_per_record and not force:
            return None

        sizes = [value for _, value in samples]
        median_size = statistics.median(sizes)

        # MAD 기반으로 심한 bbox 튐을 제거한다.
        deviations = [abs(value - median_size) for value in sizes]
        mad = statistics.median(deviations) if deviations else 0.0
        filtered = sizes
        if mad > 0:
            filtered = [
                value for value in sizes if abs(value - median_size) <= 3.5 * mad
            ] or sizes

        # 물고기가 카메라를 향하면 bbox 장축이 실제 체장보다 짧아진다.
        # 중앙값만 쓰지 않고, 정면 자세 편향을 줄인 상위 분위수를 사용한다.
        representative_size = _quantile(filtered, self.aggregation_quantile)

        length_cm = representative_size * self.px_to_cm_ratio
        sample_count = len(samples)
        self._samples[fish_id] = []
        self._window_start[fish_id] = timestamp

        if self._is_outlier_length(fish_id, timestamp, length_cm):
            print(
                f"[Growth] Fish #{fish_id} 측정값 제외: {length_cm:.2f}cm (이상치)"
            )
            return None

        record = self._make_record(
            timestamp=timestamp,
            fish_id=fish_id,
            length_cm=length_cm,
            raw_size_px=representative_size,
            sample_count=sample_count,
            source=self.source_name,
        )
        self._append_record(record)
        print(
            f"[Growth] Fish #{fish_id} 기록: {record.length_cm:.2f}cm "
            f"({sample_count} samples)"
        )
        return record

    def append_from_fish_metrics_csv(
        self,
        input_csv: str,
        *,
        force: bool = True,
        max_rows: Optional[int] = None,
    ) -> list[GrowthRecord]:
        path = Path(input_csv)
        if not path.exists():
            raise FileNotFoundError(f"fish metrics csv not found: {input_csv}")

        rows: list[tuple[float, int, dict[str, Any]]] = []
        with open(path, newline="", encoding="utf-8") as file:
            for index, row in enumerate(csv.DictReader(file)):
                if max_rows is not None and index >= max_rows:
                    break
                timestamp = _parse_timestamp(row.get("timestamp"))
                raw_id = _safe_int(row.get("fish_id"))
                if timestamp is None or raw_id is None:
                    continue
                rows.append((timestamp, raw_id, dict(row)))

        rows.sort(key=lambda item: item[0])
        saved: list[GrowthRecord] = []
        grouped: dict[float, dict[int, dict[str, Any]]] = {}
        for timestamp, raw_id, feature in rows:
            grouped.setdefault(timestamp, {})[raw_id] = feature

        for timestamp in sorted(grouped):
            saved.extend(
                self.append_from_features(timestamp, grouped[timestamp], force=False)
            )

        if force and rows:
            saved.extend(self.flush_pending(timestamp=rows[-1][0], force=True))
        return saved

    def predict_all(self, *, save: bool = True) -> list[GrowthPredictionResult]:
        results = [
            self.predict_one(fish_id, self.load_history(fish_id))
            for fish_id in range(1, self.expected_fish_count + 1)
        ]
        if save:
            self.save_results(results)
        return results

    def predict_one(
        self, fish_id: int, records: list[GrowthRecord]
    ) -> GrowthPredictionResult:
        if not self.enabled:
            return self._empty_result(
                fish_id, "disabled", "disabled", len(records), "growth prediction disabled"
            )
        if self.px_to_cm_ratio <= 0:
            return self._empty_result(
                fish_id,
                "calibration_required",
                "calibration_required",
                len(records),
                "camera.px_to_cm_ratio is 0",
            )

        records = self._dedupe_and_sort(records)
        if not records:
            return self._empty_result(
                fish_id, "no_data", "collecting", 0, "no growth records"
            )

        # 시간별 기록은 서로 독립적인 성장 관측이 아니므로, 모델 입력은 기본 1일 단위로 집계한다.
        model_records = self._aggregate_records_for_fit(records)
        current_length = model_records[-1].length_cm
        span_days = max(0.0, model_records[-1].day - model_records[0].day)
        daily_growth = self._recent_daily_growth(model_records)
        stage = self._stage(current_length)

        if len(model_records) < self.min_records:
            return self._collecting_result(
                fish_id,
                model_records,
                current_length,
                daily_growth,
                stage,
                span_days,
                "not_enough_data",
                f"need at least {self.min_records} records",
            )
        if span_days < self.min_span_days:
            return self._collecting_result(
                fish_id,
                model_records,
                current_length,
                daily_growth,
                stage,
                span_days,
                "not_enough_span",
                f"need at least {self.min_span_days:.1f} observation days",
            )

        days = [record.day for record in model_records]
        lengths = [record.length_cm for record in model_records]
        train_days, train_lengths, eval_days, eval_lengths = self._split_train_eval(
            days, lengths
        )
        fit = self._fit_vbgf(train_days, train_lengths, current_length)
        linear_slope, _, linear_r2 = _linear_fit(days, lengths)

        if fit is None:
            return GrowthPredictionResult(
                fish_id=fish_id,
                model_status="linear_fallback",
                status=self._growth_status(daily_growth),
                estimated_stage=stage,
                record_count=len(model_records),
                span_days=round(span_days, 3),
                current_length_cm=round(current_length, 3),
                current_raw_size_px=round(model_records[-1].raw_size_px, 3),
                daily_growth_cm=self._round_optional(daily_growth, 5),
                predicted_l_inf_cm=None,
                predicted_length_30d_cm=None,
                predicted_length_90d_cm=None,
                k=None,
                t0=None,
                r2=None,
                rmse_cm=None,
                ci95_cm=None,
                validation_mode="none",
                validation_count=0,
                linear_slope_cm_day=self._round_optional(linear_slope, 5),
                linear_r2=self._round_optional(linear_r2, 4),
                first_day=round(model_records[0].day, 3),
                last_day=round(model_records[-1].day, 3),
                message="vBGF fitting failed; linear trend only",
            )

        l_inf, k, t0 = fit
        fit_predictions = _vbgf_values(days, l_inf, k, t0)
        fit_r2 = _r2_score(lengths, fit_predictions)
        fit_rmse = _rmse(lengths, fit_predictions)

        if len(eval_days) >= 2 and eval_days != days:
            validation_predictions = _vbgf_values(eval_days, l_inf, k, t0)
            r2 = _r2_score(eval_lengths, validation_predictions)
            rmse = _rmse(eval_lengths, validation_predictions)
            validation_mode = "holdout"
            validation_count = len(eval_days)
        else:
            r2 = fit_r2
            rmse = fit_rmse
            validation_mode = "in_sample"
            validation_count = len(days)

        last_day = model_records[-1].day
        predicted_30d = _vbgf(last_day + 30.0, l_inf, k, t0)
        predicted_90d = _vbgf(last_day + 90.0, l_inf, k, t0)
        ci95 = self.confidence_interval_z * rmse if rmse is not None else None

        return GrowthPredictionResult(
            fish_id=fish_id,
            model_status="fitted",
            status=self._growth_status(daily_growth),
            estimated_stage=stage,
            record_count=len(model_records),
            span_days=round(span_days, 3),
            current_length_cm=round(current_length, 3),
            current_raw_size_px=round(model_records[-1].raw_size_px, 3),
            daily_growth_cm=self._round_optional(daily_growth, 5),
            predicted_l_inf_cm=round(l_inf, 3),
            predicted_length_30d_cm=round(predicted_30d, 3),
            predicted_length_90d_cm=round(predicted_90d, 3),
            k=round(k, 6),
            t0=round(t0, 6),
            r2=self._round_optional(r2, 4),
            rmse_cm=self._round_optional(rmse, 4),
            ci95_cm=self._round_optional(ci95, 4),
            validation_mode=validation_mode,
            validation_count=validation_count,
            linear_slope_cm_day=self._round_optional(linear_slope, 5),
            linear_r2=self._round_optional(linear_r2, 4),
            first_day=round(model_records[0].day, 3),
            last_day=round(model_records[-1].day, 3),
            message="vBGF fitted successfully",
        )

    def load_history(self, fish_id: Optional[int] = None) -> list[GrowthRecord]:
        if not self.history_csv.exists():
            return []

        records: list[GrowthRecord] = []
        with open(self.history_csv, newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                row_fish_id = _safe_int(row.get("fish_id"))
                if row_fish_id is None:
                    continue
                if fish_id is not None and row_fish_id != fish_id:
                    continue

                timestamp = _safe_float(row.get("timestamp"))
                day = _safe_float(row.get("day"))
                length_cm = _safe_float(row.get("length_cm"))
                raw_size_px = _safe_float(row.get("raw_size_px"))
                if None in (timestamp, day, length_cm, raw_size_px):
                    continue

                records.append(
                    GrowthRecord(
                        timestamp=float(timestamp),
                        datetime_str=str(row.get("datetime_str") or ""),
                        fish_id=row_fish_id,
                        day=float(day),
                        length_cm=float(length_cm),
                        raw_size_px=float(raw_size_px),
                        sample_count=int(_safe_int(row.get("sample_count"), 1) or 1),
                        source=str(row.get("source") or "unknown"),
                    )
                )
        return self._dedupe_and_sort(records)

    def save_results(self, results: list[GrowthPredictionResult]) -> None:
        fields = list(GrowthPredictionResult.__dataclass_fields__.keys())
        with open(self.result_csv, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file, fieldnames=["timestamp", "datetime_str", *fields]
            )
            writer.writeheader()
            timestamp = datetime.now().timestamp()
            datetime_str = datetime.fromtimestamp(timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            for result in results:
                writer.writerow(
                    {
                        "timestamp": timestamp,
                        "datetime_str": datetime_str,
                        **asdict(result),
                    }
                )

    def _append_record(self, record: GrowthRecord) -> None:
        fields = list(GrowthRecord.__dataclass_fields__.keys())
        write_header = not self.history_csv.exists()
        with open(self.history_csv, "a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(asdict(record))

    def _make_record(
        self,
        *,
        timestamp: float,
        fish_id: int,
        length_cm: float,
        raw_size_px: float,
        sample_count: int,
        source: str,
    ) -> GrowthRecord:
        history = self.load_history(fish_id)
        start_timestamp = min(
            (record.timestamp for record in history), default=timestamp
        )
        day = (timestamp - start_timestamp) / 86400.0
        return GrowthRecord(
            timestamp=float(timestamp),
            datetime_str=datetime.fromtimestamp(timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            fish_id=int(fish_id),
            day=round(day, 6),
            length_cm=round(float(length_cm), 4),
            raw_size_px=round(float(raw_size_px), 4),
            sample_count=int(sample_count),
            source=source,
        )

    def _is_outlier_length(
        self, fish_id: int, timestamp: float, length_cm: float
    ) -> bool:
        history = self.load_history(fish_id)
        if not history:
            return False

        recent = history[-3:]
        baseline = statistics.median(record.length_cm for record in recent)
        absolute_jump = abs(length_cm - baseline)
        if absolute_jump > self.max_measurement_jump_cm:
            return True

        last = history[-1]
        interval_days = (timestamp - last.timestamp) / 86400.0
        if interval_days >= 1.0:
            daily_change = absolute_jump / interval_days
            if daily_change > self.max_daily_growth_cm:
                return True
        return False

    @staticmethod
    def _dedupe_and_sort(records: list[GrowthRecord]) -> list[GrowthRecord]:
        deduped: dict[tuple[int, float], GrowthRecord] = {}
        for record in sorted(records, key=lambda item: item.timestamp):
            deduped[(record.fish_id, round(record.timestamp, 3))] = record
        return sorted(deduped.values(), key=lambda item: item.timestamp)

    def _aggregate_records_for_fit(
        self, records: list[GrowthRecord]
    ) -> list[GrowthRecord]:
        """시간별 관측을 vBGF 피팅용 기간 대표값으로 집계한다.

        기본은 1일 단위이며 각 구간의 체장/픽셀값 중앙값을 사용한다.
        동일한 날의 반복 측정이 모델 적합도와 표본 수를 과대평가하는 것을 방지한다.
        """
        if not records:
            return []

        start_day = records[0].day
        buckets: dict[int, list[GrowthRecord]] = {}
        for record in records:
            bucket = int(math.floor((record.day - start_day) / self.fit_aggregation_days))
            buckets.setdefault(bucket, []).append(record)

        aggregated: list[GrowthRecord] = []
        for bucket in sorted(buckets):
            group = buckets[bucket]
            representative = max(group, key=lambda item: item.timestamp)
            aggregated.append(
                GrowthRecord(
                    timestamp=representative.timestamp,
                    datetime_str=representative.datetime_str,
                    fish_id=representative.fish_id,
                    day=statistics.median(item.day for item in group),
                    length_cm=statistics.median(item.length_cm for item in group),
                    raw_size_px=statistics.median(item.raw_size_px for item in group),
                    sample_count=sum(item.sample_count for item in group),
                    source=f"daily_aggregate:{len(group)}",
                )
            )
        return aggregated

    def _recent_daily_growth(self, records: list[GrowthRecord]) -> Optional[float]:
        if len(records) < 2:
            return None
        recent = records[-min(10, len(records)) :]
        days = [record.day for record in recent]
        lengths = [record.length_cm for record in recent]
        slope, _, _ = _linear_fit(days, lengths)
        return slope

    def _split_train_eval(
        self, days: list[float], lengths: list[float]
    ) -> tuple[list[float], list[float], list[float], list[float]]:
        if self.holdout_ratio <= 0 or len(days) < max(self.min_records, 6):
            return days, lengths, days, lengths

        holdout_count = max(2, int(round(len(days) * self.holdout_ratio)))
        if len(days) - holdout_count < 4:
            return days, lengths, days, lengths

        return (
            days[:-holdout_count],
            lengths[:-holdout_count],
            days[-holdout_count:],
            lengths[-holdout_count:],
        )

    def _fit_vbgf(
        self, days: list[float], lengths: list[float], current_length: float
    ) -> Optional[tuple[float, float, float]]:
        if len(days) < 4 or max(days) - min(days) <= 1e-9:
            return None

        max_length = max(lengths)
        l_inf_low = max(self.min_l_inf_cm, max_length * 1.01, current_length * 1.01)
        l_inf_high = self.max_l_inf_cm
        if l_inf_low >= l_inf_high:
            return None

        min_day = min(days)
        span = max(days) - min_day

        if curve_fit is not None and np is not None:
            try:
                x_values = np.array(days, dtype=float)
                y_values = np.array(lengths, dtype=float)

                def scipy_vbgf(t, l_inf, k, t0):
                    return l_inf * (1.0 - np.exp(-k * (t - t0)))

                initial_l_inf = _clamp(
                    max(self.default_l_inf_cm, max_length * 1.3),
                    l_inf_low + 1e-4,
                    l_inf_high - 1e-4,
                )
                initial_t0 = min_day - max(1.0, span)
                parameters, _ = curve_fit(
                    scipy_vbgf,
                    x_values,
                    y_values,
                    p0=[initial_l_inf, 0.02, initial_t0],
                    bounds=(
                        [l_inf_low, 0.0001, min_day - 3650.0],
                        [l_inf_high, 1.0, min_day - 1e-6],
                    ),
                    maxfev=30000,
                )
                l_inf, k, t0 = [float(value) for value in parameters]
                if self._valid_parameters(l_inf, k, t0):
                    return l_inf, k, t0
            except Exception:
                pass

        return self._fit_vbgf_grid(days, lengths, l_inf_low, l_inf_high)

    def _fit_vbgf_grid(
        self,
        days: list[float],
        lengths: list[float],
        l_inf_low: float,
        l_inf_high: float,
    ) -> Optional[tuple[float, float, float]]:
        best: Optional[tuple[float, float, float, float]] = None
        min_day = min(days)
        span = max(days) - min_day
        k_values = [
            0.0005,
            0.001,
            0.002,
            0.004,
            0.006,
            0.01,
            0.015,
            0.02,
            0.03,
            0.05,
            0.08,
            0.12,
        ]
        t0_values = [
            min_day - max(1.0, span * factor)
            for factor in (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
        ]

        for index in range(50):
            l_inf = l_inf_low + (l_inf_high - l_inf_low) * index / 49.0
            for k in k_values:
                for t0 in t0_values:
                    predicted = _vbgf_values(days, l_inf, k, t0)
                    if any(value <= 0 or value > l_inf for value in predicted):
                        continue
                    error = _rmse(lengths, predicted)
                    if error is not None and (best is None or error < best[0]):
                        best = (error, l_inf, k, t0)

        if best is None:
            return None
        return best[1], best[2], best[3]

    def _valid_parameters(self, l_inf: float, k: float, t0: float) -> bool:
        return (
            self.min_l_inf_cm <= l_inf <= self.max_l_inf_cm
            and 0.00001 <= k <= 2.0
            and math.isfinite(t0)
        )

    def _growth_status(self, daily_growth: Optional[float]) -> str:
        if daily_growth is None:
            return "collecting"
        if daily_growth < -0.02 or daily_growth > self.max_daily_growth_cm:
            return "measurement_warning"
        if daily_growth < 0.005:
            return "slow_growth"
        return "normal"

    def _stage(self, length_cm: float) -> str:
        if length_cm < self.fry_max_cm:
            return "fry"
        if length_cm < self.juvenile_max_cm:
            return "juvenile"
        return "adult"

    @staticmethod
    def _round_optional(value: Optional[float], digits: int) -> Optional[float]:
        return round(value, digits) if value is not None and math.isfinite(value) else None

    def _collecting_result(
        self,
        fish_id: int,
        records: list[GrowthRecord],
        current_length: float,
        daily_growth: Optional[float],
        stage: str,
        span_days: float,
        model_status: str,
        message: str,
    ) -> GrowthPredictionResult:
        return GrowthPredictionResult(
            fish_id=fish_id,
            model_status=model_status,
            status="collecting",
            estimated_stage=stage,
            record_count=len(records),
            span_days=round(span_days, 3),
            current_length_cm=round(current_length, 3),
            current_raw_size_px=round(records[-1].raw_size_px, 3),
            daily_growth_cm=self._round_optional(daily_growth, 5),
            predicted_l_inf_cm=None,
            predicted_length_30d_cm=None,
            predicted_length_90d_cm=None,
            k=None,
            t0=None,
            r2=None,
            rmse_cm=None,
            ci95_cm=None,
            validation_mode="none",
            validation_count=0,
            linear_slope_cm_day=None,
            linear_r2=None,
            first_day=round(model_records[0].day, 3),
            last_day=round(model_records[-1].day, 3),
            message=message,
        )

    def _empty_result(
        self,
        fish_id: int,
        model_status: str,
        status: str,
        record_count: int,
        message: str,
    ) -> GrowthPredictionResult:
        return GrowthPredictionResult(
            fish_id=fish_id,
            model_status=model_status,
            status=status,
            estimated_stage="unknown",
            record_count=record_count,
            span_days=0.0,
            current_length_cm=None,
            current_raw_size_px=None,
            daily_growth_cm=None,
            predicted_l_inf_cm=None,
            predicted_length_30d_cm=None,
            predicted_length_90d_cm=None,
            k=None,
            t0=None,
            r2=None,
            rmse_cm=None,
            ci95_cm=None,
            validation_mode="none",
            validation_count=0,
            linear_slope_cm_day=None,
            linear_r2=None,
            first_day=None,
            last_day=None,
            message=message,
        )


def load_yaml_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    if yaml is None:
        raise RuntimeError("PyYAML is required to load config.yaml")
    with open(config_path, encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def print_results(results: list[GrowthPredictionResult]) -> None:
    print("\nGrowth Prediction Results")
    print("-" * 116)
    print(
        f"{'Fish':<8} {'model_status':<20} {'n':>4} {'span':>7} "
        f"{'current':>9} {'L_inf':>9} {'30d':>9} {'R2':>8} {'RMSE':>8} {'daily':>9}"
    )
    print("-" * 116)
    for result in results:
        print(
            f"Fish #{result.fish_id:<2} {result.model_status:<20} "
            f"{result.record_count:>4} {result.span_days:>7.1f} "
            f"{str(result.current_length_cm):>9} "
            f"{str(result.predicted_l_inf_cm):>9} "
            f"{str(result.predicted_length_30d_cm):>9} "
            f"{str(result.r2):>8} {str(result.rmse_cm):>8} "
            f"{str(result.daily_growth_cm):>9}"
        )
    print("-" * 116)


def main() -> None:
    parser = argparse.ArgumentParser(description="Goldfish growth prediction analyzer")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--input", default=None, help="fish_metrics CSV")
    parser.add_argument("--fish-count", type=int, default=None)
    parser.add_argument("--px-to-cm-ratio", type=float, default=None)
    parser.add_argument("--force-import", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_yaml_config(args.config)
    if args.fish_count is not None:
        config.setdefault("pipeline", {})["expected_fish_count"] = args.fish_count
        config.setdefault("growth_prediction", {})[
            "expected_fish_count"
        ] = args.fish_count
    if args.px_to_cm_ratio is not None:
        config.setdefault("camera", {})["px_to_cm_ratio"] = args.px_to_cm_ratio

    analyzer = GrowthPredictionAnalyzer.from_config(config)
    if args.input:
        records = analyzer.append_from_fish_metrics_csv(
            args.input, force=args.force_import
        )
        print(f"[Growth] imported records: {len(records)}")

    results = analyzer.predict_all(save=True)
    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        print_results(results)
        print(f"[Growth] history: {analyzer.history_csv}")
        print(f"[Growth] result : {analyzer.result_csv}")


if __name__ == "__main__":
    main()
