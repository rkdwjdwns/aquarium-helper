from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.monitoring.models import (
    Tank,
    GrowthRecord,
    FishActivityDetail,
    FeedingEvent,
    FeedingResponse,
)

OUTPUT_FILENAMES = {
    "growth": "growth_analysis.csv",
    "activity": "activity_analysis.csv",
    "abr": "abr_analysis.csv",
    "feeding": "feeding_analysis.csv",
}
RECONSTRUCTED_FILENAME = "deceased_fish_growth_reconstructed.csv"


def _fmt_datetime(value):
    if not value:
        return ""
    try:
        value = timezone.localtime(value)
    except (ValueError, TypeError):
        pass
    return value.strftime("%Y-%m-%d %H:%M:%S%z")


def _elapsed_days(value, first_value):
    if not value or not first_value:
        return 0.0
    return round((value - first_value).total_seconds() / 86400.0, 3)


def _growth_stage(length_cm):
    if length_cm < 3.0:
        return "FRY"
    if length_cm < 7.0:
        return "YOUNG"
    return "ADULT"


def _to_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_reconstructed(path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


class Command(BaseCommand):
    help = "DB의 개체별 성장/행동/ABR/급이 데이터를 프론트용 분석 CSV로 자동 생성합니다."

    def add_arguments(self, parser):
        parser.add_argument("--tank-id", type=int, default=None)
        parser.add_argument("--output-dir", default="static/monitoring/data")
        parser.add_argument("--without-reconstructed", action="store_true")

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        if not output_dir.is_absolute():
            output_dir = Path(settings.BASE_DIR) / output_dir

        tank = self._get_tank(options["tank_id"])

        reconstructed_path = (
            Path(settings.BASE_DIR)
            / "static"
            / "monitoring"
            / "data"
            / RECONSTRUCTED_FILENAME
        )
        reconstructed_rows = []
        if not options["without_reconstructed"]:
            reconstructed_rows = _read_reconstructed(reconstructed_path)
            if not reconstructed_rows:
                self.stdout.write(
                    self.style.WARNING(
                        f"재구성 원천 CSV가 없거나 비어 있습니다: {reconstructed_path}"
                    )
                )

        datasets = {
            "growth": (
                [
                    "timestamp", "day_since_first", "fish_id",
                    "estimated_length_cm", "estimated_weight_g",
                    "growth_rate_cm_day", "growth_stage", "size_index",
                    "recommended_feed_g", "life_status", "data_source", "note",
                ],
                self._build_growth_rows(tank, reconstructed_rows),
            ),
            "activity": (
                [
                    "timestamp", "day_since_first", "fish_id",
                    "activity_level_px_s", "dominant_zone", "behavior_status",
                    "is_anomaly", "life_status", "data_source", "note",
                ],
                self._build_activity_rows(tank, reconstructed_rows),
            ),
            "abr": (
                [
                    "timestamp", "day_since_first", "fish_id", "abr_score",
                    "abr_pct", "dominant_zone", "behavior_status", "is_anomaly",
                    "life_status", "data_source", "note",
                ],
                self._build_abr_rows(tank, reconstructed_rows),
            ),
            "feeding": (
                [
                    "timestamp", "event_id", "meal_no", "status", "trigger",
                    "feed_amount_g", "growth_stage", "is_overfeeding",
                    "frs_score", "response_latency_sec", "activity_before_px_s",
                    "activity_during_px_s", "activity_after_px_s",
                    "activity_increase_pct", "activity_ratio",
                    "surface_approach_ratio", "data_source", "note",
                ],
                self._build_feeding_rows(tank),
            ),
        }

        for key, (fields, rows) in datasets.items():
            out_path = output_dir / OUTPUT_FILENAMES[key]
            _write_csv(out_path, fields, rows)
            try:
                display = out_path.relative_to(settings.BASE_DIR)
            except ValueError:
                display = out_path
            self.stdout.write(
                self.style.SUCCESS(f"[생성] {display} ({len(rows)}행)")
            )

        tank_text = f"Tank #{tank.id} ({tank.name})" if tank else "DB Tank 없음"
        self.stdout.write(
            self.style.SUCCESS(
                f"분석 CSV 생성 완료 | 대상={tank_text} | "
                f"폐사 개체 재구성={len(reconstructed_rows)}행"
            )
        )

    def _get_tank(self, tank_id):
        if tank_id is not None:
            try:
                return Tank.objects.get(id=tank_id)
            except Tank.DoesNotExist as exc:
                raise CommandError(
                    f"tank_id={tank_id} 에 해당하는 Tank가 없습니다."
                ) from exc

        tank = Tank.objects.order_by("id").first()
        if tank is None:
            self.stdout.write(
                self.style.WARNING(
                    "DB에 Tank가 없습니다. 재구성 원천 자료만 처리합니다."
                )
            )
        return tank

    def _build_growth_rows(self, tank, reconstructed_rows):
        rows = []
        records = (
            list(
                GrowthRecord.objects.filter(tank=tank)
                .order_by("fish_id", "created_at", "id")
            )
            if tank is not None
            else []
        )

        first_at = {}
        for record in records:
            first_at.setdefault(record.fish_id, record.created_at)
            rows.append({
                "timestamp": _fmt_datetime(record.created_at),
                "day_since_first": _elapsed_days(
                    record.created_at, first_at[record.fish_id]
                ),
                "fish_id": record.fish_id,
                "estimated_length_cm": record.estimated_length,
                "estimated_weight_g": record.estimated_weight,
                "growth_rate_cm_day": record.growth_rate,
                "growth_stage": record.growth_stage,
                "size_index": record.size_index,
                "recommended_feed_g": record.recommended_feed_g,
                "life_status": "TRACKED",
                "data_source": "measured",
                "note": "",
            })

        measured_ids = {r.fish_id for r in records}
        reconstructed_ids = set()

        for src in reconstructed_rows:
            fish_id = _to_int(src.get("fish_id"))
            length = _to_float(src.get("estimated_length_cm"))
            day = _to_float(src.get("day"), 1.0)
            if fish_id is None or length is None:
                continue
            reconstructed_ids.add(fish_id)
            rows.append({
                "timestamp": "",
                "day_since_first": round(max(day - 1.0, 0.0), 3),
                "fish_id": fish_id,
                "estimated_length_cm": length,
                "estimated_weight_g": src.get("estimated_weight_g", ""),
                "growth_rate_cm_day": src.get("growth_rate_cm_day", ""),
                "growth_stage": _growth_stage(length),
                "size_index": "",
                "recommended_feed_g": "",
                "life_status": src.get("status", ""),
                "data_source": src.get(
                    "data_source", "synthetic_reconstruction"
                ),
                "note": src.get("note", ""),
            })

        collisions = measured_ids & reconstructed_ids
        if collisions:
            self.stdout.write(
                self.style.WARNING(
                    "DB 실측 fish_id와 재구성 fish_id가 겹칩니다: "
                    + ", ".join(map(str, sorted(collisions)))
                    + ". data_source로 구분하세요."
                )
            )

        return sorted(
            rows,
            key=lambda r: (
                _to_int(r.get("fish_id"), 0),
                _to_float(r.get("day_since_first"), 0.0),
                r.get("timestamp", ""),
            ),
        )

    def _build_activity_rows(self, tank, reconstructed_rows):
        rows = []
        details = (
            list(
                FishActivityDetail.objects.filter(tank=tank)
                .select_related("behavior")
                .order_by("fish_id", "created_at", "id")
            )
            if tank is not None
            else []
        )
        first_at = {}

        for detail in details:
            first_at.setdefault(detail.fish_id, detail.created_at)
            behavior = detail.behavior
            rows.append({
                "timestamp": _fmt_datetime(detail.created_at),
                "day_since_first": _elapsed_days(
                    detail.created_at, first_at[detail.fish_id]
                ),
                "fish_id": detail.fish_id,
                "activity_level_px_s": detail.activity_level,
                "dominant_zone": detail.dominant_zone,
                "behavior_status": behavior.status,
                "is_anomaly": behavior.is_anomaly,
                "life_status": "TRACKED",
                "data_source": "measured",
                "note": behavior.note or "",
            })

        for src in reconstructed_rows:
            fish_id = _to_int(src.get("fish_id"))
            activity = _to_float(src.get("activity_level_px_s"))
            day = _to_float(src.get("day"), 1.0)
            if fish_id is None or activity is None:
                continue
            rows.append({
                "timestamp": "",
                "day_since_first": round(max(day - 1.0, 0.0), 3),
                "fish_id": fish_id,
                "activity_level_px_s": activity,
                "dominant_zone": src.get("dominant_zone", ""),
                "behavior_status": "",
                "is_anomaly": "",
                "life_status": src.get("status", ""),
                "data_source": src.get(
                    "data_source", "synthetic_reconstruction"
                ),
                "note": src.get("note", ""),
            })

        return sorted(
            rows,
            key=lambda r: (
                _to_int(r.get("fish_id"), 0),
                _to_float(r.get("day_since_first"), 0.0),
                r.get("timestamp", ""),
            ),
        )

    def _build_abr_rows(self, tank, reconstructed_rows):
        rows = []
        details = (
            list(
                FishActivityDetail.objects.filter(tank=tank)
                .select_related("behavior")
                .order_by("fish_id", "created_at", "id")
            )
            if tank is not None
            else []
        )
        first_at = {}

        for detail in details:
            first_at.setdefault(detail.fish_id, detail.created_at)
            behavior = detail.behavior
            rows.append({
                "timestamp": _fmt_datetime(detail.created_at),
                "day_since_first": _elapsed_days(
                    detail.created_at, first_at[detail.fish_id]
                ),
                "fish_id": detail.fish_id,
                "abr_score": detail.abr_score,
                "abr_pct": round(detail.abr_score * 100.0, 3),
                "dominant_zone": detail.dominant_zone,
                "behavior_status": behavior.status,
                "is_anomaly": behavior.is_anomaly,
                "life_status": "TRACKED",
                "data_source": "measured",
                "note": behavior.note or "",
            })

        for src in reconstructed_rows:
            fish_id = _to_int(src.get("fish_id"))
            abr_score = _to_float(src.get("abr_score"))
            day = _to_float(src.get("day"), 1.0)
            if fish_id is None or abr_score is None:
                continue
            rows.append({
                "timestamp": "",
                "day_since_first": round(max(day - 1.0, 0.0), 3),
                "fish_id": fish_id,
                "abr_score": abr_score,
                "abr_pct": round(abr_score * 100.0, 3),
                "dominant_zone": src.get("dominant_zone", ""),
                "behavior_status": "",
                "is_anomaly": "",
                "life_status": src.get("status", ""),
                "data_source": src.get(
                    "data_source", "synthetic_reconstruction"
                ),
                "note": src.get("note", ""),
            })

        return sorted(
            rows,
            key=lambda r: (
                _to_int(r.get("fish_id"), 0),
                _to_float(r.get("day_since_first"), 0.0),
                r.get("timestamp", ""),
            ),
        )

    def _build_feeding_rows(self, tank):
        if tank is None:
            return []

        events = list(
            FeedingEvent.objects.filter(tank=tank)
            .select_related("response")
            .order_by("created_at", "id")
        )
        meal_counts = defaultdict(int)
        rows = []

        for event in events:
            local_dt = timezone.localtime(event.created_at)
            date_key = local_dt.date().isoformat()
            meal_counts[date_key] += 1

            try:
                response = event.response
            except FeedingResponse.DoesNotExist:
                response = None

            if response is not None and response.activity_before > 0:
                activity_increase_pct = round(
                    (
                        (response.activity_during - response.activity_before)
                        / response.activity_before
                    ) * 100.0,
                    3,
                )
            else:
                activity_increase_pct = ""

            rows.append({
                "timestamp": _fmt_datetime(event.created_at),
                "event_id": event.id,
                "meal_no": meal_counts[date_key],
                "status": "OK" if response else "NO_RESPONSE_DATA",
                "trigger": event.trigger,
                "feed_amount_g": event.amount_g,
                "growth_stage": event.growth_stage,
                "is_overfeeding": event.is_overfeeding,
                "frs_score": response.frs_score if response else "",
                "response_latency_sec": response.rt_seconds if response else "",
                "activity_before_px_s": (
                    response.activity_before if response else ""
                ),
                "activity_during_px_s": (
                    response.activity_during if response else ""
                ),
                "activity_after_px_s": (
                    response.activity_after if response else ""
                ),
                "activity_increase_pct": activity_increase_pct,
                "activity_ratio": response.ar_ratio if response else "",
                "surface_approach_ratio": (
                    response.sf_ratio if response else ""
                ),
                "data_source": "measured",
                "note": "" if response else "급이 반응 데이터 없음",
            })

        return rows
