import json
import os
import re
import PIL.Image
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from django.db import transaction
from django.utils import timezone
from datetime import date, timedelta

from .models import Tank, EventLog, DeviceControl, SensorReading, FishBehavior


# ──────────────────────────────────────────────
# [1] 메인 대시보드 및 리스트
# ──────────────────────────────────────────────

@login_required
def index(request):
    """메인 페이지: 사용자 어항 목록 및 상태 요약"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10)
    page_obj  = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        if latest and latest.temperature is not None:
            try:
                target  = float(tank.target_temp or 26.0)
                current = float(latest.temperature)
                if abs(current - target) >= 2.0:
                    status = "DANGER"
            except:
                pass

        d_day = 7
        if tank.last_water_change:
            try:
                period      = int(tank.water_change_period or 7)
                next_change = tank.last_water_change + timedelta(days=period)
                d_day       = (next_change - date.today()).days
            except:
                pass

        tank_data.append({'tank': tank, 'latest': latest, 'status': status, 'd_day': d_day})

    return render(request, 'core/index.html', {
        'tank_data': tank_data,
        'page_obj':  page_obj,
        'has_tanks': all_tanks.exists(),
    })


# ✅ 추가: 차트용 히스토리 생성 헬퍼
def _get_chart_history(tank):
    """최근 12개 센서 데이터로 Chart.js용 JSON 생성"""
    readings = list(
        SensorReading.objects.filter(tank=tank).order_by('-created_at')[:12]
    )
    readings.reverse()
    return json.dumps({
        "labels": [r.created_at.strftime("%H:%M") for r in readings],
        "temp":   [r.temperature         for r in readings],
        "ph":     [r.ph                  for r in readings],
        "do":     [r.dissolved_oxygen    for r in readings],
        "turb":   [r.turbidity           for r in readings],
    }, ensure_ascii=False)


def _get_growth_chart(tank):
    """최근 14일 성장 차트 데이터"""
    from .models import GrowthRecord
    records = list(
        GrowthRecord.objects.filter(tank=tank)
        .order_by('-created_at')[:14]
    )
    records.reverse()
    return json.dumps({
        "labels": [r.created_at.strftime("%m/%d") for r in records],
        "length": [r.estimated_length for r in records],
        "weight": [r.estimated_weight for r in records],
    }, ensure_ascii=False)


def _get_feeding_chart(tank):
    """최근 7일 급이 차트 데이터"""
    from .models import FeedingEvent
    from django.db.models import Sum
    from django.utils import timezone
    import datetime

    today = timezone.now().date()
    labels, amounts = [], []
    for i in range(6, -1, -1):
        day = today - datetime.timedelta(days=i)
        total = FeedingEvent.objects.filter(
            tank=tank,
            created_at__date=day
        ).aggregate(total=Sum('amount_g'))['total'] or 0.0
        labels.append(day.strftime("%m/%d"))
        amounts.append(round(total, 3))

    return json.dumps({"labels": labels, "amounts": amounts}, ensure_ascii=False)


@login_required
def dashboard(request, tank_id=None):
    """특정 어항 상세 대시보드"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()

    if not tank:
        return render(request, 'monitoring/dashboard.html', {'tank': None})

    # 최신 센서 데이터
    latest = tank.readings.order_by('-created_at').first()

    # 최신 AI 행동 분석
    latest_behavior = tank.behaviors.order_by('-created_at').first() if hasattr(tank, 'behaviors') else None

    # 장치 상태
    devices = {d.type: d for d in DeviceControl.objects.filter(tank=tank)}

    # 최근 로그 3개
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:3]

    # 환수 D-day
    d_day = 7
    if tank.last_water_change:
        try:
            period      = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day       = (next_change - date.today()).days
        except:
            pass

    # 오늘 환수 여부
    is_water_changed_today = (tank.last_water_change == date.today())

    # 사용자 전체 어항 목록 (탭용)
    user_tanks = Tank.objects.filter(user=request.user).order_by('-id')

    return render(request, 'monitoring/dashboard.html', {
        'tank':                   tank,
        'latest':                 latest,
        'latest_behavior':        latest_behavior,
        'devices':                devices,
        'logs':                   logs,
        'd_day':                  d_day,
        'is_water_changed_today': is_water_changed_today,
        'user_tanks':             user_tanks,
        # ✅ 추가: 차트 초기 데이터
        'chart_history':   _get_chart_history(tank),
        'growth_chart':    _get_growth_chart(tank),
        'feeding_chart':   _get_feeding_chart(tank),
        # 장치별 ON/OFF 편의 변수
        'heater_on':   devices.get('HEATER',   None) and devices['HEATER'].is_on,
        'cooling_on':  devices.get('COOLING',  None) and devices['COOLING'].is_on,
        'filter_on':   devices.get('FILTER',   None) and devices['FILTER'].is_on,
        'air_pump_on': devices.get('AIR_PUMP', None) and devices['AIR_PUMP'].is_on,
        'feeder_on':   devices.get('FEEDER',   None) and devices['FEEDER'].is_on,
        'light_on':    devices.get('LIGHT',    None) and devices['LIGHT'].is_on,
    })


