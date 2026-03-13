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

# --- [메인 대시보드 및 리스트] ---

@login_required 
def index(request):
    """메인 페이지: 사용자의 어항 목록 및 요약 상태"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

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
    """특정 어항 상세 모니터링 대시보드"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
    readings = tank.readings.all().order_by('-created_at')[:20] if tank else []
    return render(request, 'monitoring/dashboard.html', {'tank': tank, 'readings': readings})

@login_required
def tank_list(request):
    """어항 관리 목록 페이지"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {
        'tanks': all_tanks,
        'tank_count': all_tanks.count()
    })

# --- [어항 관리 CRUD] ---

@login_required
def add_tank(request):
    """어항 등록"""
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
            messages.success(request, f"'{tank.name}' 어항이 등록되었습니다.")
            return redirect('monitoring:tank_list') 
        except Exception as e:
            messages.error(request, f"등록 중 오류 발생: {e}")
            
    return render(request, 'monitoring/tank_form.html', {'title': '어항 등록'})

@login_required
def edit_tank(request, tank_id):
    """어항 수정"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        tank.name = request.POST.get('name', tank.name)
        tank.target_temp = float(request.POST.get('target_temp') or 26.0)
        tank.save()
        messages.success(request, "정보가 수정되었습니다.")
        return redirect('monitoring:tank_list')
    return render(request, 'monitoring/tank_form.html', {'tank': tank, 'title': '어항 수정'})

@login_required
def delete_tank(request, tank_id):
    """어항 삭제"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    messages.success(request, "어항이 삭제되었습니다.")
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def delete_tanks(request):
    """일괄 삭제"""
    tank_ids = request.POST.getlist('tank_ids')
    if tank_ids:
        deleted_count, _ = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"{deleted_count}개의 어항이 삭제되었습니다.")
    return redirect('monitoring:tank_list')

# --- [제어 및 로그] ---

@login_required
@require_POST
def toggle_device(request, tank_id):
    """장치 토글 제어"""
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    """환수 기록"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    return JsonResponse({'status': 'success'})

@login_required
def logs_view(request):
    """로그 보기"""
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    """카메라 뷰"""
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'monitoring/camera.html', {'tanks': tanks})

# --- [AI 및 리포트] ---

@login_required
def ai_report_list(request):
    """AI 리포트 목록"""
    tanks = Tank.objects.filter(user=request.user).order_by('-id')
    selected_tank_id = request.GET.get('tank_id')
    selected_tank = None
    
    if selected_tank_id:
        selected_tank = get_object_or_404(Tank, id=selected_tank_id, user=request.user)
    elif tanks.exists():
        selected_tank = tanks.first()

    return render(request, 'reports/report_list.html', {
        'tanks': tanks,
        'selected_tank': selected_tank
    })

@login_required
def download_report(request, tank_id):
    """리포트 다운로드 - 에러 해결을 위해 다시 추가됨"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    readings = tank.readings.all().order_by('-created_at')[:10]
    
    content = f"--- {tank.name} AI 관리 리포트 ---\n"
    content += f"생성 일자: {date.today()}\n"
    content += f"목표 온도: {tank.target_temp}도\n\n"
    content += "[최근 수질 기록]\n"
    for r in readings:
        content += f"- {r.created_at.strftime('%Y-%m-%d %H:%M')}: 수온 {r.temperature}도\n"
    
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="{tank.name}_report.txt"'
    return response

# --- [AI 챗봇 API: 정준님 최적화 엔진] ---

@login_required
@require_POST
def chat_api(request):
    """AI 챗봇 API: 불필요한 설명 제거 및 10줄 이내 요약"""
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()
            image_file = None
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')
        
        user_tanks = Tank.objects.filter(user=request.user)
        tank_info = ", ".join([f"{t.name}" for t in user_tanks]) if user_tanks.exists() else "없음"
        display_name = getattr(request.user, 'nickname', None) or request.user.username

        api_keys = [os.getenv('GEMINI_API_KEY_1'), os.getenv('GEMINI_API_KEY_2'), getattr(settings, 'GEMINI_API_KEY', None)]
        valid_keys = [k for k in api_keys if k]
        
        for key in valid_keys:
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name="gemini-1.5-flash")
                
                instruction = (
                    f"당신은 '데이터 추출 기계'입니다. 인간처럼 대화하지 마십시오.\n\n"
                    f"1. 첫 줄: '{display_name}님! 🌊' (이외 인사 절대 금지)\n"
                    f"2. 본문: 반드시 아래 템플릿의 '수치'만 채워서 10줄 이내로 출력하십시오.\n"
                    f"🏠 [권장 수치] Temp: 24~26°C / pH: 6.5~7.5 / 탁도: 80%↑\n"
                    f"💧 [수질 관리] 환수: 주 1회 30% / 사이펀 수동 청소\n"
                    f"⚙️ [기기 설정] 여과기: 24시간(상시) / 조명: 8~10시간(자동/수동)\n"
                    f"🍽️ [먹이 주기] 횟수: 1일 1~2회 (2분 내 소진량)\n\n"
                    f"3. 절대 금지:\n"
                    f"   - '~군요', '~입니다', '추천합니다' 등 모든 문장 어미 금지.\n"
                    f"   - 서술형 설명, 환영 인사, 보충 설명 절대 금지.\n"
                    f"   - 줄바꿈을 포함하여 전체 10줄을 넘기지 말 것.\n"
                    f"4. 마지막 줄: '즐거운 물생활 되세요! 🐠'\n\n"
                    f"정보: {tank_info}"
                )
                
                prompt_parts = [instruction, user_message]
                if image_file:
                    image_file.seek(0)
                    prompt_parts.insert(1, PIL.Image.open(image_file))

                response = model.generate_content(prompt_parts)
                if response and response.text:
                    raw_text = response.text.replace('**', '').replace('### ', '').replace('## ', '').strip()
                    
                    filtered_lines = []
                    for line in raw_text.split('\n'):
                        line = line.strip()
                        if any(mark in line for mark in ['🌊', '🏠', '💧', '⚙️', '🍽️', '●', '🐠', 'Temp', 'pH']):
                            filtered_lines.append(line)
                    
                    reply = '\n'.join(filtered_lines[:10])
                    
                    try:
                        ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                        ChatMessage.objects.create(user=request.user, message=user_message or "(사진)", response=reply)
                    except: pass
                    return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})
            except: continue
            
        return JsonResponse({'status': 'error', 'message': "연결 실패"}, status=500)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)