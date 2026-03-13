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
    """리포트 다운로드"""
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

# --- [AI 챗봇 API: 정준님 최적화 가독성 엔진] ---

@login_required
@require_POST
def chat_api(request):
    """AI 챗봇 API: 조잡한 문장 제거, 섹션별 요약, 가독성 극대화"""
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()
            image_file = None
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')
        
        display_name = getattr(request.user, 'nickname', None) or request.user.username
        user_tanks = Tank.objects.filter(user=request.user)
        tank_info = ", ".join([f"{t.name}" for t in user_tanks]) if user_tanks.exists() else "정보 없음"

        api_keys = [os.getenv('GEMINI_API_KEY_1'), os.getenv('GEMINI_API_KEY_2'), getattr(settings, 'GEMINI_API_KEY', None)]
        valid_keys = [k for k in api_keys if k]
        
        for key in valid_keys:
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name="gemini-1.5-flash")
                
                # 가독성을 위한 명확한 구조 지시 (데이터 필드 위주)
                instruction = (
                    f"당신은 '어항 관리 전문가'입니다. 서술형 문장을 쓰지 말고 리스트로만 답하세요.\n\n"
                    f"포맷 가이드:\n"
                    f"1. 상단: '{display_name}님! 🌊'\n"
                    f"2. 섹션구분:\n"
                    f"🏠 [권장 환경]: 온도 24-26°C / pH 7.0 전후\n"
                    f"💧 [수질 관리]: 주 1회 30% 환수 필수\n"
                    f"⚙️ [기기 설정]: 여과기 24h / 조명 8-10h\n"
                    f"🍽️ [사료 급여]: 1일 1-2회 (소량)\n\n"
                    f"제약 사항:\n"
                    f"- 모든 줄은 불렛 포인트(*) 또는 아이콘으로 시작할 것.\n"
                    f"- '~입니다', '~추천합니다', '~알려드릴게요' 같은 조잡한 설명 절대 금지.\n"
                    f"- '아름다운 색상', '즐거움을 주는' 같은 감성 멘트 삭제.\n"
                    f"- 가독성을 위해 섹션 사이 한 줄 공백 유지.\n"
                    f"- 하단: '즐거운 물생활 되세요! 🐠'"
                )
                
                prompt_parts = [instruction, f"질문: {user_message}"]
                if image_file:
                    image_file.seek(0)
                    prompt_parts.insert(1, PIL.Image.open(image_file))

                response = model.generate_content(prompt_parts)
                if response and response.text:
                    # 마크다운 제거 및 줄 정리
                    reply = response.text.replace('**', '').strip()
                    
                    # 조잡한 문장이 포함된 줄(아이콘이나 불렛이 없는 긴 문장)은 파이썬에서 2차 필터링
                    lines = []
                    for line in reply.split('\n'):
                        line = line.strip()
                        if not line: # 공백 라인 허용
                            lines.append(line)
                            continue
                        # 아이콘이 있거나 불렛(*)으로 시작하는 핵심 데이터 라인만 유지
                        if any(icon in line for icon in ['🌊', '🏠', '💧', '⚙️', '🍽️', '🐠', '*', '●', '-']):
                            lines.append(line)
                    
                    final_reply = '\n'.join(lines[:12]) # 가독성을 위해 최대 12줄 제한

                    try:
                        ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                        ChatMessage.objects.create(user=request.user, message=user_message or "(사진)", response=final_reply)
                    except: pass
                    
                    return JsonResponse({'status': 'success', 'reply': final_reply, 'response': final_reply})
            except: continue
            
        return JsonResponse({'status': 'error', 'message': "연결 실패"}, status=500)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)