# ✅ 추가: AJAX 폴링 엔드포인트
@login_required
def dashboard_data(request, tank_id):
    """
    대시보드 AJAX 폴링용 — 최신 센서값 + 차트 히스토리 반환
    GET /monitoring/api/dashboard-data/{tank_id}/
    """
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)

    latest   = SensorReading.objects.filter(tank=tank).order_by('-created_at').first()
    readings = list(
        SensorReading.objects.filter(tank=tank).order_by('-created_at')[:12]
    )
    readings.reverse()

    sensor = None
    if latest:
        sensor = {
            "temperature":      latest.temperature,
            "ph":               latest.ph,
            "dissolved_oxygen": latest.dissolved_oxygen,
            "turbidity":        latest.turbidity,
            "water_level":      latest.water_level,
        }

    history = {
        "labels": [r.created_at.strftime("%H:%M") for r in readings],
        "temp":   [r.temperature         for r in readings],
        "ph":     [r.ph                  for r in readings],
        "do":     [r.dissolved_oxygen    for r in readings],
        "turb":   [r.turbidity           for r in readings],
    }

    return JsonResponse({"sensor": sensor, "history": history})


@login_required
def tank_settings(request, tank_id):
    """어항 세부 설정 페이지"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)

    if request.method == 'POST':
        try:
            # 수질 기준값
            tank.temp_min      = float(request.POST.get('temp_min',      21.0))
            tank.temp_max      = float(request.POST.get('temp_max',      24.0))
            tank.ph_min        = float(request.POST.get('ph_min',         6.5))
            tank.ph_max        = float(request.POST.get('ph_max',         8.0))
            tank.do_min        = float(request.POST.get('do_min',         5.0))
            tank.turbidity_max = float(request.POST.get('turbidity_max', 50.0))

            # 장치 히스테리시스
            tank.heater_on_temp   = float(request.POST.get('heater_on_temp',   21.0))
            tank.heater_off_temp  = float(request.POST.get('heater_off_temp',  22.0))
            tank.cooling_on_temp  = float(request.POST.get('cooling_on_temp',  24.0))
            tank.cooling_off_temp = float(request.POST.get('cooling_off_temp', 23.0))
            tank.filter_on_ntu    = float(request.POST.get('filter_on_ntu',   50.0))
            tank.filter_off_ntu   = float(request.POST.get('filter_off_ntu',  20.0))
            tank.airpump_on_do    = float(request.POST.get('airpump_on_do',    4.0))
            tank.airpump_off_do   = float(request.POST.get('airpump_off_do',   6.0))

            # 급이 설정
            tank.feeding_times    = request.POST.get('feeding_times', '08:00,12:00,18:00')
            tank.feeding_amount_g = float(request.POST.get('feeding_amount_g', 0.1))
            tank.feeding_auto     = request.POST.get('feeding_auto') == 'on'

            # 조명 타이머
            tank.light_on_hour  = int(request.POST.get('light_on_hour',  8))
            tank.light_off_hour = int(request.POST.get('light_off_hour', 20))
            tank.light_auto     = request.POST.get('light_auto') == 'on'

            tank.save()
            messages.success(request, "설정이 저장되었습니다.")
            return redirect('monitoring:tank_settings', tank_id=tank.id)

        except Exception as e:
            messages.error(request, f"저장 실패: {e}")

    return render(request, 'monitoring/tank_settings.html', {'tank': tank})


@login_required
def tank_settings_api(request, tank_id):
    """설정값 JSON 반환 (Pi용)"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    return JsonResponse({
        'water': {
            'temp_min': tank.temp_min, 'temp_max': tank.temp_max,
            'ph_min': tank.ph_min,     'ph_max': tank.ph_max,
            'do_min': tank.do_min,     'turbidity_max': tank.turbidity_max,
        },
        'devices': {
            'heater_on': tank.heater_on_temp,   'heater_off': tank.heater_off_temp,
            'cooling_on': tank.cooling_on_temp, 'cooling_off': tank.cooling_off_temp,
            'filter_on': tank.filter_on_ntu,    'filter_off': tank.filter_off_ntu,
            'airpump_on': tank.airpump_on_do,   'airpump_off': tank.airpump_off_do,
        },
        'feeding': {
            'times': tank.feeding_times.split(','),
            'amount_g': tank.feeding_amount_g,
            'auto': tank.feeding_auto,
        },
        'light': {
            'on_hour': tank.light_on_hour,
            'off_hour': tank.light_off_hour,
            'auto': tank.light_auto,
        },
    })
    """어항 관리 목록"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {
        'tanks':      all_tanks,
        'tank_count': all_tanks.count(),
    })


# ──────────────────────────────────────────────
# [2] 어항 관리 CRUD
# ──────────────────────────────────────────────

@login_required
def add_tank(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                tank = Tank.objects.create(
                    user=request.user,
                    name=request.POST.get('name', '새 어항'),
                    target_temp=float(request.POST.get('target_temp') or 26.0),
                    water_change_period=int(request.POST.get('water_change_period') or 7),
                    last_water_change=date.today(),
                )
            messages.success(request, f"'{tank.name}' 등록 완료.")
            return redirect('monitoring:tank_list')
        except Exception as e:
            messages.error(request, f"오류: {e}")
    return render(request, 'monitoring/tank_form.html', {'title': '어항 등록'})


@login_required
def edit_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        tank.name        = request.POST.get('name', tank.name)
        tank.target_temp = float(request.POST.get('target_temp') or 26.0)
        tank.save()
        messages.success(request, "수정 완료.")
        return redirect('monitoring:tank_list')
    return render(request, 'monitoring/tank_form.html', {'tank': tank, 'title': '어항 수정'})


@login_required
def delete_tank(request, tank_id):
    get_object_or_404(Tank, id=tank_id, user=request.user).delete()
    messages.success(request, "삭제 완료.")
    return redirect('monitoring:tank_list')


@login_required
@require_POST
def delete_tanks(request):
    tank_ids = request.POST.getlist('tank_ids')
    if tank_ids:
        deleted_count, _ = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"{deleted_count}개의 어항이 성공적으로 삭제되었습니다.")
    else:
        messages.warning(request, "삭제할 어항을 선택해주세요.")
    return redirect('monitoring:tank_list')


# ──────────────────────────────────────────────
# [3] 제어, 로그 및 카메라
# ──────────────────────────────────────────────

@login_required
def logs_view(request):
    tank_id    = request.GET.get('tank_id')
    level      = request.GET.get('level')
    user_tanks = Tank.objects.filter(user=request.user).order_by('-id')

    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    if tank_id:
        logs = logs.filter(tank_id=tank_id)
    if level:
        logs = logs.filter(level=level)

    paginator = Paginator(logs, 20)
    page_obj  = paginator.get_page(request.GET.get('page'))

    return render(request, 'monitoring/logs.html', {
        'page_obj':   page_obj,
        'user_tanks': user_tanks,
        'tank_id':    tank_id,
        'level':      level,
    })


@login_required
def camera_view(request):
    tank = Tank.objects.filter(user=request.user).first()
    return render(request, 'monitoring/camera.html', {'tank': tank, 'title': '실시간 모니터링'})


@login_required
@require_POST
def toggle_device(request, tank_id):
    tank      = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=request.POST.get('device_type'))
    device.is_on = not device.is_on
    device.save()

    state = "ON" if device.is_on else "OFF"
    EventLog.objects.create(
        tank=tank,
        level='INFO',
        message=f"[수동제어] {device.get_type_display()} {state}"
    )
    return JsonResponse({'status': 'success', 'is_on': device.is_on})


@login_required
@require_POST
def perform_water_change(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    EventLog.objects.create(tank=tank, level='INFO', message="환수 완료 기록")
    return JsonResponse({'status': 'success'})


# ──────────────────────────────────────────────
# [4] 리포트
# ──────────────────────────────────────────────

@login_required
def ai_report_list(request):
    tanks     = Tank.objects.filter(user=request.user).order_by('-id')
    has_tanks = tanks.exists()

    tank_id       = request.GET.get('tank_id')
    selected_tank = None

    if has_tanks:
        if tank_id:
            selected_tank = tanks.filter(id=tank_id).first()
        if not selected_tank:
            selected_tank = tanks.first()

    sort_order = request.GET.get('sort', 'desc')
    order_by   = '-created_at' if sort_order == 'desc' else 'created_at'

    report_data = []
    behaviors   = []
    reports     = []

    if selected_tank:
        report_data = selected_tank.readings.all().order_by(order_by)
        behaviors   = selected_tank.behaviors.all().order_by(order_by)[:10] if hasattr(selected_tank, 'behaviors') else []
        try:
            ReportModel = apps.get_model('reports', 'Report')
            reports     = ReportModel.objects.filter(tank=selected_tank).order_by('-created_at')
        except:
            pass

    return render(request, 'reports/report_list.html', {
        'tanks':         tanks,
        'selected_tank': selected_tank,
        'report_data':   report_data,
        'behaviors':     behaviors,
        'reports':       reports,
        'sort':          sort_order,
        'has_tanks':     has_tanks,
    })


@login_required
@require_POST
def delete_report_data(request, reading_id):
    reading = get_object_or_404(SensorReading, id=reading_id, tank__user=request.user)
    tank_id = reading.tank.id
    reading.delete()
    messages.success(request, "기록이 삭제되었습니다.")
    return redirect(f'/reports/?tank_id={tank_id}')


@login_required
def download_report(request, tank_id):
    tank   = get_object_or_404(Tank, id=tank_id, user=request.user)
    period = request.GET.get('period', 'daily')
    today  = timezone.now()

    if period == 'weekly':
        start_date = today - timedelta(days=7)
    elif period == 'monthly':
        start_date = today - timedelta(days=30)
    else:
        start_date = today - timedelta(days=1)

    readings = tank.readings.filter(created_at__gte=start_date).order_by('-created_at')

    content = (
        f"[{tank.name}] {period.upper()} 분석 기록\n"
        f"기준일: {today.strftime('%Y-%m-%d')}\n"
        + "=" * 40 + "\n"
    )
    if readings.exists():
        for r in readings:
            content += (
                f"{r.created_at.strftime('%Y-%m-%d %H:%M')} | "
                f"수온:{r.temperature}°C | "
                f"pH:{r.ph} | "
                f"DO:{r.dissolved_oxygen}mg/L | "
                f"탁도:{r.turbidity}NTU | "
                f"수질점수:{r.water_quality_score}\n"
            )
    else:
        content += "데이터가 없습니다."

    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{tank.name}_{period}_report.txt"'
    return response


# ──────────────────────────────────────────────
# [5] AI 챗봇
# ──────────────────────────────────────────────

def _build_prompt(display_name: str, user_message: str) -> str:
    return f"""너는 어항 관리 전문 도우미야. 질문 유형을 파악해서 아래 형식에 맞게 답해.

