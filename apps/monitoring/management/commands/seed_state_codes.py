from django.core.management.base import BaseCommand
from apps.monitoring.models import StateCode


SEED_DATA = [
    dict(code='TMP-HIGH-001', category='TEMP', level='WARNING', title='수온 과다',
         description='수온이 설정 상한을 초과했습니다.',
         causes=['히터/냉각팬 오작동', '실내 온도 급변', '직사광선 노출'],
         effects=['어류 스트레스 증가', '용존산소 감소'],
         actions=['냉각팬 수동 작동', '수온 확인 후 부분 환수'],
         prevention=['냉각 임계값 재점검', '어항 위치 조정']),
    dict(code='TMP-LOW-001', category='TEMP', level='WARNING', title='수온 부족',
         description='수온이 설정 하한 미만입니다.',
         causes=['히터 고장', '정전', '실내 온도 저하'],
         effects=['어류 면역력 저하', '활동성 감소'],
         actions=['히터 상태 확인', '수온 임계값 재확인'],
         prevention=['히터 예비기 준비']),
    dict(code='DO-LOW-001', category='DO', level='DANGER', title='용존산소 부족',
         description='용존산소량이 위험 수준까지 떨어졌습니다.',
         causes=['에어펌프 고장', '과밀 사육', '유기물 과다'],
         effects=['어류 호흡곤란', '폐사 위험'],
         actions=['에어펌프 즉시 가동', '부분 환수'],
         prevention=['정기적인 여과기 청소', '급이량 조절']),
    dict(code='PH-OUT-001', category='PH', level='WARNING', title='pH 범위 이탈',
         description='pH가 권장 범위를 벗어났습니다.',
         causes=['환수 미흡', '여과재 노후화'],
         effects=['어류 스트레스', '점액질 손상'],
         actions=['pH 재측정 후 완충제 사용 검토'],
         prevention=['정기 환수 주기 준수']),
    dict(code='TURB-HIGH-001', category='TURBIDITY', level='WARNING', title='탁도 과다',
         description='탁도가 설정 상한을 초과했습니다.',
         causes=['과급여', '여과기 막힘'],
         effects=['수질 악화', '질병 위험 증가'],
         actions=['여과기 점검', '부분 환수'],
         prevention=['급이량 조절', '여과기 정기 청소']),
]


class Command(BaseCommand):
    help = "StateCode 초기 데이터를 등록합니다 (이미 있으면 갱신)."

    def handle(self, *args, **options):
        for data in SEED_DATA:
            obj, created = StateCode.objects.update_or_create(
                code=data['code'], defaults=data
            )
            action = "생성" if created else "갱신"
            self.stdout.write(self.style.SUCCESS(f"[{action}] {obj.code} - {obj.title}"))