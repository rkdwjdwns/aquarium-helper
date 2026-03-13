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
    """메인 페이지: 사용자 어항 목록 및 상태 요약"""
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
        
    return render(request, 'core/index.html', {
        'tank_data': tank_data, 
        'page_obj': page_obj, 
        'has_tanks': all_tanks.exists()
    })

@login_required
def dashboard(request, tank_id=None):
    """특정 어항 상세 대시보드"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user) if tank_id else Tank.objects.filter(user=request.user).first()
    readings = tank.readings.all().order_by('-created_at')[:20] if tank else []
    return render(request, 'monitoring/dashboard.html', {'tank': tank, 'readings': readings})

@login_required
def tank_list(request):
    """어항 관리 목록"""
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
    """단일 어항 삭제"""
    get_object_or_404(Tank, id=tank_id, user=request.user).delete()
    messages.success(request, "삭제 완료.")
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def delete_tanks(request):
    """선택된 여러 개의 어항을 한꺼번에 삭제"""
    tank_ids = request.POST.getlist('tank_ids')
    if tank_ids:
        deleted_count, _ = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"{deleted_count}개의 어항이 성공적으로 삭제되었습니다.")
    else:
        messages.warning(request, "삭제할 어항을 선택해주세요.")
    return redirect('monitoring:tank_list')

# --- [3. 제어, 로그 및 카메라] ---

@login_required
def logs_view(request):
    """어항 활동 로그 뷰"""
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    paginator = Paginator(logs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'monitoring/logs.html', {'page_obj': page_obj})

@login_required
def camera_view(request):
    """실시간 카메라 화면"""
    tank = Tank.objects.filter(user=request.user).first()
    return render(request, 'monitoring/camera.html', {'tank': tank, 'title': '실시간 모니터링'})

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

# --- [4. AI 리포트 관리 (정렬 로직 및 사용자 체크 최적화)] ---

@login_required
def ai_report_list(request):
    """리포트 목록: 현재 로그인 사용자의 어항 데이터를 강제 동기화"""
    # 현재 로그인한 유저의 어항만 가져옴
    tanks = Tank.objects.filter(user=request.user).order_by('-id')
    has_tanks = tanks.exists()
    
    tank_id = request.GET.get('tank_id')
    selected_tank = None
    
    if has_tanks:
        if tank_id:
            selected_tank = tanks.filter(id=tank_id).first()
        # 선택된 어항이 없거나 다른 유저의 ID인 경우 첫 번째 어항 선택
        if not selected_tank:
            selected_tank = tanks.first()

    sort_order = request.GET.get('sort', 'desc')
    order_by = '-created_at' if sort_order == 'desc' else 'created_at'

    report_data = []
    if selected_tank:
        report_data = selected_tank.readings.all().order_by(order_by)

    return render(request, 'reports/report_list.html', {
        'tanks': tanks,
        'selected_tank': selected_tank,
        'report_data': report_data,
        'sort': sort_order,
        'has_tanks': has_tanks 
    })

@login_required
@require_POST
def delete_report_data(request, reading_id):
    reading = get_object_or_404(SensorReading, id=reading_id, tank__user=request.user)
    tank_id = reading.tank.id
    reading.delete()
    messages.success(request, "기록이 삭제되었습니다.")
    return redirect(f'/monitoring/reports/?tank_id={tank_id}')

@login_required
def download_report(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    period = request.GET.get('period', 'daily')
    today = date.today()
    
    if period == 'weekly': start_date = today - timedelta(days=7)
    elif period == 'monthly': start_date = today - timedelta(days=30)
    else: start_date = today - timedelta(days=1)

    readings = tank.readings.filter(created_at__date__gte=start_date).order_by('-created_at')
    
    content = f"[{tank.name}] {period.upper()} 리포트\n기준일: {today}\n" + "="*30 + "\n"
    for r in readings:
        content += f"{r.created_at.strftime('%Y-%m-%d %H:%M')} : {r.temperature}°C\n"
    
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="{tank.name}_{period}.txt"'
    return response

# --- [5. AI 챗봇 API] ---

@login_required
@require_POST
def chat_api(request):
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
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-8b")
        
        prompt_parts = [
            f"Role: minimalist expert for {display_name}.\n"
            f"Rule: No sentences. No '~요', '~다'. Only nouns.\n"
            f"Format: 1. {display_name}님! 🌊 / 2. 🏠 [환경] / 3. 💧 [관리] / 4. ⚙️ [기기] / 5. 🍽️ [급여] / 6. 즐거운 물생활 되세요! 🐠"
        ]
        
        if image_file:
            img = PIL.Image.open(image_file)
            img.thumbnail((512, 512)) 
            prompt_parts.append(img)
            
        prompt_parts.append(f"질문: {user_message}")

        response = model.generate_content(
            prompt_parts,
            generation_config=genai.types.GenerationConfig(max_output_tokens=120, temperature=0.0)
        )

        if response and response.text:
            lines = [l.strip() for l in response.text.replace('**', '').split('\n') if l.strip()]
            reply = '\n'.join([l for l in lines if not any(l.endswith(e) for e in ['다.', '요.', '죠.'])][:8])
            
            if len(reply) < 15:
                reply = f"{display_name}님! 🌊\n\n🏠 [환경]: 26°C\n💧 [관리]: 환수 주기 확인\n⚙️ [기기]: 정상 가동\n🍽️ [급여]: 1일 1회\n\n즐거운 물생활 되세요! 🐠"

            try:
                ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                ChatMessage.objects.create(user=request.user, message=user_message or "사진 분석", response=reply)
            except: pass
            
            return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})
            
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)