[말투 규칙]
- 반말 금지, 존댓말 사용
- 문장은 짧고 핵심만
- 이모지 사용 금지 (숫자 목록 기호만 허용)
- "안녕하세요", "물론이죠" 같은 인삿말 금지
- 어항 정보 없다는 언급 금지

[질문 유형별 답변 형식]

1. 물고기 추천 질문 (예: 초보자용 물고기, 금붕어 종류, 같이 키울 수 있는 물고기)
→ 추천 물고기 2~3종을 아래 형식으로
   물고기명: 특징 한 줄, 난이도, 적정 수온
   
2. 수질/센서 설정 질문 (예: 수온 몇 도, pH 범위, 금붕어 수질)
→ 항목별 수치를 표 형식으로
   수온: XX~XX°C
   pH: X.X~X.X
   DO: Xmg/L 이상
   탁도: XXNTU 이하

3. 어항 세팅 질문 (예: 처음 어항 세팅, 여과기 선택, 어항 크기)
→ 순서가 있으면 번호 목록, 없으면 항목별로
   핵심 정보만 3~5줄 이내

4. 물고기 관리/질병 질문 (예: 먹이 양, 환수 주기, 지느러미 썩음병)
→ 원인 + 해결책 위주로 간결하게

5. 기타 어항 관련 질문
→ 핵심만 3~5줄 이내

