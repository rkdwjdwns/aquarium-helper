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
from datetime import date, timedelta

# 모델 임포트
from .models import Tank, EventLog, DeviceControl, SensorReading

# --- [1. 메인 대시보드 및 리스트] ---

@login_required 
def index(request):
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10) 
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        if latest and latest.temperature is not None:
            try:
                target = float(tank.target_temp or 26.0)
                current = float(latest.temperature)
                if abs(current - target) >= 2.0: status = "DANGER"
            except: pass

        d_day = 7
        if tank.last_water_change:
            try:
                period = int(tank.water_change_period or 7)
                next_change = tank.last_water_change + timedelta(days=period)
                d_day = (next_change - date.today()).days
            except: pass
        
        tank_data.append({'tank': tank, 'latest': latest, 'status': status, 'd_day': d_day})
        
    return render(request, 'core/index.html', {'tank_data': tank_data, 'page_obj': page_obj, 'has_tanks': all_tanks.exists()})

@login_required
def dashboard(request, tank_id=None):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user) if tank_id else Tank.objects.filter(user=request.user).first()
    readings = tank.readings.all().order_by('-created_at')[:20] if tank else []
    return render(request, 'monitoring/dashboard.html', {'tank': tank, 'readings': readings})

@login_required
def tank_list(request):
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {'tanks': all_tanks, 'tank_count': all_tanks.count()})

# --- [2. 어항 관리 CRUD] ---

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
                    last_water_change=date.today()
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
        tank.name = request.POST.get('name', tank.name)
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
        Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, "일괄 삭제 완료.")
    return redirect('monitoring:tank_list')

# --- [3. 제어 및 로그] ---

@login_required
@require_POST
def toggle_device(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
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

@login_required
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    return render(request, 'monitoring/camera.html', {'tanks': Tank.objects.filter(user=request.user)})

# --- [4. AI 리포트] ---

@login_required
def ai_report_list(request):
    tanks = Tank.objects.filter(user=request.user).order_by('-id')
    selected_tank = get_object_or_404(Tank, id=request.GET.get('tank_id'), user=request.user) if request.GET.get('tank_id') else tanks.first()
    return render(request, 'reports/report_list.html', {'tanks': tanks, 'selected_tank': selected_tank})

@login_required
def download_report(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    content = f"[{tank.name}] 리포트\n날짜: {date.today()}\n온도: {tank.target_temp}°C"
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="report.txt"'
    return response

# --- [5. AI 챗봇 API: 초고속 & 초간결 최적화 버전] ---

@login_required
@require_POST
def chat_api(request):
    """AI 답변 속도와 가독성을 극대화한 버전"""
    try:
        if request.content_type == 'application/json':
            user_message = json.loads(request.body).get('message', '').strip()
            image_file = None
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')
        
        display_name = getattr(request.user, 'nickname', None) or request.user.username
        api_key = os.getenv('GEMINI_API_KEY_1') or getattr(settings, 'GEMINI_API_KEY', None)
        
        genai.configure(api_key=api_key)
        # 8b 모델은 응답 속도가 훨씬 빠릅니다.
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-8b")
        
        # AI가 딴소리 못하게 하는 강력한 지시문
        instruction = (
            f"Role: minimalist aquarium expert.\n"
            f"Format:\n"
            f"1. {display_name}님! 🌊\n"
            f"2. 🏠 [환경]: 수치 위주\n"
            f"3. 💧 [관리]: 방법 위주\n"
            f"4. ⚙️ [기기]: 상태 위주\n"
            f"5. 🍽️ [급여]: 횟수 위주\n"
            f"6. 즐거운 물생활 되세요! 🐠\n\n"
            f"Rule: No sentences. No '~입니다'. No '~요'. Only nouns and icons."
        )

        response = model.generate_content(
            [instruction, f"질문: {user_message}"],
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=100, # 길이를 짧게 제한해서 속도 향상
                temperature=0.0        # 일관되고 빠른 응답
            )
        )

        if response and response.text:
            # 줄바꿈 정리 및 마크다운 제거
            lines = [l.strip() for l in response.text.replace('**', '').split('\n') if l.strip()]
            
            # 파이썬 필터링: 문장형 어미(~다, ~요)가 포함된 줄은 삭제
            filtered = [l for l in lines if not any(l.endswith(e) for e in ['다.', '요.', '죠.'])]
            reply = '\n'.join(filtered[:8]) # 최대 8줄 제한

            # 결과가 너무 짧으면 기본 포맷 반환
            if len(reply) < 10:
                reply = f"{display_name}님! 🌊\n\n🏠 [환경]: 26°C / pH 7.0\n💧 [관리]: 주 1회 환수\n⚙️ [기기]: 여과기 가동\n🍽️ [급여]: 1일 1회\n\n즐거운 물생활 되세요! 🐠"

            try:
                ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                ChatMessage.objects.create(user=request.user, message=user_message or "사진", response=reply)
            except: pass
            
            return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})
            
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)