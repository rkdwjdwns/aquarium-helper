import json, os, PIL.Image
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from datetime import date, timedelta
from django.core.paginator import Paginator

# [수정 확인] sys.path 설정에 맞춰 apps. 접두사 없이 올바르게 가져옴
from monitoring.models import Tank, SensorReading

def index(request):
    """메인 대시보드: 비로그인 대응"""
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        
        try:
            if latest and latest.temperature is not None:
                current_temp = float(latest.temperature)
                target_temp = float(tank.target_temp) if tank.target_temp else 26.0
                if abs(current_temp - target_temp) >= 2.0:
                    status = "DANGER"
        except (ValueError, TypeError):
            status = "UNKNOWN"
        
        d_day = 7
        if tank.last_water_change:
            period = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day = (next_change - date.today()).days
        
        tank_data.append({
            'tank': tank, 
            'latest': latest, 
            'status': status, 
            'd_day': d_day
        })

    return render(request, 'core/index.html', {
        'tank_data': tank_data, 
        'page_obj': page_obj,
        'is_guest': False
    })

@login_required
@require_POST
def chat_api(request):
    """AI 챗봇 API: 2026년 최신 모델 자동 인식 및 세팅값 특화"""
    user_message = ""
    image_file = None

    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()
        except: pass
    else:
        user_message = request.POST.get('message', '').strip()
        image_file = request.FILES.get('image')
    
    display_name = getattr(request.user, 'nickname', None) or request.user.username

    api_keys = [
        os.getenv('GEMINI_API_KEY_1'),
        os.getenv('GEMINI_API_KEY_2'),
        os.getenv('GEMINI_API_KEY_3'),
        getattr(settings, 'GEMINI_API_KEY', None)
    ]
    valid_keys = [k for k in api_keys if k]

    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "사용 가능한 API 키가 없습니다."}, status=500)

    last_error_msg = ""
    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            
            # [보완 1] 2026년 가용 모델 목록을 실시간으로 확인
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            # [보완 2] 우선순위 모델 리스트 (로그에 찍힌 2.5, 2.0 버전을 최우선으로)
            selected_model = None
            if image_file:
                candidates = ["models/gemini-2.5-flash", "models/gemini-2.0-flash", "models/gemini-1.5-flash", "models/gemini-pro-vision"]
            else:
                candidates = ["models/gemini-2.5-flash", "models/gemini-2.0-flash", "models/gemini-flash-latest", "models/gemini-pro"]

            for cand in candidates:
                if cand in available_models:
                    selected_model = cand
                    break
            
            # 후보에 없으면 목록 중 첫 번째 모델이라도 사용 (404 방지)
            if not selected_model and available_models:
                selected_model = available_models[0]
            
            if not selected_model: continue

            model = genai.GenerativeModel(model_name=selected_model)
            
            # [보완 3] 세팅값(수동/자동) 안내를 강제하는 프롬프트
            instruction = (
                f"당신은 '어항 도우미'입니다.\n"
                f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                f"2. 특수기호(*, #, -) 사용 금지. 3. 문장마다 줄바꿈 필수.\n"
                f"4. 아주 친절하고 짧게 핵심만 말할 것.\n"
                f"5. 어종 추천이나 사육 환경 질문 시 반드시 아래 형식을 포함할 것:\n"
                f"   [수동 설정 추천]\n"
                f"   직접 관리 시: 환수 주기와 적정 온도\n"
                f"   [자동 설정 추천]\n"
                f"   기기 제어 시: 대시보드 목표 온도 설정값과 센서 주의 기준"
            )
            
            prompt_parts = [instruction]
            if image_file:
                image_file.seek(0)
                img = PIL.Image.open(image_file)
                prompt_parts.extend([img, user_message if user_message else "이 환경의 세팅값을 알려줘."])
            else:
                if not user_message: continue
                prompt_parts.append(user_message)
            
            response = model.generate_content(prompt_parts)
            
            if response and response.text:
                reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()
                
                try:
                    ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                    ChatMessage.objects.create(user=request.user, message=user_message or "(사진 분석)", response=reply)
                except: pass
                
                return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})

        except Exception as e:
            last_error_msg = str(e)
            print(f"Chat API Retry Log: {last_error_msg}")
            continue

    return JsonResponse({'status': 'error', 'message': f"모델 연결 실패: {last_error_msg}"}, status=500)