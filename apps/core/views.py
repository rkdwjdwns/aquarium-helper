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

# [수정 확인] 모델 가져오기
from monitoring.models import Tank, SensorReading

def index(request):
    """메인 대시보드: 삭제/수정 즉시 반영을 위해 항상 DB 최신 데이터를 조회"""
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    # 정렬 순서를 명확히 하여 메인과 편집센터의 일치감을 높임
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
    """AI 챗봇 API: 특수기호 제거, 가독성 강화, 어항 데이터 실시간 연동"""
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
    
    # [데이터 동기화 핵심] 현재 로그인한 유저의 어항 리스트를 가져와서 챗봇에게 알려줌
    current_user_tanks = Tank.objects.filter(user=request.user)
    tank_info_list = [f"{t.name}(종류: {t.fish_type})" for t in current_user_tanks]
    tank_context = ", ".join(tank_info_list) if tank_info_list else "현재 등록된 어항이 없습니다."

    display_name = getattr(request.user, 'nickname', None) or request.user.username

    api_keys = [
        os.getenv('GEMINI_API_KEY_1'),
        os.getenv('GEMINI_API_KEY_2'),
        os.getenv('GEMINI_API_KEY_3'),
        getattr(settings, 'GEMINI_API_KEY', None)
    ]
    valid_keys = [k for k in api_keys if k]

    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "API 키가 설정되지 않았습니다."}, status=500)

    last_error_msg = ""
    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            # 2026년 최신 모델 우선 순위
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
            
            # [가독성 및 데이터 정합성 지시사항]
            instruction = (
                f"당신은 '어항 도우미'입니다.\n"
                f"현재 사용자: {display_name}님\n"
                f"현재 등록된 어항 정보: {tank_context}\n\n"
                f"답변 규칙:\n"
                f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작할 것.\n"
                f"2. 별표(*), 샵(#), 대시(-) 같은 특수기호는 절대 사용하지 말 것.\n"
                f"3. 모든 답변은 문장 단위로 줄바꿈을 하고, 문단 사이에는 빈 줄을 넣어 깔끔하게 보여줄 것.\n"
                f"4. 중요 항목은 [제목] 형태를 사용하고, 지금 상담원과 대화하는 것처럼 친절하게 말할 것.\n"
                f"5. 어종 질문 시 [수동 설정 추천]과 [자동 설정 추천]을 나누어 친절하게 설명할 것."
            )
            
            prompt_parts = [instruction, user_message]
            if image_file:
                image_file.seek(0)
                img = PIL.Image.open(image_file)
                prompt_parts.insert(1, img)

            response = model.generate_content(prompt_parts)
            
            if response and response.text:
                # 기호 제거 및 깔끔한 정리
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