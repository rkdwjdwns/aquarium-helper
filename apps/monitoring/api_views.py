"""
apps/monitoring/api_views.py

Raspberry Pi ↔ Render 서버 간 REST API
- Pi → 서버 : 센서/행동/급이/성장/패턴 데이터 전송
- 서버 → Pi : 장치 제어 명령 응답 (polling 방식)

인증: 헤더 X-API-KEY (Render 환경변수 PI_API_KEY)
수질 기준: 코멧 금붕어 치어 기준 (설계 문서 v2.0)
"""

import json
import os
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import (
    Tank, SensorReading, FishBehavior, DeviceControl, EventLog,
    FeedingEvent, FeedingResponse, GrowthRecord, ActivityPattern,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 수질 기준값 (코멧 금붕어 치어 — 설계 문서 v2.0)
# ──────────────────────────────────────────────

WATER_STANDARDS = {
    'temp_min':       21.0,
    'temp_max':       24.0,
    'temp_optimal':   22.0,
    'ph_min':         6.5,
    'ph_max':         8.0,
    'ph_optimal_lo':  7.4,
    'ph_optimal_hi':  7.5,
    'do_min':         5.0,
    'do_danger':      4.0,
    'turbidity_max':  50.0,
    'turbidity_ok':   20.0,
    'turbidity_warn': 100.0,
}


# ──────────────────────────────────────────────
# 인증 데코레이터
# ──────────────────────────────────────────────

def api_key_required(func):
    def wrapper(request, *args, **kwargs):
        server_key = os.getenv('PI_API_KEY', '')
        if not server_key:
            logger.warning("PI_API_KEY 환경변수가 설정되어 있지 않습니다.")
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
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}


def _get_tank(tank_id) -> tuple:
    if not tank_id:
        return None, _error("tank_id 필드가 필요합니다.")
    try:
        return Tank.objects.get(id=tank_id), None
    except Tank.DoesNotExist:
        return None, _error(f"tank_id={tank_id} 에 해당하는 어항이 없습니다.", status=404)


# ──────────────────────────────────────────────
# 수질 점수 계산 (금붕어 기준)
# ──────────────────────────────────────────────

def _calc_water_quality(temp, ph, do_val, turbidity) -> int:
    score = 100
    s = WATER_STANDARDS

    # 수온
    if temp < s['temp_min'] or temp > s['temp_max']:
        score -= 30
    else:
        score -= min(int(abs(temp - s['temp_optimal']) / 1.0) * 5, 15)

    # pH
    if ph < 6.0 or ph > 8.5:
        score -= 30
    elif ph < s['ph_min'] or ph > s['ph_max']:
        score -= 15
    elif not (s['ph_optimal_lo'] <= ph <= s['ph_optimal_hi']):
        score -= 5

    # DO
    if do_val < s['do_danger']:
        score -= 30
    elif do_val < s['do_min']:
        score -= 15

    # 탁도
    if turbidity > s['turbidity_warn']:
        score -= 30
    elif turbidity > s['turbidity_max']:
        score -= 15
    elif turbidity > 30:
        score -= 5

    return max(score, 0)


# ──────────────────────────────────────────────
# 장치 자동 제어 (금붕어 기준)
# ──────────────────────────────────────────────

