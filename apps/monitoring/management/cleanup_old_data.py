from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.monitoring.models import EventLog, SensorReading, FishBehavior


class Command(BaseCommand):
    help = "지정된 기간(기본 2주)보다 오래된 로그/센서/행동 데이터를 삭제합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            '--weeks', type=int, default=2,
            help='보관 기간(주 단위). 기본값 2주. 이보다 오래된 데이터는 삭제됩니다.'
        )

    def handle(self, *args, **options):
        weeks = options['weeks']
        cutoff = timezone.now() - timedelta(weeks=weeks)

        # ✅ FishBehavior 삭제 시 관련 FishActivityDetail은 FK CASCADE로 자동 삭제됨
        deleted_behavior, _ = FishBehavior.objects.filter(created_at__lt=cutoff).delete()
        deleted_sensor, _   = SensorReading.objects.filter(created_at__lt=cutoff).delete()
        deleted_log, _      = EventLog.objects.filter(created_at__lt=cutoff).delete()

        self.stdout.write(self.style.SUCCESS(
            f"[정리 완료] 기준일: {cutoff.strftime('%Y-%m-%d %H:%M')} 이전 데이터 삭제\n"
            f"  - FishBehavior(+개체별 상세 포함): {deleted_behavior}개\n"
            f"  - SensorReading: {deleted_sensor}개\n"
            f"  - EventLog: {deleted_log}개"
        ))
