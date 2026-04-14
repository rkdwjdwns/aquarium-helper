"""
apps/monitoring/api_views.py

Raspberry Pi ↔ Render 서버 간 REST API
- Pi → 서버 : 센서 데이터 전송, AI 어류 행동 분석 결과 전송
- 서버 → Pi : 장치 제어 명령 응답 (polling 방식)

인증 방식: API Key (헤더 X-API-KEY)
  - Render 환경변수 PI_API_KEY 에 값을 설정
  - Pi 클라이언트에서 동일한 키를 헤더에 포함해서 요청
"""

import json
import os
import logging

from django.http      import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils     import timezone

from .models import Tank, SensorReading, FishBehavior, DeviceControl, EventLog

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 인증 데코레이터
# ──────────────────────────────────────────────

def api_key_required(func):
    """
    헤더 X-API-KEY 값을 환경변수 PI_API_KEY 와 비교해 인증.
    PI_API_KEY 가 설정되지 않은 경우 개발 편의를 위해 통과시킴(콘솔 경고 출력).
    """
    def wrapper(request, *args, **kwargs):
        server_key = os.getenv('PI_API_KEY', '')

        if not server_key:
            logger.warning("PI_API_KEY 환경변수가 설정되어 있지 않습니다. 인증을 건너뜁니다.")
            return func(request, *args, **kwargs)

        client_key = request.headers.get('X-API-KEY', '')
        if client_key != server_key:
            return _error("인증 실패: 유효하지 않은 API Key입니다.", status=401)

        return func(request, *args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────
# 공통 헬퍼
# ──────────────────────────────────────────────

def _ok(data: dict = None, **kwargs) -> JsonResponse:
    payload = {'status': 'ok'}
    if data:
        payload.update(data)
    return JsonResponse(payload, **kwargs)


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'status': 'error', 'message': message}, status=status)


