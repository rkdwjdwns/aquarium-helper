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

# 모델 가져오기
from monitoring.models import Tank, SensorReading

def index(request):
    """메인 대시보드: 데이터 정합성을 위해 항상 DB에서 최신순 조회"""
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    # 편집 센터와 순서를 맞추기 위해 최신순(-id) 정렬
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
    """AI 챗봇 API: 특수기호 완전 제거 및 실시간 데이터 연동"""
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
    
    # [데이터 동기화] 현재 유저의 어항 정보를 실시간으로 조회하여 챗봇에게 주입
    user_tanks = Tank.objects.filter(user=request.user)
    tank_info = ", ".join([f"{t.name}({t.fish_type})" for t in user_tanks]) if user_tanks else "현재 등록된 어항 없음"
    
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
            candidates = ["models/gemini-2.5-flash", "models/gemini-2.0-flash", "models/gemini-flash-latest"]
            for cand in candidates:
                if cand in available_models:
                    selected_model = cand
                    break
            
            if not selected_model and available_models:
                selected_model = available_models[0]
            
            if not selected_model: continue

            model = genai.GenerativeModel(model_name=selected_model)
            
            # [가독성 극대화 지시사항] 특수문자 금지 및 문장별 줄바꿈 강조
            instruction = (
                f"당신은 '어항 도우미'입니다.\n"
                f"사용자: {display_name}님 / 현재 보유 어항: {tank_info}\n\n"
                f"답변 규칙 (엄격 준수):\n"
                f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작하세요.\n"
                f"2. 별표(*), 샵(#), 대시(-) 같은 모든 특수기호를 절대 사용하지 마세요.\n"
                f"3. 오직 문장과 줄바꿈(엔터)만 사용하여 내용을 구분하세요.\n"
                f"4. 중요 항목은 [제목] 처럼 대괄호를 사용하고, 각 문단 사이에는 빈 줄을 넣어 간격을 벌리세요.\n"
                f"5. 지금 상담원과 대화하는 것처럼 부드럽고 친절한 말투를 유지하세요.\n"
                f"6. 사육법 질문 시 [수동 관리 추천]과 [자동 기기 세팅값]을 나누어 상세히 설명하세요."
            )
            
            prompt_parts = [instruction, user_message]
            if image_file:
                image_file.seek(0)
                prompt_parts.insert(1, PIL.Image.open(image_file))

            response = model.generate_content(prompt_parts)
            
            if response and response.text:
                # 기호 강제 제거 (2중 필터)
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