import json
import os
import PIL.Image
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from datetime import date, timedelta

# 모델 임포트 (monitoring 앱 내의 모델)
from monitoring.models import Tank, EventLog, DeviceControl, SensorReading

# --- [메인 페이지 및 대시보드] ---

def home(request):
    """로그인 상태에 따라 홈 또는 인덱스 페이지 표시"""
    if request.user.is_authenticated:
        return index(request)
    return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

@login_required 
def index(request):
    """메인 페이지: 사용자의 어항 목록 및 요약 상태 (실시간 반영)"""
    # 항상 DB에서 최신 순으로 조회하여 삭제/수정 데이터 즉시 반영
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
        'has_tanks': all_tanks.exists(),
        'is_guest': False
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

# --- [어항 관리 기능] ---

@login_required
def tank_list(request):
    """어항 관리 목록 페이지"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {'tanks': all_tanks})

@login_required
def add_tank(request):
    """어항 등록 후 즉시 반영"""
    if request.method == 'POST':
        try:
            tank = Tank.objects.create(
                user=request.user,
                name=request.POST.get('name', '새 어항'),
                target_temp=float(request.POST.get('target_temp') or 26.0),
                water_change_period=int(request.POST.get('water_change_period') or 7),
                last_water_change=date.today()
            )
            messages.success(request, f"'{tank.name}' 어항이 등록되었습니다.")
            return redirect('/') 
        except Exception as e:
            messages.error(request, f"등록 중 오류 발생: {e}")
            
    return render(request, 'monitoring/tank_form.html', {'title': '어항 등록'})

@login_required
def edit_tank(request, tank_id):
    """수정 후 메인으로 리다이렉트"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        tank.name = request.POST.get('name', tank.name)
        tank.target_temp = float(request.POST.get('target_temp') or 26.0)
        tank.save()
        messages.success(request, "정보가 수정되었습니다.")
        return redirect('/')
    return render(request, 'monitoring/tank_form.html', {'tank': tank, 'title': '어항 수정'})

@login_required
def delete_tank(request, tank_id):
    """삭제 후 메인으로 리다이렉트"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    messages.success(request, "어항이 삭제되었습니다.")
    return redirect('/')

@login_required
@require_POST
def delete_tanks(request):
    """일괄 삭제 후 메인으로 리다이렉트"""
    tank_ids = request.POST.getlist('tank_ids')
    if tank_ids:
        deleted_count, _ = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"{deleted_count}개의 어항이 삭제되었습니다.")
    return redirect('/')

# --- [장치 제어 및 로그] ---

@login_required
@require_POST
def toggle_device(request, tank_id):
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
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
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'monitoring/camera.html', {'tanks': tanks})

# --- [AI 및 챗봇] ---

def get_chat_message_model():
    try:
        return apps.get_model('chatbot', 'ChatMessage')
    except (LookupError, ValueError):
        return None

@login_required
@require_POST
def chat_api(request):
    """AI 챗봇 API: 최신 모델 자동 탐색 및 정준님 스타일 반영"""
    try:
        user_message = ""
        image_file = None

        if request.content_type == 'application/json':
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')
        
        # 실시간 어항 데이터 주입
        user_tanks = Tank.objects.filter(user=request.user)
        tank_info = ", ".join([f"{t.name}" for t in user_tanks]) if user_tanks.exists() else "등록된 어항 없음"
        display_name = getattr(request.user, 'nickname', None) or request.user.username

        # API 키 준비
        api_keys = [
            os.getenv('GEMINI_API_KEY_1'), 
            os.getenv('GEMINI_API_KEY_2'), 
            os.getenv('GEMINI_API_KEY_3'),
            getattr(settings, 'GEMINI_API_KEY', None)
        ]
        valid_keys = [k for k in api_keys if k]

        if not valid_keys:
            return JsonResponse({'status': 'error', 'message': "사용 가능한 API 키가 없습니다."}, status=500)

        last_exception = None
        for key in valid_keys:
            try:
                genai.configure(api_key=key)
                
                # [수정] 2026년 가용 모델 자동 탐색
                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                
                selected_model = None
                candidates = ["models/gemini-2.5-flash", "models/gemini-2.0-flash", "models/gemini-1.5-flash", "models/gemini-flash-latest"]
                for cand in candidates:
                    if cand in available_models:
                        selected_model = cand
                        break
                
                if not selected_model and available_models:
                    selected_model = available_models[0]
                
                if not selected_model: continue

                model = genai.GenerativeModel(model_name=selected_model)
                
                # [프롬프트] 스타일 및 사육 가이드 강제
                instruction = (
                    f"당신은 친절한 어항 전문가 '어항 도우미'입니다.\n"
                    f"사용자: {display_name}님 / 보유 어항: {tank_info}\n\n"
                    f"답변 규칙:\n"
                    f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                    f"2. 별표(*), 샵(#), 대시(-) 등 특수기호 절대 사용 금지.\n"
                    f"3. 모든 구분은 줄바꿈(엔터)으로만 할 것.\n"
                    f"4. 중요 제목은 [제목] 처럼 대괄호를 사용하고 문단 사이 빈 줄을 넣을 것.\n"
                    f"5. 사육 질문 시 반드시 [수동 설정 추천]과 [자동 설정 추천] 섹션을 나누어 상세히 말할 것."
                )
                
                prompt_parts = [instruction, user_message]
                if image_file:
                    image_file.seek(0)
                    prompt_parts.insert(1, PIL.Image.open(image_file))

                response = model.generate_content(prompt_parts)
                
                if response and response.text:
                    # 기호 최종 제거
                    reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()
                    
                    # 로그 저장
                    ChatMessage = get_chat_message_model()
                    if ChatMessage:
                        ChatMessage.objects.create(user=request.user, message=user_message or "(사진)", response=reply)
                    
                    return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})

            except Exception as e:
                last_exception = e
                continue

        return JsonResponse({'status': 'error', 'message': f"연결 실패: {str(last_exception)}"}, status=500)
        
    except Exception as general_e:
        return JsonResponse({'status': 'error', 'message': f"시스템 오류: {str(general_e)}"}, status=500)