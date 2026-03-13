import json, os, PIL.Image
import google.generativeai as genai
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from datetime import date, timedelta
from django.core.paginator import Paginator

# [중요] 데이터 정합성을 위해 올바른 경로에서 모델 가져오기
from monitoring.models import Tank, SensorReading

def index(request):
    """메인 대시보드: 어항 삭제/수정 내용이 즉시 반영되도록 실시간 조회"""
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    # [수정] 사용자의 어항을 항상 최신 DB 기준으로 필터링
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
        'is_guest': False,
        'has_tanks': all_tanks.exists()
    })

@login_required
@require_POST
def chat_api(request):
    """AI 챗봇 API: 정준님 기존 모델 탐색 로직 + 실시간 데이터 연동 + 스타일 수정"""
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
    
    # [추가] 챗봇에게 현재 내 어항 정보를 알려주기 위한 로직
    user_tanks = Tank.objects.filter(user=request.user)
    tank_info = ", ".join([f"{t.name}" for t in user_tanks]) if user_tanks.exists() else "등록된 어항 없음"
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
            
            # [스타일 수정] 요청하신 대로 기호 제거 및 친절한 말투 설정
            instruction = (
                f"당신은 친절한 '어항 도우미'입니다.\n"
                f"사용자: {display_name}님 / 보유 어항: {tank_info}\n\n"
                f"규칙:\n"
                f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작.\n"
                f"2. 별표(*), 샵(#), 대시(-) 기호 절대 사용 금지.\n"
                f"3. 문장마다 줄바꿈(엔터) 필수.\n"
                f"4. 중요 제목은 [제목] 형태를 사용하고 문단 사이 간격을 벌릴 것.\n"
                f"5. 사육 환경 질문 시 [수동 설정 추천]과 [자동 설정 추천]을 나누어 친절히 설명할 것."
            )
            
            prompt_parts = [instruction]
            if image_file:
                image_file.seek(0)
                img = PIL.Image.open(image_file)
                prompt_parts.extend([img, user_message if user_message else "상태를 분석해줘."])
            else:
                if not user_message: continue
                prompt_parts.append(user_message)
            
            response = model.generate_content(prompt_parts)
            
            if response and response.text:
                # 기호 강제 제거
                reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()
                
                try:
                    ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                    ChatMessage.objects.create(user=request.user, message=user_message or "(사진 분석)", response=reply)
                except: pass
                
                return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})

        except Exception as e:
            last_error_msg = str(e)
            continue

    return JsonResponse({'status': 'error', 'message': f"모델 연결 실패: {last_error_msg}"}, status=500)