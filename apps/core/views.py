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
    """AI 챗봇 API: 모델 인식 404 에러 강제 해결 및 세팅값 자동화"""
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
            
            # [진단 및 해결] 현재 API 키가 지원하는 모델 목록을 직접 가져옵니다.
            # 0.5.0 버전 패키지에서도 작동하는 가장 안전한 탐색법입니다.
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            print(f"Available models for this key: {available_models}") # Render 로그에서 확인용

            # 우선순위대로 모델을 선정합니다.
            selected_model = None
            if image_file:
                # 이미지 분석이 가능한 모델 찾기
                for m in ["models/gemini-1.5-flash", "models/gemini-pro-vision", "models/gemini-1.0-pro-vision-latest"]:
                    if m in available_models:
                        selected_model = m
                        break
            else:
                # 텍스트 전용 모델 찾기
                for m in ["models/gemini-1.5-flash", "models/gemini-pro", "models/gemini-1.0-pro"]:
                    if m in available_models:
                        selected_model = m
                        break
            
            # 목록에서 못 찾았다면 하드코딩된 이름으로 최후의 시도
            if not selected_model:
                selected_model = "gemini-pro" if not image_file else "gemini-pro-vision"

            model = genai.GenerativeModel(model_name=selected_model)
            
            # [규칙 보완] 사육 세팅값(수동/자동) 안내 강화
            instruction = (
                f"당신은 '어항 도우미'입니다.\n"
                f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                f"2. 특수기호(*, #, -) 절대 금지. 3. 문장마다 줄바꿈 필수.\n"
                f"4. 아주 친절하고 짧게 핵심만 말할 것.\n"
                f"5. 어종 추천이나 사육법 질문 시 반드시 다음 형식으로 답변할 것:\n"
                f"   [수동 설정 추천]\n"
                f"   - 환수 주기: X일마다\n"
                f"   - 적정 온도: X도\n"
                f"   [자동 설정 추천]\n"
                f"   - 목표 온도 세팅: X도\n"
                f"   - 조명/여과기 자동화 팁"
            )
            
            prompt_parts = [instruction]
            if image_file:
                image_file.seek(0)
                img = PIL.Image.open(image_file)
                prompt_parts.append(img)
                prompt_parts.append(user_message if user_message else "이 사진 속 환경의 세팅값을 알려줘.")
            else:
                if not user_message: continue
                prompt_parts.append(user_message)
            
            response = model.generate_content(prompt_parts)
            
            if response and response.text:
                reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()
                
                try:
                    ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                    ChatMessage.objects.create(user=request.user, message=user_message or "(사진)", response=reply)
                except: pass
                
                return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})

        except Exception as e:
            last_error_msg = str(e)
            print(f"Chat API Retry Log: {last_error_msg}")
            continue

    return JsonResponse({'status': 'error', 'message': f"현재 사용 가능한 AI 모델이 없습니다. (사유: {last_error_msg})"}, status=500)