import json
import os
import PIL.Image
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from datetime import date, timedelta
from django.core.paginator import Paginator

# 모델 임포트
from monitoring.models import Tank, SensorReading

def home(request):
    """로그인 상태에 따라 홈 또는 인덱스 페이지 표시"""
    if request.user.is_authenticated:
        return index(request)
    return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

def index(request):
    """메인 대시보드: 데이터 정합성을 위해 항상 DB에서 최신순 조회"""
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    # 편집 센터와 순서를 맞추기 위해 최신순(-id) 정렬 (삭제 즉시 반영)
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
    """AI 챗봇 API: 가독성 강화 버전 (핵심 로직 유지)"""
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
    
    # 실시간 어항 데이터 연동
    user_tanks = Tank.objects.filter(user=request.user)
    tank_info = ", ".join([f"{t.name}" for t in user_tanks]) if user_tanks else "등록된 어항 없음"
    display_name = getattr(request.user, 'nickname', None) or request.user.username

    api_keys = [
        os.getenv('GEMINI_API_KEY_1'),
        os.getenv('GEMINI_API_KEY_2'),
        os.getenv('GEMINI_API_KEY_3'),
        getattr(settings, 'GEMINI_API_KEY', None)
    ]
    valid_keys = [k for k in api_keys if k]

    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "API 키가 없습니다."}, status=500)

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
            
            instruction = (
                f"너는 어항 관리 전문가 챗봇이야.\n\n"
                f"[절대 규칙 - 하나라도 어기면 안 됨]\n"
                f"1. 답변은 무조건 5줄 이내. 6줄 이상 절대 금지.\n"
                f"2. 각 줄 앞에 반드시 이모지 1개. 예) 🌡️ 수온: 25~27°C\n"
                f"3. 핵심 키워드 + 수치만. 설명 문장 금지.\n"
                f"4. '~입니다' '~합니다' '~세요' '~군요' 문장체 완전 금지.\n"
                f"5. 어항 등록, 어항 정보 없음 언급 완전 금지. 질문에만 답해.\n"
                f"6. 마지막 줄은 🐠 로 짧게 마무리.\n"
            )
            
            prompt_parts = [instruction, user_message]
            if image_file:
                image_file.seek(0)
                prompt_parts.insert(1, PIL.Image.open(image_file))

            response = model.generate_content(prompt_parts)
            
            if response and response.text:
                # 기호 강제 제거 필터
                reply = response.text.replace('*', '').replace('#', '').replace('-', '').strip()
                
                try:
                    ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                    ChatMessage.objects.create(user=request.user, message=user_message or "(사진 분석)", response=reply)
                except: pass
                
                return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})

        except Exception as e:
            last_error_msg = str(e)
            continue

    return JsonResponse({'status': 'error', 'message': f"연결 실패: {last_error_msg}"}, status=500)