def _auto_control(tank: Tank, reading: SensorReading) -> list:
    actions  = []
    s        = WATER_STANDARDS
    controls = {d.type: d for d in DeviceControl.objects.filter(tank=tank, is_auto=True)}

    def _set_device(device_type: str, turn_on: bool, reason: str):
        device = controls.get(device_type)
        if device and device.is_on != turn_on:
            device.is_on = turn_on
            device.save(update_fields=['is_on', 'last_action_at'])
            state = "ON" if turn_on else "OFF"
            actions.append(f"{device_type}:{state}")
            EventLog.objects.create(
                tank=tank, level='INFO',
                message=f"[자동제어] {device.get_type_display()} {state} — {reason}"
            )

    temp = reading.temperature
    do_v = reading.dissolved_oxygen
    turb = reading.turbidity
    ph   = reading.ph

    # 히터: 21°C 미만 ON / 22°C 초과 OFF
    if temp < s['temp_min']:
        _set_device('HEATER', True,  f"수온 {temp}°C → 최솟값 미달")
    elif temp > s['temp_optimal']:
        _set_device('HEATER', False, f"수온 {temp}°C → 최적값 도달")

    # 냉각팬: 24°C 초과 ON / 23°C 이하 OFF
    if temp > s['temp_max']:
        _set_device('COOLING', True,  f"수온 {temp}°C → 최댓값 초과")
    elif temp <= s['temp_max'] - 1:
        _set_device('COOLING', False, f"수온 {temp}°C → 정상 범위")

    # 여과기: 50 NTU 초과 ON / 20 NTU 이하 OFF
    if turb > s['turbidity_max']:
        _set_device('FILTER', True,  f"탁도 {turb} NTU → 기준 초과")
    elif turb <= s['turbidity_ok']:
        _set_device('FILTER', False, f"탁도 {turb} NTU → 정상")

    # 에어펌프: DO 4mg/L 이하 즉각 ON / 6mg/L 이상 OFF
    if do_v < s['do_danger']:
        _set_device('AIR_PUMP', True,  f"DO {do_v} mg/L → 위험")
    elif do_v >= 6.0:
        _set_device('AIR_PUMP', False, f"DO {do_v} mg/L → 정상")

    # 위험 이벤트 로그
    if ph < 6.0 or ph > 8.5:
        EventLog.objects.create(tank=tank, level='DANGER', message=f"pH 위험 수치: {ph}")
    if turb > s['turbidity_warn']:
        EventLog.objects.create(tank=tank, level='WARNING', message=f"탁도 스트레스: {turb} NTU — 환수 권장")

    return actions


