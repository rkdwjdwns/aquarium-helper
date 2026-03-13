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
    """AI 챗봇 API: 모델 인식 404 에러 보완 및 세팅값 안내 기능 강화"""
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

    # [보완 1] 현재 라이브러리 버전에서 404가 나지 않도록 폴백 모델 리스트 준비
    # 이미지 분석 여부에 따라 다른 모델명을 시도합니다.
    if image_file:
        model_candidates = ["gemini-1.5-flash", "gemini-pro-vision"]
    else:
        model_candidates = ["gemini-1.5-flash", "gemini-pro"]

    last_error_msg = ""
    for key in valid_keys:
        genai.configure(api_key=key)
        
        for model_name in model_candidates:
            try:
                model = genai.GenerativeModel(model_name=model_name)
                
                # [보완 2] 프롬프트 강화: 세팅값(수동/자동)을 반드시 알려주도록 지시
                instruction = (
                    f"당신은 '어항 도우미'입니다.\n"
                    f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                    f"2. 특수기호(*, #, -) 절대 금지. 3. 문장마다 줄바꿈 필수.\n"
                    f"4. 아주 친절하고 짧게 핵심만 말할 것.\n"
                    f"5. 물고기 사육법을 물으면 반드시 [수동 설정]과 [자동 설정] 값을 나누어 추천할 것.\n"
                    f"   - 수동 설정: 직접 관리할 때의 환수 주기, 온도 등\n"
                    f"   - 자동 설정: 우리 서비스 제어판에서 설정할 목표 온도, 센서 기준치 등"
                )
                
                prompt_parts = [instruction]
                
                if image_file:
                    image_file.seek(0)
                    img = PIL.Image.open(image_file)
                    prompt_parts.append(img)
                    prompt_parts.append(user_message if user_message else "이 사진 속 물고기나 어항 상태를 보고 사육 세팅값을 알려줘.")
                else:
                    if not user_message:
                        continue
                    prompt_parts.append(user_message)
                
                # 안전한 응답 생성을 위한 설정 추가
                response = model.generate_content(prompt_parts)
                
                if not response or not response.candidates:
                    continue

                reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()

                # DB 저장 로직 (앱 이름 'chatbot' 확인 필수)
                try:
                    ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                    ChatMessage.objects.create(
                        user=request.user, 
                        message=user_message or "(사진 분석)", 
                        response=reply
                    )
                except: pass
                
                return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})
                
            except Exception as e:
                last_error_msg = str(e)
                # 404 에러나 모델 지원 에러 발생 시 다음 모델이나 다음 키로 넘어감
                print(f"Model {model_name} Error ({key[:5]}...): {last_error_msg}")
                continue

    return JsonResponse({'status': 'error', 'message': f"AI 엔진 응답 실패: {last_error_msg}"}, status=500)