질문: {user_message}"""


def _format_reply(raw: str, display_name: str) -> str:
    # 마크다운 제거
    raw = raw.replace('**', '').replace('##', '').replace('# ', '').strip()

    # 이모지 제거 (숫자/특수기호 유지)
    import unicodedata
    cleaned = []
    for ch in raw:
        cat = unicodedata.category(ch)
        cp  = ord(ch)
        # 이모지 범위 제거
        if 0x1F300 <= cp <= 0x1FAFF:
            continue
        if 0x2600 <= cp <= 0x27BF:
            continue
        cleaned.append(ch)
    raw = ''.join(cleaned).strip()

    # 빈 줄 정리
    lines = [l.rstrip() for l in raw.split('\n')]
    # 연속 빈 줄 제거
    result = []
    prev_blank = False
    for line in lines:
        if line == '':
            if not prev_blank:
                result.append(line)
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False

    reply = '\n'.join(result).strip()

    if len(reply) < 10:
        reply = (
            "수온: 22~26°C\n"
            "pH: 6.8~7.5\n"
            "DO: 5mg/L 이상\n"
            "환수: 주 1회 20~30%\n"
            "여과기: 24시간 가동"
        )
    return reply


@login_required
@require_POST
def chat_api(request):
    try:
        if request.content_type == 'application/json':
            user_message = json.loads(request.body).get('message', '').strip()
            image_file   = None
        else:
            user_message = request.POST.get('message', '').strip()
            image_file   = request.FILES.get('image')

        display_name = getattr(request.user, 'nickname', None) or request.user.username
        api_key      = os.getenv('GEMINI_API_KEY_1') or getattr(settings, 'GEMINI_API_KEY', None)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-8b")

        prompt_parts = [_build_prompt(display_name, user_message)]

        if image_file:
            img = PIL.Image.open(image_file)
            img.thumbnail((512, 512))
            prompt_parts.append(img)

        response = model.generate_content(
            prompt_parts,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=150,
                temperature=0.3,
            ),
            request_options={"timeout": 10},  # ✅ 추가: 10초 타임아웃
        )

        raw   = response.text if response and response.text else ""
        reply = _format_reply(raw, display_name)

        try:
            ChatMessage = apps.get_model('chatbot', 'ChatMessage')
            ChatMessage.objects.create(
                user=request.user,
                message=user_message or "사진 분석",
                response=reply,
            )
        except:
            pass

        return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)