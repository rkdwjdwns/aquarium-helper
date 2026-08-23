import json
import os
import re
import PIL.Image
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.core.paginator import Paginator
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from django.db import transaction
from django.utils import timezone
from datetime import date, timedelta
from collections import defaultdict

from .models import Tank, EventLog, DeviceControl, SensorReading, FishBehavior


@login_required
def index(request):
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10)
    page_obj  = paginator.get_page(request.GET.get('page'))
    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        if latest and latest.temperature is not None:
            try:
                if abs(float(latest.temperature) - float(tank.target_temp or 26.0)) >= 2.0:
                    status = "DANGER"
            except: pass
        d_day = 7
        if tank.last_water_change:
            try:
                next_change = tank.last_water_change + timedelta(days=int(tank.water_change_period or 7))
                d_day = (next_change - date.today()).days
            except: pass
        tank_data.append({'tank': tank, 'latest': latest, 'status': status, 'd_day': d_day})
    return render(request, 'core/index.html', {
        'tank_data': tank_data, 'page_obj': page_obj, 'has_tanks': all_tanks.exists()
    })


def _get_chart_history(tank):
    if not tank:
        return json.dumps({})
    readings = list(SensorReading.objects.filter(tank=tank).order_by('-created_at')[:12])
    readings.reverse()
    return json.dumps({
        "labels": [r.created_at.strftime("%H:%M") for r in readings],
        "temp":   [r.temperature         for r in readings],
        "ph":     [r.ph                  for r in readings],
        "do":     [r.dissolved_oxygen   for r in readings],
        "turb":   [r.turbidity          for r in readings],
    }, ensure_ascii=False)


def _get_growth_chart(tank):
    """물고기별(fish_id) 성장 추이 — 최대 3개 라인"""
    if not tank:
        return json.dumps({})
    from .models import GrowthRecord

    records = list(
        GrowthRecord.objects.filter(tank=tank)
        .order_by('created_at')
        .values('fish_id', 'estimated_length', 'created_at')
    )[-42:]  # 최근 42개 (3마리 × 14일치)

    if not records:
        return json.dumps({})

    date_fish = defaultdict(dict)
    for r in records:
        date_str = r['created_at'].strftime("%m/%d")
        fid      = r['fish_id']
        date_fish[date_str][fid] = round(float(r['estimated_length'] or 0), 2)

    labels   = sorted(date_fish.keys())
    fish_ids = sorted({r['fish_id'] for r in records})
    colors   = ['#3b82f6', '#10b981', '#f59e0b']  # 파랑, 초록, 노랑

    datasets = []
    for i, fid in enumerate(fish_ids):
        datasets.append({
            'label': f'금붕어 {fid}호',
            'data':  [date_fish[d].get(fid) for d in labels],
            'color': colors[i % len(colors)],
        })

    return json.dumps({'labels': labels, 'datasets': datasets}, ensure_ascii=False)


def _get_feeding_chart(tank):
    if not tank:
        return json.dumps({"labels": [], "amounts": []})
    from .models import FeedingEvent
    from django.db.models import Sum
    import datetime as dt
    today = timezone.now().date()
    labels, amounts = [], []
    for i in range(6, -1, -1):
        day   = today - dt.timedelta(days=i)
        total = FeedingEvent.objects.filter(
            tank=tank, created_at__date=day
        ).aggregate(total=Sum('amount_g'))['total'] or 0.0
        labels.append(day.strftime("%m/%d"))
        amounts.append(round(total, 3))
    return json.dumps({"labels": labels, "amounts": amounts}, ensure_ascii=False)


@login_required
def dashboard(request, tank_id=None):
    user_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    tank = None
    if tank_id:
        try:
            tank = user_tanks.filter(id=int(tank_id)).first()
        except (ValueError, TypeError):
            tank = None
    if not tank:
        tank = user_tanks.first()

    if not tank:
        return render(request, 'monitoring/dashboard.html', {'tank': None, 'user_tanks': user_tanks})

    latest             = tank.readings.order_by('-created_at').first()
    latest_behavior = tank.behaviors.order_by('-created_at').first() if hasattr(tank, 'behaviors') else None
    devices         = {d.type: d for d in DeviceControl.objects.filter(tank=tank)}
    logs            = EventLog.objects.filter(tank=tank).order_by('-created_at')[:3]

    d_day = 7
    if tank.last_water_change:
        try:
            next_change = tank.last_water_change + timedelta(days=int(tank.water_change_period or 7))
            d_day = (next_change - date.today()).days
        except: pass

    return render(request, 'monitoring/dashboard.html', {
        'tank': tank, 'latest': latest, 'latest_behavior': latest_behavior,
        'devices': devices, 'logs': logs, 'd_day': d_day,
        'is_water_changed_today': (tank.last_water_change == date.today()),
        'user_tanks':     user_tanks,
        'chart_history': _get_chart_history(tank),
        'growth_chart':  _get_growth_chart(tank),
        'feeding_chart': _get_feeding_chart(tank),
        'heater_on':   devices.get('HEATER',   None) and devices['HEATER'].is_on,
        'cooling_on':  devices.get('COOLING',  None) and devices['COOLING'].is_on,
        'filter_on':   devices.get('FILTER',   None) and devices['FILTER'].is_on,
        'air_pump_on': devices.get('AIR_PUMP', None) and devices['AIR_PUMP'].is_on,
        'feeder_on':   devices.get('FEEDER',   None) and devices['FEEDER'].is_on,
        'light_on':    devices.get('LIGHT',    None) and devices['LIGHT'].is_on,
    })