# ──────────────────────────────────────────────
# [1] 센서 데이터  POST /monitoring/api/sensor/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_sensor_data(request):
    """
    요청 바디:
    {
        "tank_id": 1, "temperature": 22.5, "ph": 7.2,
        "dissolved_oxygen": 6.8, "turbidity": 12.3, "water_level": 90.0
    }
    """
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank, err = _get_tank(data.get('tank_id'))
    if err:
        return err

    missing = [f for f in ['temperature', 'ph'] if f not in data]
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

    score   = _calc_water_quality(temp, ph, do_val, turbidity)
    reading = SensorReading.objects.create(
        tank=tank, temperature=temp, ph=ph,
        dissolved_oxygen=do_val, turbidity=turbidity,
        water_level=w_level, water_quality_score=score,
    )
    actions = _auto_control(tank, reading)
    logger.info(f"[센서] tank={tank.id} temp={temp} ph={ph} do={do_val} score={score}")

    return _ok({
        'reading_id': reading.id, 'water_quality_score': score,
        'auto_actions': actions, 'timestamp': reading.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [2] AI 행동 분석  POST /monitoring/api/behavior/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_fish_behavior(request):
    """
    요청 바디:
    {
        "tank_id": 1, "fish_count": 3, "overlap_frames": 2,
        "activity_level": 14.5, "abr_score": 0.05,
        "dominant_zone": "MID", "zone_top_ratio": 0.1,
        "zone_mid_ratio": 0.6, "zone_bot_ratio": 0.3,
        "size_index": 7.8, "feeding_score": 82,
        "status": "GOOD", "is_anomaly": false, "note": ""
    }
    """
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank, err = _get_tank(data.get('tank_id'))
    if err:
        return err

    status = data.get('status', 'NORMAL').upper()
    if status not in ['EXCELLENT', 'GOOD', 'NORMAL', 'WARNING', 'POOR']:
        status = 'NORMAL'

    dominant_zone = data.get('dominant_zone', 'MID').upper()
    if dominant_zone not in ['TOP', 'MID', 'BOT']:
        dominant_zone = 'MID'

    is_anomaly = bool(data.get('is_anomaly', False))

    behavior = FishBehavior.objects.create(
        tank=tank,
        fish_count=int(data.get('fish_count', 0)),
        overlap_frames=int(data.get('overlap_frames', 0)),
        activity_level=float(data.get('activity_level', 0.0)),
        abr_score=float(data.get('abr_score', 0.0)),
        dominant_zone=dominant_zone,
        zone_top_ratio=float(data.get('zone_top_ratio', 0.0)),
        zone_mid_ratio=float(data.get('zone_mid_ratio', 0.0)),
        zone_bot_ratio=float(data.get('zone_bot_ratio', 0.0)),
        size_index=float(data.get('size_index', 0.0)),
        feeding_score=int(data.get('feeding_score', 0)),
        status=status, is_anomaly=is_anomaly,
        note=data.get('note', ''),
    )

    if is_anomaly:
        EventLog.objects.create(
            tank=tank, level='WARNING',
            message=f"[AI 이상 감지] {data.get('note', '상세 내용 없음')}"
        )
    if behavior.feeding_score < 30:
        EventLog.objects.create(
            tank=tank, level='WARNING',
            message=f"[FRS 저조] {behavior.feeding_score}점 — 어류 상태 확인 권장"
        )

    logger.info(f"[행동] tank={tank.id} status={status} anomaly={is_anomaly}")
    return _ok({
        'behavior_id': behavior.id, 'status': status,
        'is_anomaly': is_anomaly, 'timestamp': behavior.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [3] 급이 이벤트  POST /monitoring/api/feeding/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_feeding_event(request):
    """
    요청 바디:
    {
        "tank_id": 1, "trigger": "AUTO", "amount_g": 0.3,
        "growth_stage": "FRY", "turbidity_before": 10.2,
        "turbidity_after": 18.5, "is_overfeeding": false,
        "rt_seconds": 4.2, "ar_ratio": 1.8, "sf_ratio": 0.45,
        "frs_score": 78, "activity_before": 12.3,
        "activity_during": 22.1, "activity_after": 15.4
    }
    """
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank, err = _get_tank(data.get('tank_id'))
    if err:
        return err

    trigger      = data.get('trigger', 'AUTO').upper()
    growth_stage = data.get('growth_stage', 'FRY').upper()
    if trigger not in ['AUTO', 'MANUAL']:
        trigger = 'AUTO'
    if growth_stage not in ['FRY', 'YOUNG', 'ADULT']:
        growth_stage = 'FRY'

    turb_before    = float(data.get('turbidity_before', 0.0))
    turb_after     = float(data.get('turbidity_after', 0.0))
    delta_ntu      = round(turb_after - turb_before, 2)
    is_overfeeding = bool(data.get('is_overfeeding', False))

    feeding = FeedingEvent.objects.create(
        tank=tank, trigger=trigger,
        amount_g=float(data.get('amount_g', 0.0)),
        growth_stage=growth_stage,
        turbidity_before=turb_before, turbidity_after=turb_after,
        delta_ntu=delta_ntu, is_overfeeding=is_overfeeding,
    )

    frs_score = int(data.get('frs_score', 0))
    response  = FeedingResponse.objects.create(
        tank=tank, feeding_event=feeding,
        rt_seconds=float(data.get('rt_seconds', 0.0)),
        ar_ratio=float(data.get('ar_ratio', 0.0)),
        sf_ratio=float(data.get('sf_ratio', 0.0)),
        frs_score=frs_score,
        activity_before=float(data.get('activity_before', 0.0)),
        activity_during=float(data.get('activity_during', 0.0)),
        activity_after=float(data.get('activity_after', 0.0)),
    )

    if is_overfeeding:
        EventLog.objects.create(
            tank=tank, level='WARNING',
            message=f"[과급여] ΔNTU={delta_ntu} — 다음 급이량 조정 필요"
        )
    if frs_score < 40:
        EventLog.objects.create(
            tank=tank, level='WARNING',
            message=f"[FRS 저조] 급이 반응 {frs_score}점 — 건강 상태 확인"
        )

    logger.info(f"[급이] tank={tank.id} amount={feeding.amount_g}g frs={frs_score}")
    return _ok({
        'feeding_id': feeding.id, 'response_id': response.id,
        'frs_score': frs_score, 'delta_ntu': delta_ntu,
        'is_overfeeding': is_overfeeding,
        'timestamp': feeding.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [4] 성장 기록  POST /monitoring/api/growth/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_growth_record(request):
    """
    요청 바디:
    {
        "tank_id": 1, "fish_id": 1, "size_index": 7.8,
        "estimated_length": 2.1, "estimated_weight": 0.098,
        "growth_rate": 0.05, "growth_stage": "FRY",
        "recommended_feed_g": 0.01
    }
    """
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank, err = _get_tank(data.get('tank_id'))
    if err:
        return err

    if 'fish_id' not in data or 'size_index' not in data:
        return _error("필수 필드 누락: fish_id, size_index")

    growth_stage = data.get('growth_stage', 'FRY').upper()
    if growth_stage not in ['FRY', 'YOUNG', 'ADULT']:
        growth_stage = 'FRY'

    record = GrowthRecord.objects.create(
        tank=tank,
        fish_id=int(data['fish_id']),
        size_index=float(data['size_index']),
        estimated_length=float(data.get('estimated_length', 0.0)),
        estimated_weight=float(data.get('estimated_weight', 0.0)),
        growth_rate=float(data.get('growth_rate', 0.0)),
        growth_stage=growth_stage,
        recommended_feed_g=float(data.get('recommended_feed_g', 0.0)),
    )

    logger.info(f"[성장] tank={tank.id} fish={record.fish_id} length={record.estimated_length}cm")
    return _ok({
        'record_id': record.id, 'fish_id': record.fish_id,
        'estimated_length': record.estimated_length,
        'growth_stage': growth_stage,
        'recommended_feed_g': record.recommended_feed_g,
        'timestamp': record.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [5] 활동 패턴  POST /monitoring/api/pattern/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_activity_pattern(request):
    """
    요청 바디:
    {
        "tank_id": 1,
        "period_start": "2025-04-20T00:00:00",
        "period_end":   "2025-04-20T23:59:59",
        "hourly_activity": {"0": 3.2, ..., "23": 4.1},
        "baseline_mean": 12.5, "baseline_std": 3.2,
        "current_mean": 10.1, "deviation_ratio": -0.19,
        "daytime_activity": 15.2, "nighttime_activity": 4.3,
        "anomaly_hours": [2, 3, 14], "has_anomaly": true
    }
    """
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank, err = _get_tank(data.get('tank_id'))
    if err:
        return err

    missing = [f for f in ['period_start', 'period_end'] if f not in data]
    if missing:
        return _error(f"필수 필드 누락: {', '.join(missing)}")

    has_anomaly = bool(data.get('has_anomaly', False))

    pattern = ActivityPattern.objects.create(
        tank=tank,
        period_start=data['period_start'],
        period_end=data['period_end'],
        hourly_activity=data.get('hourly_activity', {}),
        baseline_mean=float(data.get('baseline_mean', 0.0)),
        baseline_std=float(data.get('baseline_std', 0.0)),
        current_mean=float(data.get('current_mean', 0.0)),
        deviation_ratio=float(data.get('deviation_ratio', 0.0)),
        daytime_activity=float(data.get('daytime_activity', 0.0)),
        nighttime_activity=float(data.get('nighttime_activity', 0.0)),
        anomaly_hours=data.get('anomaly_hours', []),
        has_anomaly=has_anomaly,
    )

    if has_anomaly:
        EventLog.objects.create(
            tank=tank, level='WARNING',
            message=f"[패턴 이상] 이상 시간대: {data.get('anomaly_hours', [])} — 편차 {data.get('deviation_ratio', 0):.0%}"
        )

    logger.info(f"[패턴] tank={tank.id} anomaly={has_anomaly}")
    return _ok({
        'pattern_id': pattern.id,
        'has_anomaly': has_anomaly,
        'timestamp': pattern.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [6] 제어 명령 polling  GET /monitoring/api/commands/<tank_id>/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['GET'])
def get_pending_commands(request, tank_id):
    tank, err = _get_tank(tank_id)
    if err:
        return err

    devices = list(DeviceControl.objects.filter(tank=tank).values('type', 'is_on', 'is_auto'))
    return _ok({'tank_id': tank.id, 'devices': devices, 'timestamp': timezone.now().isoformat()})


# ──────────────────────────────────────────────
# [7] 헬스체크  GET /monitoring/api/health/
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET'])
def health_check(request):
    return _ok({'message': 'server is running', 'time': timezone.now().isoformat()})