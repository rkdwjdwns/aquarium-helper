import json
import os
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

from .models import Tank, EventLog, DeviceControl, SensorReading


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


@login_required
def dashboard(request, tank_id=None):
    """특정 어항 상세 대시보드"""
    tank     = get_object_or_404(Tank, id=tank_id, user=request.user) if tank_id else Tank.objects.filter(user=request.user).first()
    readings = tank.readings.all().order_by('-created_at')[:20] if tank else []
    return render(request, 'monitoring/dashboard.html', {'tank': tank, 'readings': readings})


@login_required
def tank_list(request):
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
    logs      = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    paginator = Paginator(logs, 20)
    page_obj  = paginator.get_page(request.GET.get('page'))
    return render(request, 'monitoring/logs.html', {'page_obj': page_obj})


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
    return JsonResponse({'status': 'success', 'is_on': device.is_on})


@login_required
@require_POST
def perform_water_change(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    return JsonResponse({'status': 'success'})


# ──────────────────────────────────────────────
# [4] 리포트
# ──────────────────────────────────────────────

@login_required
def ai_report_list(request):
    """리포트 목록"""
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
    reports     = []

    if selected_tank:
        report_data = selected_tank.readings.all().order_by(order_by)
        try:
            ReportModel = apps.get_model('reports', 'Report')
            reports     = ReportModel.objects.filter(tank=selected_tank).order_by('-created_at')
        except:
            pass

    return render(request, 'reports/report_list.html', {
        'tanks':         tanks,
        'selected_tank': selected_tank,
        'report_data':   report_data,
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
            content += f"{r.created_at.strftime('%Y-%m-%d %H:%M')} : {r.temperature}°C\n"
    else:
        content += "데이터가 없습니다."

    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{tank.name}_{period}_report.txt"'
    return response


# ──────────────────────────────────────────────
# [5] AI 챗봇
# ──────────────────────────────────────────────

def _build_prompt(display_name: str, user_message: str) -> str:
    """
    챗봇 프롬프트 생성.
    - 반드시 5줄 이내, 줄바꿈으로 구분
    - 각 줄은 이모지 + 핵심 내용만
    - 긴 문장, 설명체 금지
    """
    return (
        f"너는 어항 관리 전문가 챗봇이야.\n"
        f"사용자 이름: {display_name}\n\n"
        f"[답변 규칙 - 반드시 지켜]\n"
        f"1. 전체 답변은 5줄을 절대 넘기지 마.\n"
        f"2. 각 줄은 이모지 하나로 시작해. 예) 🌡️ 수온: 25~27°C 유지\n"
        f"3. 줄마다 핵심 키워드와 수치만 써. 긴 설명 금지.\n"
        f"4. '~입니다', '~합니다', '~세요' 같은 존댓말 문장체 사용 금지.\n"
        f"5. 마지막 줄은 반드시 짧은 마무리 한 줄. 예) 🐠 즐거운 물생활!\n\n"
        f"질문: {user_message}"
    )


def _format_reply(raw: str, display_name: str) -> str:
    """
    AI 응답을 5줄 이내로 정제.
    빈 줄 제거 → 최대 5줄만 유지.
    """
    lines = [line.strip() for line in raw.replace('**', '').split('\n') if line.strip()]

    # 5줄 초과 시 자르기
    lines = lines[:5]

    reply = '\n'.join(lines)

    # 너무 짧거나 비어있으면 기본 응답
    if len(reply) < 10:
        reply = (
            f"🌊 {display_name}님 안녕하세요!\n"
            f"🌡️ 수온: 25~27°C\n"
            f"💧 환수: 주 1회 30%\n"
            f"⚙️ 여과기: 정상 가동 확인\n"
            f"🐠 즐거운 물생활!"
        )

    return reply


@login_required
@require_POST
def chat_api(request):
    try:
        # ── 요청 파싱 ──
        if request.content_type == 'application/json':
            user_message = json.loads(request.body).get('message', '').strip()
            image_file   = None
        else:
            user_message = request.POST.get('message', '').strip()
            image_file   = request.FILES.get('image')

        display_name = getattr(request.user, 'nickname', None) or request.user.username
        api_key      = os.getenv('GEMINI_API_KEY_1') or getattr(settings, 'GEMINI_API_KEY', None)

        # ── Gemini 설정 ──
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-8b")

        # ── 프롬프트 구성 ──
        prompt_parts = [_build_prompt(display_name, user_message)]

        if image_file:
            img = PIL.Image.open(image_file)
            img.thumbnail((512, 512))
            prompt_parts.append(img)

        # ── API 호출 ──
        response = model.generate_content(
            prompt_parts,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=150,  # 5줄 × 30자 기준
                temperature=0.3,        # 너무 창의적이면 규칙 무시하므로 낮게
            ),
        )

        # ── 응답 정제 ──
        raw   = response.text if response and response.text else ""
        reply = _format_reply(raw, display_name)

        # ── 채팅 기록 저장 ──
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