@login_required
def dashboard_data(request, tank_id):
    tank     = get_object_or_404(Tank, id=tank_id, user=request.user)
    latest   = SensorReading.objects.filter(tank=tank).order_by('-created_at').first()
    readings = list(SensorReading.objects.filter(tank=tank).order_by('-created_at')[:12])
    readings.reverse()
    sensor = None
    if latest:
        sensor = {
            "temperature":       latest.temperature,
            "ph":                latest.ph,
            "dissolved_oxygen":  latest.dissolved_oxygen,
            "turbidity":         latest.turbidity,
            "water_level":       latest.water_level,
        }
    history = {
        "labels": [r.created_at.strftime("%H:%M") for r in readings],
        "temp":   [r.temperature      for r in readings],
        "ph":     [r.ph               for r in readings],
        "do":     [r.dissolved_oxygen for r in readings],
        "turb":   [r.turbidity        for r in readings],
    }
    return JsonResponse({"sensor": sensor, "history": history})


@login_required
def tank_settings(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        try:
            tank.temp_min         = float(request.POST.get('temp_min',        21.0))
            tank.temp_max         = float(request.POST.get('temp_max',        24.0))
            tank.ph_min           = float(request.POST.get('ph_min',            6.5))
            tank.ph_max           = float(request.POST.get('ph_max',            8.0))
            tank.do_min           = float(request.POST.get('do_min',            5.0))
            tank.turbidity_max    = float(request.POST.get('turbidity_max',    50.0))
            tank.heater_on_temp   = float(request.POST.get('heater_on_temp',   21.0))
            tank.heater_off_temp  = float(request.POST.get('heater_off_temp',  22.0))
            tank.cooling_on_temp  = float(request.POST.get('cooling_on_temp',  24.0))
            tank.cooling_off_temp = float(request.POST.get('cooling_off_temp', 23.0))
            tank.filter_on_ntu    = float(request.POST.get('filter_on_ntu',    50.0))
            tank.filter_off_ntu   = float(request.POST.get('filter_off_ntu',   20.0))
            tank.airpump_on_do    = float(request.POST.get('airpump_on_do',     4.0))
            tank.airpump_off_do   = float(request.POST.get('airpump_off_do',    6.0))
            tank.feeding_times    = request.POST.get('feeding_times', '08:00,18:00')
            tank.feeding_amount_g = float(request.POST.get('feeding_amount_g', 0.1))
            tank.feeding_auto     = request.POST.get('feeding_auto') == 'on'
            tank.light_on_hour    = int(request.POST.get('light_on_hour',  8))
            tank.light_off_hour   = int(request.POST.get('light_off_hour', 20))
            tank.light_auto       = request.POST.get('light_auto') == 'on'
            tank.save()
            messages.success(request, "설정이 저장되었습니다.")
            return redirect('monitoring:tank_settings', tank_id=tank.id)
        except Exception as e:
            messages.error(request, f"저장 실패: {e}")
    return render(request, 'monitoring/tank_settings.html', {'tank': tank})


def tank_settings_api(request, tank_id):
    server_key = os.getenv('PI_API_KEY', '')
    client_key = request.headers.get('X-API-KEY', '')
    if server_key and client_key != server_key:
        return JsonResponse({'error': '인증 실패'}, status=401)
    try:
        tank = Tank.objects.get(id=tank_id)
    except Tank.DoesNotExist:
        return JsonResponse({'error': '어항 없음'}, status=404)
    return JsonResponse({
        'water':   {'temp_min': tank.temp_min, 'temp_max': tank.temp_max, 'ph_min': tank.ph_min, 'ph_max': tank.ph_max, 'do_min': tank.do_min, 'turbidity_max': tank.turbidity_max},
        'devices': {'heater_on': tank.heater_on_temp, 'heater_off': tank.heater_off_temp, 'cooling_on': tank.cooling_on_temp, 'cooling_off': tank.cooling_off_temp, 'filter_on': tank.filter_on_ntu, 'filter_off': tank.filter_off_ntu, 'airpump_on': tank.airpump_on_do, 'airpump_off': tank.airpump_off_do},
        'feeding': {'times': tank.feeding_times.split(','), 'amount_g': tank.feeding_amount_g, 'auto': tank.feeding_auto},
        'light':   {'on_hour': tank.light_on_hour, 'off_hour': tank.light_off_hour, 'auto': tank.light_auto},
    })


@login_required
def tank_list(request):
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {'tanks': all_tanks, 'tank_count': all_tanks.count()})


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
        tank.name       = request.POST.get('name', tank.name)
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
        messages.success(request, f"{deleted_count}개의 어항이 삭제되었습니다.")
    else:
        messages.warning(request, "삭제할 어항을 선택해주세요.")
    return redirect('monitoring:tank_list')


