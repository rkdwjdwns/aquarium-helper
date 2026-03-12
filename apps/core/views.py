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

@login_required
def index(request):
    """메인 대시보드 어항 목록"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        
        if latest and latest.temperature:
            if abs(float(latest.temperature) - float(tank.target_temp or 26.0)) >= 2.0:
                status = "DANGER"
        
        d_day = 7
        if tank.last_water_change:
            period = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day = (next_change - date.today()).days
        
        tank_data.append({'tank': tank, 'latest': latest, 'status': status, 'd_day': d_day})

    return render(request, 'core/index.html', {'tank_data': tank_data, 'page_obj': page_obj})

@login_required
@require_POST
def chat_api(request):
    """AI 챗봇 API (텍스트/이미지 대응)"""
    if request.content_type == 'application/json':
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
    else:
        user_message = request.POST.get('message', '').strip()
    
    image_file = request.FILES.get('image')
    display_name = getattr(request.user, 'nickname', None) or request.user.username

    # 설정된 API 키 리스트업 및 유효성 검사
    api_keys = [settings.GEMINI_API_KEY, os.getenv('GEMINI_API_KEY_2'), os.getenv('GEMINI_API_KEY_3')]
    valid_keys = [k for k in api_keys if k]

    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "설정된 API 키가 없습니다."}, status=500)

    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            prompt = [
                f"당신은 '어항 도우미'입니다. 1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작. "
                "2. 특수기호(*, #) 절대 금지. 3. 짧게 줄바꿈을 아주 자주 할 것.",
                user_message if user_message else "이 사진을 분석해줘."
            ]
            
            # [보완] 이미지 파일이 손상되었거나 형식이 맞지 않을 경우의 예외 처리 추가
            if image_file:
                try:
                    img = PIL.Image.open(image_file)
                    prompt.append(img)
                except Exception as e:
                    return JsonResponse({'status': 'error', 'message': "이미지를 읽을 수 없습니다. 다시 업로드해주세요."}, status=400)
            
            response = model.generate_content(prompt)
            reply = response.text.replace('*', '').replace('#', '').strip()

            # 동적 모델 로딩을 통한 순환 참조 방지 (아주 좋은 접근입니다!)
            ChatMessage = apps.get_model('chatbot', 'ChatMessage')
            ChatMessage.objects.create(
                user=request.user, 
                message=user_message or "사진 분석", 
                response=reply
            )
            
            return JsonResponse({'status': 'success', 'reply': reply})
            
        except Exception as e:
            # 할당량 초과(429) 에러 시 다음 키로 시도
            if "429" in str(e): 
                continue
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': "모든 API 키가 만료되거나 오류가 발생했습니다."}, status=500)