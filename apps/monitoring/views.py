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

# 모델 임포트
from .models import Tank, EventLog, DeviceControl

# 1. 메인 홈 뷰 (데이터 전달 추가)
def home(request):
    """로그인 안했을 때는 홈, 했을 때는 어항 목록(index)으로 연결"""
    if request.user.is_authenticated:
        return index(request)
    return render(request, 'core/index.html', {'tank_data': []})

# 2. ChatMessage 모델 안전하게 가져오기
def get_chat_message_model():
    try:
        return apps.get_model('chatbot', 'ChatMessage')
    except (LookupError, ValueError):
        try:
            return apps.get_model('apps.chatbot', 'ChatMessage')
        except:
            return None

# --- [메인 기능: 대시보드 및 리스트] ---

@login_required 
def index(request):
    """메인 페이지: 어항 카드 목록 (데이터 누락 방지 보완)"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    
    # 페이지네이션: 한 페이지에 10개로 늘려 데이터가 안보이는 현상 방지
    paginator = Paginator(all_tanks, 10) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    tank_data = []
    for tank in page_obj:
        # 최신 수질 데이터
        latest = tank.readings.order_by('-created_at').first()
        
        # 상태 체크 로직
        status = "NORMAL"
        if latest and latest.temperature is not None:
            try:
                target = float(tank.target_temp or 26.0)
                current = float(latest.temperature)
                if abs(current - target) >= 2.0: 
                    status = "DANGER"
            except: pass

        # 환수 D-Day 계산
        d_day = 7
        if tank.last_water_change:
            try:
                period = int(tank.water_change_period or 7)
                next_change = tank.last_water_change + timedelta(days=period)
                d_day = (next_change - date.today()).days
            except: pass
        
        tank_data.append({
            'tank': tank, 
            'latest': latest, 
            'status': status, 
            'd_day': d_day
        })
        
    return render(request, 'core/index.html', {
        'tank_data': tank_data, 
        'page_obj': page_obj,
        'has_tanks': all_tanks.exists()
    })

# --- [챗봇 기능: API 키 순환 및 닉네임 적용] ---

@login_required
@require_POST
def chat_api(request):
    """텍스트 + 이미지 분석 지원 챗봇"""
    # JSON 요청과 POST 요청 모두 대응
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()
        except: user_message = ""
    else:
        user_message = request.POST.get('message', '').strip()
    
    image_file = request.FILES.get('image') 
    
    if not user_message and not image_file:
        return JsonResponse({'status': 'error', 'message': "궁금한 점을 입력해 주세요! 🌊"}, status=400)
    
    # 닉네임 설정
    display_name = getattr(request.user, 'nickname', None) or request.user.username
    
    # API 키 리스트 (settings.py에 통합된 키 우선 사용)
    api_keys = [
        getattr(settings, 'GEMINI_API_KEY', None),
        getattr(settings, 'GEMINI_API_KEY_1', None),
        getattr(settings, 'GEMINI_API_KEY_2', None),
        getattr(settings, 'GEMINI_API_KEY_3', None),
    ]
    valid_keys = [k for k in api_keys if k]
    
    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "API 키가 설정되지 않았습니다."}, status=500)

    for current_key in valid_keys:
        try:
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=(
                    f"당신은 '어항 도우미'입니다.\n"
                    f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                    f"2. 특수 기호(*, #, -) 절대 사용 금지.\n"
                    f"3. 아주 쉽고 짧게 핵심만 말할 것.\n"
                    f"4. 줄바꿈을 아주 자주 할 것.\n"
                    f"5. 마지막에 [SETTING: temp=온도, ph=수치, cycle=환수주기] 포함."
                )
            )
            
            content = []
            if user_message: content.append(user_message)
            if image_file: content.append(PIL.Image.open(image_file))
            
            response = model.generate_content(content)
            bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
            
            # 대화 내역 저장
            ChatMessage = get_chat_message_model()
            if ChatMessage:
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message if user_message else "사진 분석 요청 📸", 
                    response=bot_response
                )
            
            return JsonResponse({'status': 'success', 'reply': bot_response, 'message': bot_response})
            
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                continue # 다음 키로 시도
            return JsonResponse({'status': 'error', 'message': f"분석 중 오류 발생: {str(e)}"}, status=500)

    return JsonResponse({'status': 'error', 'message': "모든 API 키가 만료되었습니다. 잠시 후 시도해 주세요."}, status=500)

# --- [어항 관리 기능] ---

@login_required
def tank_list(request):
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {'tanks': all_tanks})

@login_required
def add_tank(request):
    if request.method == 'POST':
        try:
            tank = Tank.objects.create(
                user=request.user,
                name=request.POST.get('name', '새 어항') or '새 어항',
                fish_species=request.POST.get('fish_species', ''),
                target_temp=float(request.POST.get('target_temp') or 26.0),
                water_change_period=int(request.POST.get('water_change_period') or 7),
                last_water_change=date.today()
            )
            messages.success(request, f"'{tank.name}' 어항이 등록되었습니다.")
            return redirect('monitoring:index')
        except Exception as e:
            return render(request, 'monitoring/tank_form.html', {'error': str(e), 'title': '어항 등록'})
    return render(request, 'monitoring/tank_form.html', {'title': '어항 등록'})

@login_required
def edit_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        tank.name = request.POST.get('name', tank.name)
        tank.fish_species = request.POST.get('fish_species', tank.fish_species)
        tank.target_temp = float(request.POST.get('target_temp') or 26.0)
        tank.water_change_period = int(request.POST.get('water_change_period') or 7)
        tank.save()
        messages.success(request, "정보가 수정되었습니다.")
        return redirect('monitoring:index')
    return render(request, 'monitoring/tank_form.html', {'tank': tank, 'title': '어항 수정'})

@login_required
def delete_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    messages.success(request, "어항이 삭제되었습니다.")
    return redirect('monitoring:index')

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

@login_required
def ai_report_list(request):
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'reports/report_list.html', {'first_tank': tanks.first(), 'tanks': tanks})