@login_required
def logs_view(request):
    tank_id    = request.GET.get('tank_id')
    level      = request.GET.get('level')
    user_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    if tank_id: logs = logs.filter(tank_id=tank_id)
    if level:   logs = logs.filter(level=level)
    paginator = Paginator(logs, 20)
    page_obj  = paginator.get_page(request.GET.get('page'))
    return render(request, 'monitoring/logs.html', {
        'page_obj': page_obj, 'user_tanks': user_tanks, 'tank_id': tank_id, 'level': level
    })


@login_required
def camera_view(request):
    try:
        tank_id = request.GET.get('tank_id')
        user_tanks = Tank.objects.filter(user=request.user).order_by('-id')
        tank = None
        if tank_id:
            try:
                tank = user_tanks.filter(id=int(tank_id)).first()
            except (ValueError, TypeError):
                tank = None
        if not tank:
            tank = user_tanks.first()
            
        return render(request, 'monitoring/camera.html', {'tank': tank, 'user_tanks': user_tanks, 'title': '실시간 모니터링'})
    except Exception as e:
        return HttpResponse(f"Camera View Error: {e}", status=500)


@login_required
@require_POST
def toggle_device(request, tank_id):
    tank        = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=request.POST.get('device_type'))
    device.is_on = not device.is_on
    device.save()
    EventLog.objects.create(
        tank=tank, level='INFO',
        message=f"[수동제어] {device.get_type_display()} {'ON' if device.is_on else 'OFF'}"
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


@login_required
def ai_report_list(request):
    tanks         = Tank.objects.filter(user=request.user).order_by('-id')
    has_tanks     = tanks.exists()
    tank_id       = request.GET.get('tank_id')
    selected_tank = None
    if has_tanks:
        if tank_id:
            try:
                selected_tank = tanks.filter(id=int(tank_id)).first()
            except (ValueError, TypeError):
                selected_tank = None
        if not selected_tank: selected_tank = tanks.first()
    sort_order  = request.GET.get('sort', 'desc')
    order_by    = '-created_at' if sort_order == 'desc' else 'created_at'
    report_data = []
    behaviors   = []
    reports     = []
    if selected_tank:
        report_data = selected_tank.readings.all().order_by(order_by)[:200]
        behaviors   = selected_tank.behaviors.all().order_by(order_by)[:10] if hasattr(selected_tank, 'behaviors') else []
        try:
            ReportModel = apps.get_model('reports', 'Report')
            reports     = ReportModel.objects.filter(tank=selected_tank).order_by('-created_at')
        except: pass
    return render(request, 'reports/report_list.html', {
        'tanks': tanks, 'selected_tank': selected_tank,
        'report_data': report_data, 'behaviors': behaviors,
        'reports': reports, 'sort': sort_order, 'has_tanks': has_tanks,
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
    if period == 'weekly':    start_date = today - timedelta(days=7)
    elif period == 'monthly': start_date = today - timedelta(days=30)
    else:                     start_date = today - timedelta(days=1)
    readings = tank.readings.filter(created_at__gte=start_date).order_by('-created_at')
    content  = f"[{tank.name}] {period.upper()} 분석 기록\n기준일: {today.strftime('%Y-%m-%d')}\n" + "=" * 40 + "\n"
    if readings.exists():
        for r in readings:
            content += f"{r.created_at.strftime('%Y-%m-%d %H:%M')} | 수온:{r.temperature}°C | pH:{r.ph} | DO:{r.dissolved_oxygen}mg/L | 탁도:{r.turbidity}NTU | 수질점수:{r.water_quality_score}\n"
    else:
        content += "데이터가 없습니다."
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{tank.name}_{period}_report.txt"'
    return response


def _build_prompt(display_name: str, user_message: str) -> str:
    return f"""너는 어항 관리 전문 도우미야. 질문 유형에 맞게 답해.

[말투 규칙]
- 존댓말 사용, 문장은 짧고 핵심만
- 이모지 사용 금지
- 인사말 금지
- 문장 중간에 끊지 말고 완성된 문장으로 마무리

[답변 형식]
1. 물고기 추천: 2~3종, 각각 물고기명 / 특징 한 문장 / 수온·pH·난이도
2. 수질/센서: 수온·pH·DO·탁도 수치 항목별
3. 어항 세팅: 핵심 순서 3~5줄
4. 관리/질병: 원인 + 해결책
5. 기타: 핵심만 3~5줄

질문: {user_message}"""


def _clean_reply(raw: str) -> str:
    raw = raw.replace('**', '').replace('##', '').replace('# ', '').strip()
    cleaned = []
    for ch in raw:
        cp = ord(ch)
        if 0x1F300 <= cp <= 0x1FAFF: continue
        if 0x2600 <= cp <= 0x27BF:   continue
        if 0x1F000 <= cp <= 0x1F02F: continue
        cleaned.append(ch)
    raw    = ''.join(cleaned).strip()
    lines  = raw.split('\n')
    result = []
    prev_blank = False
    for line in lines:
        if line.strip() == '':
            if not prev_blank: result.append('')
            prev_blank = True
        else:
            result.append(line.rstrip())
            prev_blank = False
    return '\n'.join(result).strip()


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
        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        prompt_parts = [_build_prompt(display_name, user_message)]
        if image_file:
            img = PIL.Image.open(image_file)
            img.thumbnail((512, 512))
            prompt_parts.append(img)
        response = model.generate_content(
            prompt_parts,
            generation_config=genai.types.GenerationConfig(max_output_tokens=1024, temperature=0.4),
            request_options={"timeout": 20},
        )
        raw   = response.text if response and response.text else ""
        reply = _clean_reply(raw)
        try:
            ChatMessage = apps.get_model('chatbot', 'ChatMessage')
            ChatMessage.objects.create(user=request.user, message=user_message or "사진 분석", response=reply)
        except: pass
        return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def fish_data_view(request):
    """물고기 개체 데이터 페이지"""
    try:
        tank_id    = request.GET.get('tank_id')
        user_tanks = Tank.objects.filter(user=request.user).order_by('-id')
        tank       = None
        
        if tank_id:
            try:
                tank = user_tanks.filter(id=int(tank_id)).first()
            except (ValueError, TypeError):
                tank = None
                
        if not tank:
            tank = user_tanks.first()
            
        return render(request, 'monitoring/fish_data.html', {
            'tank': tank,
            'user_tanks': user_tanks,
        })
    except Exception as e:
        return HttpResponse(f"Fish Data View Error: {e}", status=500)


@login_required
def analysis_view(request):
    """AI 행동분석 페이지"""
    tank_id    = request.GET.get('tank_id')
    user_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    tank = None
    if tank_id:
        try:
            tank = user_tanks.filter(id=int(tank_id)).first()
        except (ValueError, TypeError):
            tank = None
    if not tank:
        tank = user_tanks.first()
    return render(request, 'monitoring/analysis.html', {
        'tank': tank, 'user_tanks': user_tanks,
    })


@login_required
def data_log_view(request):
    """데이터 로그 페이지 (EventLog 전체 조회)"""
    tank_id             = request.GET.get('tank_id')
    level               = request.GET.get('level', '')
    sort                = request.GET.get('sort', 'desc')
    user_tanks          = Tank.objects.filter(user=request.user).order_by('-id')
    selected_tank = None
    if tank_id:
        try:
            selected_tank = user_tanks.filter(id=int(tank_id)).first()
        except (ValueError, TypeError):
            selected_tank = None
    if not selected_tank:
        selected_tank = user_tanks.first()

    order_by = '-created_at' if sort != 'asc' else 'created_at'
    logs = EventLog.objects.filter(tank__user=request.user).order_by(order_by)
    if selected_tank:
        logs = logs.filter(tank=selected_tank)
    if level:
        logs = logs.filter(level=level)

    paginator = Paginator(logs, 20)
    page_obj  = paginator.get_page(request.GET.get('page'))

    return render(request, 'monitoring/data_log.html', {
        'page_obj':      page_obj,
        'user_tanks':    user_tanks,
        'selected_tank': selected_tank,
        'level':         level,
        'sort':          sort,
    })


@login_required
def video_feed(request, tank_id=None):
    """실시간 카메라 스트리밍 뷰"""
    try:
        return StreamingHttpResponse(
            gen_camera_frame(), 
            content_type='multipart/x-mixed-replace; boundary=frame'
        )
    except Exception as e:
        return HttpResponse(f"Streaming Error: {e}", status=500)def video_feed(request):
    """실시간 카메라 스트리밍 뷰"""
    try:
        return StreamingHttpResponse(
            gen_camera_frame(), 
            content_type='multipart/x-mixed-replace; boundary=frame'
        )
    except Exception as e:
        return HttpResponse(f"Streaming Error: {e}", status=500)

def gen_camera_frame():
    while True:
        frame = b''
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')