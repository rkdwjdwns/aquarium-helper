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
    """
    메인 대시보드: 
    로그인 안 한 사용자도 접근 가능하도록 @login_required 제거.
    """
    # 1. 로그인하지 않은 사용자는 소개 페이지나 빈 목록을 보여줌
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    # 2. 로그인한 사용자의 어항 목록 가져오기
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        
        # [보완] float 변환 에러 방지 (데이터가 없을 경우 대비)
        try:
            if latest and latest.temperature is not None:
                current_temp = float(latest.temperature)
                target_temp = float(tank.target_temp) if tank.target_temp else 26.0
                if abs(current_temp - target_temp) >= 2.0:
                    status = "DANGER"
        except (ValueError, TypeError):
            status = "UNKNOWN"
        
        # D-Day 계산 (기본값 7일)
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
    """AI 챗봇 API (텍스트/이미지 대응 및 다중 키 순환)"""
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

    # 설정된 API 키 리스트 (settings.py 및 env 참조)
    api_keys = [
        getattr(settings, 'GEMINI_API_KEY', None), 
        os.getenv('GEMINI_API_KEY_1'),
        os.getenv('GEMINI_API_KEY_2')
    ]
    valid_keys = [k for k in api_keys if k]

    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "설정된 API 키가 없습니다."}, status=500)

    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            # [보완] 챗봇 지침 구체화
            instruction = (
                f"당신은 '어항 도우미'입니다.\n"
                f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                f"2. 특수기호(*, #, -) 절대 금지. 3. 아주 짧게 핵심만 말할 것.\n"
                f"4. 줄바꿈을 문장마다 아주 자주 할 것."
            )
            
            prompt_parts = [instruction]
            
            if image_file:
                try:
                    img = PIL.Image.open(image_file)
                    prompt_parts.append(img)
                    prompt_parts.append(user_message if user_message else "이 사진 속 물고기 상태나 어항 환경을 분석해줘.")
                except:
                    return JsonResponse({'status': 'error', 'message': "이미지 형식이 올바르지 않습니다."}, status=400)
            else:
                prompt_parts.append(user_message)
            
            response = model.generate_content(prompt_parts)
            reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()

            # 동적 모델 로딩 (순환 참조 방지)
            try:
                ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message or "(사진 분석 요청)", 
                    response=reply
                )
            except:
                pass # 모델 저장 실패 시에도 응답은 보내줌
            
            return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})
            
        except Exception as e:
            if "429" in str(e): # 할당량 초과 시 다음 키로 이동
                continue
            print(f"Chat API Error: {e}")
            return JsonResponse({'status': 'error', 'message': "답변 생성 중 오류가 발생했습니다."}, status=500)

    return JsonResponse({'status': 'error', 'message': "모든 API 키의 할당량이 초과되었습니다."}, status=500)