from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.monitoring.models import EventLog, SensorReading, FishBehavior


class Command(BaseCommand):
    help = (
        "지정한 기간보다 오래된 로그/센서/행동 데이터를 수동 삭제합니다. "
        "분석 데이터 보존을 위해 --weeks와 --confirm을 모두 명시해야 합니다."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--weeks',
            type=int,
            required=True,
            help='보관 기간(주 단위). 이보다 오래된 데이터가 삭제 대상입니다.',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='실제 삭제를 승인합니다. 없으면 삭제하지 않습니다.',
        )

    def handle(self, *args, **options):
        weeks = options['weeks']
        confirm = options['confirm']

        if weeks <= 0:
            raise CommandError('--weeks는 1 이상의 정수여야 합니다.')

        if not confirm:
            raise CommandError(
                '데이터 삭제가 취소되었습니다. 실제 삭제하려면 --confirm을 추가하세요.'
            )

        cutoff = timezone.now() - timedelta(weeks=weeks)

        # FishBehavior 삭제 시 연결된 FishActivityDetail도 FK CASCADE로 삭제됨.
        deleted_behavior, _ = FishBehavior.objects.filter(
            created_at__lt=cutoff
        ).delete()
        deleted_sensor, _ = SensorReading.objects.filter(
            created_at__lt=cutoff
        ).delete()
        deleted_log, _ = EventLog.objects.filter(
            created_at__lt=cutoff
        ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"[정리 완료] 기준일: {cutoff.strftime('%Y-%m-%d %H:%M')} 이전 데이터 삭제\n"
                f"  - FishBehavior(+개체별 상세 포함): {deleted_behavior}개\n"
                f"  - SensorReading: {deleted_sensor}개\n"
                f"  - EventLog: {deleted_log}개"
            )
        )