def _parse_body(request) -> dict:
    """요청 바디를 JSON으로 파싱. 실패 시 빈 딕셔너리 반환."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}


def _calc_water_quality(temp, ph, do_val, turbidity) -> int:
    """
    수질 종합 점수 계산 (0~100).
    각 지표별 감점 방식으로 단순 산정.
    """
    score = 100

    # 수온: 목표 26°C 기준 ±2°C 마다 10점 감점
    score -= min(int(abs(temp - 26.0) / 2.0) * 10, 30)

    # pH: 6.5~7.5 정상 범위 이탈 시 감점
    if ph < 6.0 or ph > 8.0:
        score -= 30
    elif ph < 6.5 or ph > 7.5:
        score -= 10

    # DO: 5mg/L 미만 감점
    if do_val < 4.0:
        score -= 30
    elif do_val < 5.0:
        score -= 10

    # 탁도: 50 NTU 초과 감점
    if turbidity > 50:
        score -= 20
    elif turbidity > 30:
        score -= 10

    return max(score, 0)


def _auto_control(tank: Tank, reading: SensorReading) -> list[str]:
    """
    수질 데이터 기반 장치 자동 제어 + 이벤트 로그 기록.
    히스테리시스 로직 적용 (채터링 방지).
    반환: 제어된 장치명 목록
    """
    actions = []

    controls = {
        d.type: d
        for d in DeviceControl.objects.filter(tank=tank, is_auto=True)
    }

    def _set_device(device_type: str, turn_on: bool, reason: str):
        device = controls.get(device_type)
        if device and device.is_on != turn_on:
            device.is_on = turn_on
            device.save(update_fields=['is_on', 'last_action_at'])
            state = "ON" if turn_on else "OFF"
            actions.append(f"{device_type}:{state}")
            EventLog.objects.create(
                tank=tank,
                level='INFO',
                message=f"[자동제어] {device.get_type_display()} {state} — {reason}"
            )

    # 히터: 25.5°C 미만 ON / 26.5°C 초과 OFF
    if reading.temperature < 25.5:
        _set_device('HEATER', True,  f"수온 {reading.temperature}°C → 기준 미달")
    elif reading.temperature > 26.5:
        _set_device('HEATER', False, f"수온 {reading.temperature}°C → 정상 복귀")

    # 냉각팬: 28°C 초과 ON / 27°C 이하 OFF
    if reading.temperature > 28.0:
        _set_device('COOLING', True,  f"수온 {reading.temperature}°C → 과열")
    elif reading.temperature <= 27.0:
        _set_device('COOLING', False, f"수온 {reading.temperature}°C → 냉각 불필요")

    # 여과기: 50 NTU 초과 ON / 20 NTU 이하 OFF
    if reading.turbidity > 50.0:
        _set_device('FILTER', True,  f"탁도 {reading.turbidity} NTU → 기준 초과")
    elif reading.turbidity <= 20.0:
        _set_device('FILTER', False, f"탁도 {reading.turbidity} NTU → 정상")

    # 에어펌프: DO 4mg/L 이하 ON / 6mg/L 이상 OFF
    if reading.dissolved_oxygen < 4.0:
        _set_device('AIR_PUMP', True,  f"DO {reading.dissolved_oxygen} mg/L → 산소 부족")
    elif reading.dissolved_oxygen >= 6.0:
        _set_device('AIR_PUMP', False, f"DO {reading.dissolved_oxygen} mg/L → 정상")

    # 위험 이벤트 로그
    if reading.ph < 6.0 or reading.ph > 8.5:
        EventLog.objects.create(
            tank=tank,
            level='DANGER',
            message=f"pH 위험 수치 감지: {reading.ph}"
        )

    return actions


# ──────────────────────────────────────────────
# [1] 센서 데이터 수신  POST /monitoring/api/sensor/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_sensor_data(request):
    """
    ESP32 → Raspberry Pi → 서버로 전달되는 수질 센서 데이터 수신.

    요청 바디 예시:
    {
        "tank_id": 1,
        "temperature": 25.3,
        "ph": 7.1,
        "dissolved_oxygen": 6.2,
        "turbidity": 18.5,
        "water_level": 90.0
    }
    """
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank_id = data.get('tank_id')
    if not tank_id:
        return _error("tank_id 필드가 필요합니다.")

    try:
        tank = Tank.objects.get(id=tank_id)
    except Tank.DoesNotExist:
        return _error(f"tank_id={tank_id} 에 해당하는 어항이 없습니다.", status=404)

    # 필수 필드 검증
    required = ['temperature', 'ph']
    missing = [f for f in required if f not in data]
    if missing:
        return _error(f"필수 필드 누락: {', '.join(missing)}")

    try:
        temp      = float(data['temperature'])
        ph        = float(data['ph'])
        do_val    = float(data.get('dissolved_oxygen', 0.0))
        turbidity = float(data.get('turbidity', 0.0))
        w_level   = float(data.get('water_level', 100.0))
    except (TypeError, ValueError) as e:
        return _error(f"숫자 변환 오류: {e}")

    score = _calc_water_quality(temp, ph, do_val, turbidity)

    reading = SensorReading.objects.create(
        tank=tank,
        temperature=temp,
        ph=ph,
        dissolved_oxygen=do_val,
        turbidity=turbidity,
        water_level=w_level,
        water_quality_score=score,
    )

    # 자동 제어 실행
    actions = _auto_control(tank, reading)

    logger.info(f"[센서] tank={tank_id} temp={temp} ph={ph} do={do_val} score={score}")

    return _ok({
        'reading_id':          reading.id,
        'water_quality_score': score,
        'auto_actions':        actions,
        'timestamp':           reading.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [2] AI 어류 행동 분석 수신  POST /monitoring/api/behavior/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_fish_behavior(request):
    """
    Raspberry Pi의 YOLOv11 + ByteTrack 분석 결과 수신.

    요청 바디 예시:
    {
        "tank_id": 1,
        "fish_count": 4,
        "overlap_frames": 2,
        "activity_level": 14.5,
        "dominant_zone": "BOT",
        "zone_top_ratio": 0.1,
        "zone_mid_ratio": 0.3,
        "zone_bot_ratio": 0.6,
        "size_index": 7.8,
        "feeding_score": 82,
        "status": "GOOD",
        "is_anomaly": false,
        "note": ""
    }
    """
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank_id = data.get('tank_id')
    if not tank_id:
        return _error("tank_id 필드가 필요합니다.")

    try:
        tank = Tank.objects.get(id=tank_id)
    except Tank.DoesNotExist:
        return _error(f"tank_id={tank_id} 에 해당하는 어항이 없습니다.", status=404)

    # STATUS 유효성 검증
    valid_statuses = ['EXCELLENT', 'GOOD', 'NORMAL', 'WARNING', 'POOR']
    status = data.get('status', 'NORMAL').upper()
    if status not in valid_statuses:
        status = 'NORMAL'

    # ZONE 유효성 검증
    valid_zones = ['TOP', 'MID', 'BOT']
    dominant_zone = data.get('dominant_zone', 'MID').upper()
    if dominant_zone not in valid_zones:
        dominant_zone = 'MID'

    is_anomaly = bool(data.get('is_anomaly', False))

    behavior = FishBehavior.objects.create(
        tank=tank,
        fish_count=int(data.get('fish_count', 0)),
        overlap_frames=int(data.get('overlap_frames', 0)),
        activity_level=float(data.get('activity_level', 0.0)),
        dominant_zone=dominant_zone,
        zone_top_ratio=float(data.get('zone_top_ratio', 0.0)),
        zone_mid_ratio=float(data.get('zone_mid_ratio', 0.0)),
        zone_bot_ratio=float(data.get('zone_bot_ratio', 0.0)),
        size_index=float(data.get('size_index', 0.0)),
        feeding_score=int(data.get('feeding_score', 0)),
        status=status,
        is_anomaly=is_anomaly,
        note=data.get('note', ''),
    )

    # 이상 행동 감지 시 경고 로그 자동 생성
    if is_anomaly:
        EventLog.objects.create(
            tank=tank,
            level='WARNING',
            message=f"[AI 이상 감지] {data.get('note', '상세 내용 없음')}"
        )

    # 급이 점수가 낮으면 주의 로그
    if behavior.feeding_score < 30:
        EventLog.objects.create(
            tank=tank,
            level='WARNING',
            message=f"[급이 반응 저하] 급이 점수 {behavior.feeding_score}점 — 어류 상태 확인 권장"
        )

    logger.info(
        f"[행동] tank={tank_id} status={status} "
        f"anomaly={is_anomaly} activity={behavior.activity_level}"
    )

    return _ok({
        'behavior_id': behavior.id,
        'status':      status,
        'is_anomaly':  is_anomaly,
        'timestamp':   behavior.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [3] 제어 명령 polling  GET /monitoring/api/commands/<tank_id>/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['GET'])
def get_pending_commands(request, tank_id):
    """
    Raspberry Pi가 주기적으로 호출해 대시보드의 수동 제어 명령을 가져감.
    Pi는 응답을 받은 후 ESP32로 명령을 전달해 릴레이를 제어함.

    응답 예시:
    {
        "status": "ok",
        "tank_id": 1,
        "devices": [
            {"type": "HEATER",   "is_on": true,  "is_auto": true},
            {"type": "FILTER",   "is_on": true,  "is_auto": true},
            {"type": "AIR_PUMP", "is_on": false, "is_auto": true},
            {"type": "FEEDER",   "is_on": false, "is_auto": false},
            {"type": "COOLING",  "is_on": false, "is_auto": true},
            {"type": "LIGHT",    "is_on": true,  "is_auto": false}
        ],
        "timestamp": "2025-04-01T12:00:00+09:00"
    }
    """
    try:
        tank = Tank.objects.get(id=tank_id)
    except Tank.DoesNotExist:
        return _error(f"tank_id={tank_id} 에 해당하는 어항이 없습니다.", status=404)

    devices = DeviceControl.objects.filter(tank=tank).values(
        'type', 'is_on', 'is_auto'
    )

    return _ok({
        'tank_id':   tank.id,
        'devices':   list(devices),
        'timestamp': timezone.now().isoformat(),
    })


# ──────────────────────────────────────────────
# [4] 헬스체크  GET /monitoring/api/health/
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET'])
def health_check(request):
    """
    Pi가 서버 연결 상태를 확인하거나 Render 슬립 방지 ping 용도로 사용.
    인증 불필요.
    """
    return _ok({'message': 'server is running', 'time': timezone.now().isoformat()})