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
    """AI 챗봇 API: Render 환경변수 3개 순환 대응"""
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

    # [중요] Render 환경변수 키 3개 + settings 기본키 리스트업
    # Render 대시보드에 입력한 Key 이름과 정확히 일치해야 합니다.
    api_keys = [
        os.getenv('GEMINI_API_KEY_1'),
        os.getenv('GEMINI_API_KEY_2'),
        os.getenv('GEMINI_API_KEY_3'),
        getattr(settings, 'GEMINI_API_KEY', None)
    ]
    # None이거나 빈 문자열인 키는 제외
    valid_keys = [k for k in api_keys if k]

    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "사용 가능한 API 키가 없습니다."}, status=500)

    last_error_msg = ""
    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            # 매번 새로운 키로 모델 인스턴스 생성
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            instruction = (
                f"당신은 '어항 도우미'입니다.\n"
                f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                f"2. 특수기호(*, #, -) 절대 금지. 3. 문장마다 줄바꿈 필수.\n"
                f"4. 아주 친절하고 짧게 핵심만 말할 것."
            )
            
            prompt_parts = [instruction]
            
            if image_file:
                try:
                    # PIL 이미지를 열기 전에 포인터를 처음으로 되돌림 (반복 시도 대비)
                    image_file.seek(0)
                    img = PIL.Image.open(image_file)
                    prompt_parts.append(img)
                    prompt_parts.append(user_message if user_message else "이 사진을 분석해줘.")
                except:
                    return JsonResponse({'status': 'error', 'message': "이미지 파일에 문제가 있습니다."}, status=400)
            else:
                if not user_message:
                    return JsonResponse({'status': 'error', 'message': "메시지를 입력해주세요."}, status=400)
                prompt_parts.append(user_message)
            
            # 답변 생성 시도
            response = model.generate_content(prompt_parts)
            
            if not response or not response.text:
                continue # 응답이 없으면 다음 키로

            reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()

            # 채팅 내역 저장 (데이터베이스 저장 실패가 챗봇 응답을 막지 않도록 try-except)
            try:
                ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message or "(사진 분석)", 
                    response=reply
                )
            except Exception as db_err:
                print(f"DB Save Error: {db_err}")
            
            # 성공 시 즉시 반환
            return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})
            
        except Exception as e:
            last_error_msg = str(e)
            print(f"API Key Error: {last_error_msg}")
            # 429(할당량 초과) 혹은 기타 API 에러 발생 시 다음 키로 루프 진행
            continue

    # 모든 키를 다 돌았는데 실패한 경우
    return JsonResponse({
        'status': 'error', 
        'message': f"모든 AI 엔진이 응답하지 않습니다. (에러: {last_error_msg})"
    }, status=500)