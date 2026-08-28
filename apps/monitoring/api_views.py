"""
apps/monitoring/api_views.py

Raspberry Pi ↔ Render 서버 간 REST API
- Pi → 서버 : 센서/행동/급이/성장/패턴 데이터 전송
- 서버 → Pi : 장치 제어 명령 응답 (polling 방식)
- Pi → 서버 : IP 자동 등록 (카메라 스트림 자동 연결)
- 프론트 → 서버 : 행동/FRS/ABR/패턴/성장 최신 데이터 조회 (GET)

인증: 헤더 X-API-KEY (Render 환경변수 PI_API_KEY)
수질 기준: 코멧 금붕어 치어 기준 (설계 문서 v2.0)
"""

import json
import os
import logging
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import (
    Tank, SensorReading, FishBehavior, FishActivityDetail, DeviceControl, EventLog,
    FeedingEvent, FeedingResponse, GrowthRecord, ActivityPattern,
    StateCode, TankStateEvent,
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

STATUS_KO = {
    'EXCELLENT': '매우 좋음',
    'GOOD':      '좋음',
    'NORMAL':    '정상',
    'WARNING':   '주의',
    'POOR':      '나쁨',
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


def _check_api_key(request) -> bool:
    """POST 뷰 내부에서 직접 API Key 체크 시 사용."""
    server_key = os.getenv('PI_API_KEY', '')
    if not server_key:
        return True
    return request.headers.get('X-API-KEY', '') == server_key


# ──────────────────────────────────────────────
# 수질 점수 계산 (금붕어 기준)
# ──────────────────────────────────────────────

def _calc_water_quality(temp, ph, do_val, turbidity) -> int:
    score = 100
    s = WATER_STANDARDS

    if temp < s['temp_min'] or temp > s['temp_max']:
        score -= 30
    else:
        score -= min(int(abs(temp - s['temp_optimal']) / 1.0) * 5, 15)

    if ph < 6.0 or ph > 8.5:
        score -= 30
    elif ph < s['ph_min'] or ph > s['ph_max']:
        score -= 15
    elif not (s['ph_optimal_lo'] <= ph <= s['ph_optimal_hi']):
        score -= 5

    if do_val < s['do_danger']:
        score -= 30
    elif do_val < s['do_min']:
        score -= 15

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

    heater_on   = getattr(tank, 'heater_on_temp',   WATER_STANDARDS['temp_min'])
    heater_off  = getattr(tank, 'heater_off_temp',  WATER_STANDARDS['temp_optimal'])
    cooling_on  = getattr(tank, 'cooling_on_temp',  WATER_STANDARDS['temp_max'])
    cooling_off = getattr(tank, 'cooling_off_temp', WATER_STANDARDS['temp_max'] - 1)
    filter_on   = getattr(tank, 'filter_on_ntu',    WATER_STANDARDS['turbidity_max'])
    filter_off  = getattr(tank, 'filter_off_ntu',   WATER_STANDARDS['turbidity_ok'])
    airpump_on  = getattr(tank, 'airpump_on_do',    WATER_STANDARDS['do_danger'])
    airpump_off = getattr(tank, 'airpump_off_do',   6.0)
    ph_min      = getattr(tank, 'ph_min',           WATER_STANDARDS['ph_min'])
    ph_max      = getattr(tank, 'ph_max',           WATER_STANDARDS['ph_max'])
    turb_warn   = getattr(tank, 'turbidity_max',    WATER_STANDARDS['turbidity_max']) * 2

    if temp < heater_on:
        _set_device('HEATER', True,  f"수온 {temp}°C → {heater_on}°C 미달")
    elif temp > heater_off:
        _set_device('HEATER', False, f"수온 {temp}°C → {heater_off}°C 도달")

    if temp > cooling_on:
        _set_device('COOLING', True,  f"수온 {temp}°C → {cooling_on}°C 초과")
    elif temp <= cooling_off:
        _set_device('COOLING', False, f"수온 {temp}°C → 정상 범위")

    if turb > filter_on:
        _set_device('FILTER', True,  f"탁도 {turb} NTU → {filter_on} 초과")
    elif turb <= filter_off:
        _set_device('FILTER', False, f"탁도 {turb} NTU → 정상")

    if do_v < airpump_on:
        _set_device('AIR_PUMP', True,  f"DO {do_v} mg/L → {airpump_on} 위험")
    elif do_v >= airpump_off:
        _set_device('AIR_PUMP', False, f"DO {do_v} mg/L → 정상")

    if ph < ph_min or ph > ph_max:
        EventLog.objects.create(tank=tank, level='DANGER', message=f"pH 이상: {ph}")
    if turb > turb_warn:
        EventLog.objects.create(tank=tank, level='WARNING', message=f"탁도 위험: {turb} NTU")

    return actions


# ──────────────────────────────────────────────
# 어항 상태 진단 코드 이벤트 처리
# ──────────────────────────────────────────────

# 감시 대상 코드 전체 목록 (정상 복귀 판정에 사용)
MONITORED_STATE_CODES = [
    'TMP-HIGH-001', 'TMP-LOW-001', 'DO-LOW-001', 'PH-OUT-001', 'TURB-HIGH-001',
]


def _check_state_events(tank: Tank, reading: SensorReading) -> list:
    """수질 기준 이탈 시 TankStateEvent 생성, 정상 복귀 시 is_resolved=True 처리.
    같은 code로 미해결 이벤트가 이미 있으면 중복 생성하지 않는다."""
    s = WATER_STANDARDS
    triggered = []  # [(code, value), ...]

    if reading.temperature > s['temp_max']:
        triggered.append(('TMP-HIGH-001', reading.temperature))
    if reading.temperature < s['temp_min']:
        triggered.append(('TMP-LOW-001', reading.temperature))
    if reading.dissolved_oxygen < s['do_min']:
        triggered.append(('DO-LOW-001', reading.dissolved_oxygen))
    if reading.ph < s['ph_min'] or reading.ph > s['ph_max']:
        triggered.append(('PH-OUT-001', reading.ph))
    if reading.turbidity > s['turbidity_max']:
        triggered.append(('TURB-HIGH-001', reading.turbidity))

    triggered_codes = {code for code, _ in triggered}
    created_codes = []

    for code, value in triggered:
        try:
            state_code = StateCode.objects.get(code=code)
        except StateCode.DoesNotExist:
            logger.warning(f"[상태코드 없음] {code} — seed_state_codes 실행 필요")
            continue

        # ✅ 같은 code로 미해결 이벤트가 이미 있으면 새로 만들지 않음 (중복 방지)
        already_open = TankStateEvent.objects.filter(
            tank=tank, state_code=state_code, is_resolved=False
        ).exists()
        if not already_open:
            TankStateEvent.objects.create(
                tank=tank, state_code=state_code,
                current_value=value,
                evidence={'reading_id': reading.id, 'value': value},
            )
            created_codes.append(code)

    # ✅ 더 이상 이상 범위가 아닌 코드는 자동 해결 처리
    resolved_codes = set(MONITORED_STATE_CODES) - triggered_codes
    if resolved_codes:
        TankStateEvent.objects.filter(
            tank=tank, state_code__code__in=resolved_codes, is_resolved=False
        ).update(is_resolved=True, resolved_at=timezone.now())

    return created_codes


# ──────────────────────────────────────────────
# 데이터 미수신 감지 / 자동 복구
# ──────────────────────────────────────────────

DATA_OFFLINE_THRESHOLD_SEC = 120  # 2분 — 센서가 10초 주기 전송이라 넉넉히 잡음


def _check_data_freshness(tank: Tank) -> str | None:
    """센서 데이터 수신이 끊겼는지 확인하고, 끊겼으면 경고 생성 /
    복구됐으면 자동 해제. 반환값은 'offline' / 'recovered' / None."""
    try:
        state_code = StateCode.objects.get(code='DATA-OFFLINE-001')
    except StateCode.DoesNotExist:
        logger.warning("DATA-OFFLINE-001 StateCode 없음 — seed_state_codes 실행 필요")
        return None

    latest = SensorReading.objects.filter(tank=tank).order_by('-created_at').first()
    now = timezone.now()

    open_event = TankStateEvent.objects.filter(
        tank=tank, state_code=state_code, is_resolved=False
    ).first()

    # 데이터가 아예 없거나, 마지막 수신이 임계 시간을 넘었으면 → 미수신 상태
    is_stale = (
        latest is None
        or (now - latest.created_at).total_seconds() > DATA_OFFLINE_THRESHOLD_SEC
    )

    if is_stale:
        if not open_event:
            TankStateEvent.objects.create(
                tank=tank, state_code=state_code,
                current_value=None,
                evidence={
                    'last_reading_at': latest.created_at.isoformat() if latest else None,
                },
            )
            EventLog.objects.create(
                tank=tank, level='DANGER', event_type='SYSTEM',
                message="[센서 미수신] 데이터 수신이 중단되었습니다."
            )
            return 'offline'
        return None  # 이미 경고 중 — 중복 생성 안 함

    # 정상 수신 중인데 열려있는 미수신 이벤트가 있으면 → 자동 복구
    if open_event:
        open_event.is_resolved = True
        open_event.resolved_at = now
        open_event.save(update_fields=['is_resolved', 'resolved_at'])
        EventLog.objects.create(
            tank=tank, level='INFO', event_type='SYSTEM',
            message="[센서 복구] 데이터 수신이 재개되었습니다."
        )
        return 'recovered'

    return None


# ──────────────────────────────────────────────
# [1] 센서 데이터  POST /monitoring/api/sensor/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_sensor_data(request):
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
    new_state_events = _check_state_events(tank, reading)
    recovery_status = _check_data_freshness(tank)   # ✅ 추가 — 데이터가 들어왔다는 건 곧 복구 신호
    logger.info(f"[센서] tank={tank.id} temp={temp} ph={ph} do={do_val} score={score}")

    return _ok({
        'reading_id': reading.id, 'water_quality_score': score,
        'auto_actions': actions,
        'new_state_events': new_state_events,
        'data_recovery': recovery_status,   # ✅ 추가 — 'recovered'면 방금 복구된 것
        'timestamp': reading.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [2] AI 행동 분석  POST /monitoring/api/behavior/
#     ✅ fish_details 배열 수신 시 개체별 상세 저장 (하위 호환 유지)
#     ✅ 수정: fish_count는 Pi가 보낸 값을 그대로 믿지 않고,
#        fish_details(실제 개체 목록)가 있으면 그걸 fish_id 기준으로
#        중복 제거한 뒤 그 개수를 최종 fish_count로 사용한다.
#        → 겹침(overlap)/중복 detection으로 fish_count 필드 자체가
#          부풀려져 오는 경우에도 실제 화면에 표시되는 마리 수는
#          왜곡되지 않는다.
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_fish_behavior(request):
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

    # ✅ fish_details를 fish_id 기준으로 먼저 중복 제거 (같은 요청 안에
    #    동일 fish_id가 두 번 이상 들어오면 마지막 값으로 덮어씀)
    raw_fish_details = data.get('fish_details', [])
    detail_map = {}
    for fd in raw_fish_details:
        try:
            fzone = str(fd.get('dominant_zone', 'MID')).upper()
            if fzone not in ['TOP', 'MID', 'BOT']:
                fzone = 'MID'
            fish_id = int(fd['fish_id'])
            detail_map[fish_id] = {
                'activity_level': float(fd.get('activity_level', 0.0)),
                'dominant_zone':  fzone,
                'abr_score':      float(fd.get('abr_score', 0.0)),
            }
        except (KeyError, TypeError, ValueError):
            continue

    # ✅ fish_details가 있으면 그 개수(중복 제거됨)를 진짜 물고기 수로 사용.
    #    없을 때만 Pi가 보낸 fish_count 필드를 그대로 사용(하위 호환).
    reported_fish_count = int(data.get('fish_count', 0) or 0)
    if detail_map:
        fish_count = len(detail_map)
        if reported_fish_count and reported_fish_count != fish_count:
            logger.warning(
                f"[행동] tank={tank.id} fish_count 불일치: "
                f"payload={reported_fish_count} vs fish_details={fish_count} "
                f"→ fish_details 기준으로 저장"
            )
    else:
        fish_count = reported_fish_count

    behavior = FishBehavior.objects.create(
        tank=tank,
        fish_count=fish_count,
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

    detail_objs = [
        FishActivityDetail(
            behavior=behavior,
            tank=tank,
            fish_id=fid,
            activity_level=v['activity_level'],
            dominant_zone=v['dominant_zone'],
            abr_score=v['abr_score'],
        )
        for fid, v in detail_map.items()
    ]
    if detail_objs:
        FishActivityDetail.objects.bulk_create(detail_objs)

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

    logger.info(f"[행동] tank={tank.id} status={status} anomaly={is_anomaly} fish_count={fish_count} fish_details={len(detail_objs)}")
    return _ok({
        'behavior_id': behavior.id, 'status': status,
        'is_anomaly': is_anomaly, 'fish_count': fish_count,
        'fish_detail_count': len(detail_objs),
        'timestamp': behavior.created_at.isoformat(),
    })


# ──────────────────────────────────────────────
# [2-1] AI 행동 분석 최신값 조회
#       GET /monitoring/api/behavior/latest/?tank_id=1  (프론트용)
#       ✅ 개체별 활동량/구역 배열(fish) 포함
# ──────────────────────────────────────────────

@require_http_methods(['GET'])
def get_behavior_latest(request):
    tank_id = request.GET.get('tank_id', 1)
    try:
        b = FishBehavior.objects.filter(tank_id=tank_id).latest('created_at')
        fish_list = [
            {
                'fish_id':        d.fish_id,
                'activity_level': round(float(d.activity_level), 2),
                'dominant_zone':  d.dominant_zone,
            }
            for d in b.fish_details.all().order_by('fish_id')
        ]
        return JsonResponse({
            'fish_count':     b.fish_count,
            'activity_level': round(float(b.activity_level), 2),
            'dominant_zone':  b.dominant_zone,
            'zone_top_ratio': round(float(b.zone_top_ratio), 3),
            'zone_mid_ratio': round(float(b.zone_mid_ratio), 3),
            'zone_bot_ratio': round(float(b.zone_bot_ratio), 3),
            'size_index':     round(float(b.size_index), 3),
            'status':         b.status,
            'status_ko':      STATUS_KO.get(b.status, b.status),
            'is_anomaly':     b.is_anomaly,
            'note':           b.note or '',
            'fish':           fish_list,
            'timestamp':      b.created_at.isoformat(),
        })
    except FishBehavior.DoesNotExist:
        return JsonResponse({'error': 'no data'}, status=404)


# ──────────────────────────────────────────────
# [3] 급이 이벤트  POST /monitoring/api/feeding/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def receive_feeding_event(request):
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
#               GET  /monitoring/api/growth/?tank_id=1  (프론트용)
# ──────────────────────────────────────────────

GROWTH_STAGE_KO = {'FRY': '치어', 'JUVENILE': '유어', 'YOUNG': '유어', 'ADULT': '성어'}

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def receive_growth_record(request):

    if request.method == 'GET':
        tank_id = request.GET.get('tank_id', 1)
        try:
            g = GrowthRecord.objects.filter(tank_id=tank_id).latest('created_at')
            stage_raw = (g.growth_stage or '').upper()
            return JsonResponse({
                'current_size_cm': float(g.estimated_length or 0),
                'estimated_stage': GROWTH_STAGE_KO.get(stage_raw, stage_raw or '--'),
                'growth_per_day':  float(g.growth_rate or 0),
                'fish_id':         g.fish_id,
                'timestamp':       g.created_at.isoformat(),
            })
        except GrowthRecord.DoesNotExist:
            return JsonResponse({'error': 'no data'}, status=404)

    if not _check_api_key(request):
        return _error("인증 실패: 유효하지 않은 API Key입니다.", status=401)

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
#               GET  /monitoring/api/pattern/?tank_id=1  (프론트용)
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def receive_activity_pattern(request):

    if request.method == 'GET':
        tank_id = request.GET.get('tank_id', 1)
        try:
            p = ActivityPattern.objects.filter(tank_id=tank_id).latest('created_at')

            raw = p.hourly_activity or {}
            if isinstance(raw, dict):
                hourly = [float(raw.get(str(i), 0)) for i in range(24)]
            elif isinstance(raw, list):
                hourly = [float(v) for v in raw[:24]]
                hourly += [0.0] * (24 - len(hourly))
            else:
                hourly = [0.0] * 24

            current_hour     = datetime.now().hour
            current_activity = hourly[current_hour]
            avg = sum(hourly) / 24 if any(hourly) else 1
            baseline_pct = round((current_activity - avg) / avg * 100, 1) if avg else 0

            return JsonResponse({
                'hourly_activity':       hourly,
                'current_hour_activity': round(current_activity, 2),
                'compared_to_baseline':  baseline_pct,
                'has_anomaly':           p.has_anomaly,
                'timestamp':             p.created_at.isoformat(),
            })
        except ActivityPattern.DoesNotExist:
            return JsonResponse({'error': 'no data'}, status=404)

    if not _check_api_key(request):
        return _error("인증 실패: 유효하지 않은 API Key입니다.", status=401)

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
# [7] Pi IP 자동 등록  POST /monitoring/api/register-pi/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def register_pi(request):
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank, err = _get_tank(data.get('tank_id'))
    if err:
        return err

    pi_ip = data.get('pi_ip', '').strip()
    if not pi_ip:
        return _error("pi_ip 필드가 필요합니다.")

    pi_stream_port = int(data.get('pi_stream_port', 8080))

    tank.pi_ip          = pi_ip
    tank.pi_stream_port = pi_stream_port
    tank.pi_last_seen   = timezone.now()
    tank.save(update_fields=['pi_ip', 'pi_stream_port', 'pi_last_seen'])

    logger.info(f"[Pi 등록] tank={tank.id} ip={pi_ip}:{pi_stream_port}")
    EventLog.objects.create(
        tank=tank, level='INFO',
        message=f"[Pi 연결] {pi_ip}:{pi_stream_port} — 카메라 스트림 준비 완료"
    )

    return _ok({
        'tank_id':        tank.id,
        'pi_ip':          pi_ip,
        'pi_stream_port': pi_stream_port,
        'stream_url':     f"http://{pi_ip}:{pi_stream_port}/stream.mjpg",
    })


# ──────────────────────────────────────────────
# [7-1] 카메라 URL 등록  POST /monitoring/api/register-camera-url/
#       ✅ scheme(https 등) 보존 버그 수정
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def register_camera_url(request):
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank, err = _get_tank(data.get('tank_id'))
    if err:
        return err

    camera_url = data.get('camera_url', '').strip()
    if not camera_url:
        return _error("camera_url 필드가 필요합니다.")

    parsed = urlparse(camera_url)
    # ✅ scheme까지 포함해서 저장 (예: https://xxxx.trycloudflare.com)
    #    scheme이 없으면 원본 문자열을 그대로 사용
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else camera_url.rstrip('/')

    tank.pi_ip        = base_url
    tank.pi_last_seen = timezone.now()
    tank.save(update_fields=['pi_ip', 'pi_last_seen'])

    logger.info(f"[카메라 URL 등록] tank={tank.id} base_url={base_url}")
    EventLog.objects.create(
        tank=tank, level='INFO',
        message=f"[카메라 연결] Cloudflare 터널 등록 완료 ({base_url})"
    )

    return _ok({
        'tank_id':    tank.id,
        'camera_url': camera_url,
        'stream_url': f"{base_url}/stream.mjpg",
    })


# ──────────────────────────────────────────────
# [8] 이벤트 로그 수신  POST /monitoring/api/event-log/
# ──────────────────────────────────────────────

@csrf_exempt
@api_key_required
@require_http_methods(['POST'])
def create_event_log(request):
    data = _parse_body(request)
    if not data:
        return _error("요청 바디가 비어있거나 JSON 형식이 아닙니다.")

    tank_id = data.get('tank_id') or 1
    level   = data.get('level', 'INFO').upper()
    message = data.get('message', '').strip()

    if not message:
        return _error("message 필드가 필요합니다.")
    if level not in ('INFO', 'WARNING', 'DANGER'):
        level = 'INFO'

    tank, err = _get_tank(tank_id)
    if err:
        return err

    log = EventLog.objects.create(tank=tank, level=level, message=message)
    return _ok({'log_id': log.id, 'level': level, 'message': message})


# ──────────────────────────────────────────────
# [9] 헬스체크  GET /monitoring/api/health/
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET'])
def health_check(request):
    return _ok({'message': 'server is running', 'time': timezone.now().isoformat()})


# ──────────────────────────────────────────────
# [10] FRS 최신 조회  GET /monitoring/api/frs/?tank_id=1
# ──────────────────────────────────────────────

@require_http_methods(['GET'])
def get_frs(request):
    tank_id = request.GET.get('tank_id', 1)
    try:
        r = FeedingResponse.objects.filter(tank_id=tank_id).latest('created_at')
        score = int(r.frs_score or 0)
        if   score >= 70: status = '양호'
        elif score >= 40: status = '주의'
        else:             status = '위험'

        ar_ratio          = float(r.ar_ratio or 1.0)
        activity_increase = round((ar_ratio - 1.0) * 100, 1)

        return JsonResponse({
            'score':                     score,
            'status':                    status,
            'response_time_sec':         float(r.rt_seconds or 0),
            'activity_increase_percent': activity_increase,
            'surface_visits':            round(float(r.sf_ratio or 0) * 10),
            'comment':                   f"급이 반응 점수 {score}점 — {status}",
            'timestamp':                 r.created_at.isoformat(),
        })
    except FeedingResponse.DoesNotExist:
        return JsonResponse({'error': 'no data'}, status=404)


# ──────────────────────────────────────────────
# [11] ABR 최신 조회  GET /monitoring/api/abr/?tank_id=1
#      ✅ 개체별 ABR 배열(fish) 포함
# ──────────────────────────────────────────────

@require_http_methods(['GET'])
def get_abr(request):
    tank_id = request.GET.get('tank_id', 1)
    try:
        b = FishBehavior.objects.filter(tank_id=tank_id).latest('created_at')
        abr_rate = round(float(b.abr_score or 0) * 100, 1)
        if   abr_rate <= 10: status = '정상'
        elif abr_rate <= 30: status = '주의'
        else:                status = '위험'

        anomaly_count = FishBehavior.objects.filter(tank_id=tank_id, is_anomaly=True).count()

        fish_list = []
        for d in b.fish_details.all().order_by('fish_id'):
            rate = round(float(d.abr_score or 0) * 100, 1)
            f_status = '정상' if rate <= 10 else ('관찰' if rate <= 30 else '위험')
            fish_list.append({'fish_id': d.fish_id, 'abr_rate': rate, 'status': f_status})

        return JsonResponse({
            'abr_rate':      abr_rate,
            'status':        status,
            'anomaly_count': anomaly_count,
            'fish':          fish_list,
            'timestamp':     b.created_at.isoformat(),
        })
    except FishBehavior.DoesNotExist:
        return JsonResponse({'error': 'no data'}, status=404)


# ──────────────────────────────────────────────
# [12] 성장 차트 데이터  (뷰 헬퍼 + GET 엔드포인트)
#      GET /monitoring/api/growth/chart/?tank_id=1  (프론트용)
#
# 최근 42개 레코드 (fish_id × 14일치) 기준
# 날짜별·fish_id별 최신 체장(estimated_length) 반환
# ──────────────────────────────────────────────

def _get_growth_chart(tank) -> str:
    """
    Tank 객체를 받아 Chart.js 호환 JSON 문자열을 반환합니다.
    데이터가 없으면 '{}'를 반환합니다.

    반환 구조:
    {
        "labels":   ["MM/DD", ...],          # 날짜 레이블 (오름차순)
        "datasets": [
            {
                "label": "금붕어 1호",
                "data":  [1.2, 1.3, None, ...],  # 해당 날짜 데이터 없으면 None
                "color": "#3b82f6"
            },
            ...
        ]
    }
    """
    # 최근 42개 (3마리 × 14일치 기준)
    records = list(
        GrowthRecord.objects.filter(tank=tank)
        .order_by('created_at')
        .values('fish_id', 'estimated_length', 'created_at')
    )[-42:]

    if not records:
        return json.dumps({})

    # 날짜별·fish_id별 최신 체장 값 집계
    date_fish: dict = defaultdict(dict)
    for r in records:
        date_str = r['created_at'].strftime("%m/%d")
        fid      = r['fish_id']
        date_fish[date_str][fid] = round(float(r['estimated_length']), 2)

    labels   = sorted(date_fish.keys())
    fish_ids = sorted({r['fish_id'] for r in records})
    colors   = ['#3b82f6', '#10b981', '#f59e0b']  # 파랑·초록·노랑

    datasets = []
    for i, fid in enumerate(fish_ids):
        datasets.append({
            'label': f'금붕어 {fid}호',
            'data':  [date_fish[d].get(fid) for d in labels],  # 없으면 None
            'color': colors[i % len(colors)],
        })

    return json.dumps({'labels': labels, 'datasets': datasets}, ensure_ascii=False)


@require_http_methods(['GET'])
def get_growth_chart(request):
    """GET /monitoring/api/growth/chart/?tank_id=1"""
    tank_id = request.GET.get('tank_id', 1)
    tank, err = _get_tank(tank_id)
    if err:
        return err

    chart_json = _get_growth_chart(tank)
    chart_data = json.loads(chart_json)

    if not chart_data:
        return JsonResponse({'error': 'no data'}, status=404)

    return JsonResponse(chart_data)


# ──────────────────────────────────────────────
# [13] 개체별 성장 최신값 조회  GET /monitoring/api/growth/latest-all/?tank_id=1
# ──────────────────────────────────────────────

@require_http_methods(['GET'])
def get_growth_latest_all(request):
    tank_id = request.GET.get('tank_id', 1)
    tank, err = _get_tank(tank_id)
    if err:
        return err

    fish_ids = GrowthRecord.objects.filter(tank=tank).values_list('fish_id', flat=True).distinct()
    fish = []
    for fid in fish_ids:
        r = GrowthRecord.objects.filter(tank=tank, fish_id=fid).latest('created_at')
        stage_raw = (r.growth_stage or '').upper()
        fish.append({
            'fish_id':          fid,
            'estimated_length': round(float(r.estimated_length or 0), 2),
            'growth_rate':      round(float(r.growth_rate or 0), 3),
            'growth_stage':     GROWTH_STAGE_KO.get(stage_raw, stage_raw or '--'),
        })
    fish.sort(key=lambda x: x['fish_id'])

    if not fish:
        return JsonResponse({'error': 'no data'}, status=404)

    avg_length = round(sum(f['estimated_length'] for f in fish) / len(fish), 2)
    avg_rate   = round(sum(f['growth_rate'] for f in fish) / len(fish), 3)

    return JsonResponse({'fish': fish, 'avg_length': avg_length, 'avg_rate': avg_rate})


# ──────────────────────────────────────────────
# [14] 일별 급이량 차트  GET /monitoring/api/feeding/chart/?tank_id=1
#      최근 7일 — 오전(14시 이전)/오후(14시 이후) 2구간으로 분리 집계
# ──────────────────────────────────────────────

@require_http_methods(['GET'])
def get_feeding_chart(request):
    tank_id = request.GET.get('tank_id', 1)
    tank, err = _get_tank(tank_id)
    if err:
        return err

    import datetime as dt
    from django.db.models import Sum

    WEEKDAY_KO = ['월', '화', '수', '목', '금', '토', '일']
    today = timezone.now().date()

    labels, am_amounts, pm_amounts = [], [], []
    for i in range(6, -1, -1):
        day = today - dt.timedelta(days=i)
        qs  = FeedingEvent.objects.filter(tank=tank, created_at__date=day)
        am  = qs.filter(created_at__hour__lt=14).aggregate(total=Sum('amount_g'))['total'] or 0.0
        pm  = qs.filter(created_at__hour__gte=14).aggregate(total=Sum('amount_g'))['total'] or 0.0
        labels.append(WEEKDAY_KO[day.weekday()])
        am_amounts.append(round(am, 3))
        pm_amounts.append(round(pm, 3))

    return JsonResponse({'labels': labels, 'am': am_amounts, 'pm': pm_amounts})


# ──────────────────────────────────────────────
# [15] 미해결 알림 목록 조회  GET /monitoring/api/alerts/
#      로그인한 사용자의 모든 어항 기준으로 조회 (상단바 공통 표시용)
#      ✅ 조회 전에 프레시니스 체크를 먼저 수행 → 이 API가 30초마다
#         호출되는 것만으로 "데이터 미수신" 자동 감지가 이루어짐
# ──────────────────────────────────────────────

@require_http_methods(['GET'])
def get_active_alerts(request):
    if not request.user.is_authenticated:
        return JsonResponse({'count': 0, 'alerts': []})

    # ✅ 조회 전에 사용자의 모든 어항에 대해 미수신 여부를 먼저 갱신
    user_tanks = Tank.objects.filter(user=request.user)
    for t in user_tanks:
        _check_data_freshness(t)

    events = (
        TankStateEvent.objects
        .filter(tank__user=request.user, is_resolved=False)
        .select_related('tank', 'state_code')
        .order_by('-detected_at')[:20]
    )

    alerts = [
        {
            'id':           e.id,
            'tank_id':      e.tank_id,
            'tank_name':    e.tank.name,
            'code':         e.state_code.code,
            'title':        e.state_code.title,
            'level':        e.state_code.level,
            'current_value': e.current_value,
            'actions':      e.state_code.actions,  # 조치 추천 목록
            'detected_at':  e.detected_at.isoformat(),
        }
        for e in events
    ]

    return JsonResponse({'count': len(alerts), 'alerts': alerts})


# ──────────────────────────────────────────────
# [16] 특정 어항의 미해결 상태 상세 조회  GET /monitoring/api/states/active/?tank_id=1
#      원인/영향/조치/예방까지 전부 포함 (어항 상세 페이지용)
# ──────────────────────────────────────────────

@require_http_methods(['GET'])
def get_active_states(request):
    """
    GET /monitoring/api/states/active/?tank_id=1
    현재 미해결 TankStateEvent 목록 반환.
    이상 없으면 states: [] 반환.
    """
    tank_id = request.GET.get('tank_id')
    if not tank_id:
        return JsonResponse({'states': []})

    try:
        tank = Tank.objects.get(id=tank_id)
    except Tank.DoesNotExist:
        return JsonResponse({'states': []})

    events = (
        TankStateEvent.objects
        .filter(tank=tank, is_resolved=False)
        .select_related('state_code')
        .order_by('detected_at')
    )

    states = []
    for ev in events:
        sc = ev.state_code
        states.append({
            'code':        sc.code,
            'title':       sc.title,
            'level':       sc.level,          # 'WARNING' | 'DANGER'
            'causes':      sc.causes or [],
            'effects':     sc.effects or [],
            'actions':     sc.actions or [],
            'prevention':  sc.prevention or [],
            'current_value': ev.current_value,
            'detected_at': ev.detected_at.isoformat(),
        })

    return JsonResponse({'states': states})