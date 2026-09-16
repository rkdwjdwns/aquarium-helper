from django.db import migrations


def seed_state_codes(apps, schema_editor):
    StateCode = apps.get_model('monitoring', 'StateCode')

    codes = [
        {
            "code": "TMP-HIGH-001",
            "category": "TEMP",
            "level": "WARNING",
            "title": "수온 높음",
            "description": "어항 수온이 설정된 최대 기준보다 높은 상태입니다.",
            "causes": [
                "실내 온도 상승",
                "직사광선",
                "냉각 장치 미작동",
            ],
            "effects": [
                "활동량 변화",
                "산소 요구량 증가",
                "스트레스 가능성",
            ],
            "actions": [
                "냉각 장치 상태 확인",
                "직사광선 차단",
                "수온 변화 확인",
            ],
            "prevention": [
                "주기적인 수온 확인",
                "냉각 장치 점검",
            ],
        },
        {
            "code": "TMP-LOW-001",
            "category": "TEMP",
            "level": "WARNING",
            "title": "수온 낮음",
            "description": "어항 수온이 설정된 최소 기준보다 낮은 상태입니다.",
            "causes": [
                "실내 온도 저하",
                "히터 미작동",
            ],
            "effects": [
                "활동량 감소",
                "먹이 반응 저하",
                "스트레스 가능성",
            ],
            "actions": [
                "히터 상태 확인",
                "수온을 천천히 정상 범위로 조절",
            ],
            "prevention": [
                "히터 점검",
                "급격한 온도 변화 방지",
            ],
        },
        {
            "code": "PH-OUT-001",
            "category": "PH",
            "level": "WARNING",
            "title": "pH 이상",
            "description": "pH가 설정된 정상 범위를 벗어난 상태입니다.",
            "causes": [
                "수질 변화",
                "노폐물 축적",
                "환수 부족",
            ],
            "effects": [
                "어류 스트레스 가능성",
                "수질 환경 악화 가능성",
            ],
            "actions": [
                "pH 재측정",
                "환수 여부 확인",
                "수질 상태 점검",
            ],
            "prevention": [
                "정기적인 환수",
                "pH 주기적 측정",
            ],
        },
        {
            "code": "DO-LOW-001",
            "category": "DO",
            "level": "DANGER",
            "title": "용존산소 부족",
            "description": "용존산소량이 설정된 최소 기준보다 낮은 상태입니다.",
            "causes": [
                "산소 공급 부족",
                "수온 상승",
                "과밀 사육",
            ],
            "effects": [
                "호흡 스트레스",
                "활동 이상 가능성",
            ],
            "actions": [
                "에어펌프 작동 확인",
                "수면 교반 확인",
                "수온 확인",
            ],
            "prevention": [
                "에어펌프 정기 점검",
                "과밀 사육 방지",
            ],
        },
        {
            "code": "TUR-HIGH-001",
            "category": "TURBIDITY",
            "level": "WARNING",
            "title": "탁도 높음",
            "description": "탁도가 설정된 최대 기준보다 높은 상태입니다.",
            "causes": [
                "먹이 잔여물",
                "배설물 축적",
                "여과 성능 저하",
            ],
            "effects": [
                "수질 악화 가능성",
                "어류 스트레스 가능성",
            ],
            "actions": [
                "여과기 상태 확인",
                "먹이 잔여물 확인",
                "필요 시 환수",
            ],
            "prevention": [
                "과급여 방지",
                "여과기 정기 관리",
                "정기적인 환수",
            ],
        },
    ]

    for data in codes:
        StateCode.objects.update_or_create(
            code=data["code"],
            defaults=data,
        )


def remove_state_codes(apps, schema_editor):
    StateCode = apps.get_model('monitoring', 'StateCode')

    codes = [
        "TMP-HIGH-001",
        "TMP-LOW-001",
        "PH-OUT-001",
        "DO-LOW-001",
        "TUR-HIGH-001",
    ]

    StateCode.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0015_statecode_tankstateevent'),
    ]

    operations = [
        migrations.RunPython(
            seed_state_codes,
            remove_state_codes,
        ),
    ]
