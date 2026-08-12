from django.utils import timezone

from .models import StateCode, TankStateEvent


def detect_states(tank, reading):
    """
    현재 SensorReading 값을
    Tank의 설정 기준값과 비교해서
    발생해야 할 상태 코드를 반환
    """

    states = []

    # ─────────────────────
    # 수온 높음
    # ─────────────────────
    if reading.temperature > tank.temp_max:
        states.append({
            "code": "TMP-HIGH-001",
            "value": reading.temperature,
            "evidence": {
                "temperature": reading.temperature,
                "temp_max": tank.temp_max,
            },
        })

    # ─────────────────────
    # 수온 낮음
    # ─────────────────────
    if reading.temperature < tank.temp_min:
        states.append({
            "code": "TMP-LOW-001",
            "value": reading.temperature,
            "evidence": {
                "temperature": reading.temperature,
                "temp_min": tank.temp_min,
            },
        })

    # ─────────────────────
    # pH 범위 이탈
    # ─────────────────────
    if reading.ph < tank.ph_min or reading.ph > tank.ph_max:
        states.append({
            "code": "PH-OUT-001",
            "value": reading.ph,
            "evidence": {
                "ph": reading.ph,
                "ph_min": tank.ph_min,
                "ph_max": tank.ph_max,
            },
        })

    # ─────────────────────
    # 용존산소 부족
    # ─────────────────────
    if reading.dissolved_oxygen < tank.do_min:
        states.append({
            "code": "DO-LOW-001",
            "value": reading.dissolved_oxygen,
            "evidence": {
                "dissolved_oxygen":
                    reading.dissolved_oxygen,

                "do_min":
                    tank.do_min,
            },
        })

    # ─────────────────────
    # 탁도 높음
    # ─────────────────────
    if reading.turbidity > tank.turbidity_max:
        states.append({
            "code": "TUR-HIGH-001",
            "value": reading.turbidity,
            "evidence": {
                "turbidity":
                    reading.turbidity,

                "turbidity_max":
                    tank.turbidity_max,
            },
        })

    return states


def sync_state_events(tank, detected_states):
    """
    현재 상태 판정 결과와
    DB의 활성 상태를 동기화

    새 상태:
    → TankStateEvent 생성

    계속 유지되는 상태:
    → 중복 저장 안 함

    정상화된 상태:
    → resolved 처리
    """

    detected_by_code = {
        item["code"]: item
        for item in detected_states
    }

    detected_codes = set(
        detected_by_code.keys()
    )

    active_events = (
        TankStateEvent.objects
        .select_related("state_code")
        .filter(
            tank=tank,
            is_resolved=False
        )
    )

    active_by_code = {
        event.state_code.code: event
        for event in active_events
    }

    # 새 상태 발생
    for code, item in detected_by_code.items():

        # 이미 발생 중이면 중복 생성 안 함
        if code in active_by_code:
            continue

        state_code = (
            StateCode.objects
            .filter(code=code)
            .first()
        )

        # 백과사전에 코드가 없으면 건너뜀
        if state_code is None:
            continue

        TankStateEvent.objects.create(
            tank=tank,
            state_code=state_code,
            current_value=item.get("value"),
            evidence=item.get(
                "evidence",
                {}
            ),
        )

    # 정상화된 상태 해결 처리
    now = timezone.now()

    for code, event in active_by_code.items():

        if code not in detected_codes:

            event.is_resolved = True
            event.resolved_at = now

            event.save(
                update_fields=[
                    "is_resolved",
                    "resolved_at"
                ]
            )


def evaluate_and_sync_states(tank, reading):
    """
    SensorReading 저장 직후 호출하는 함수
    """

    detected_states = detect_states(
        tank,
        reading
    )

    sync_state_events(
        tank,
        detected_states
    )

    return detected_states
