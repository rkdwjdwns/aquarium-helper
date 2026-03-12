from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import PIL.Image
import os
import json

@login_required
def chatbot_home(request):
    # 최신 대화 기록 50개를 가져와서 보여줍니다.
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    if request.method == "POST":
        user_message = ""
        image_file = None

        # JSON 및 Form 데이터 대응
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                user_message = data.get('message', '').strip()
            except: pass
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        display_name = getattr(request.user, 'nickname', request.user.username)
        
        # API 키 참조 (settings.py 우선)
        api_key = getattr(settings, 'GEMINI_API_KEY', None) or os.environ.get('GEMINI_API_KEY_1')

        if not api_key:
            return JsonResponse({'status': 'error', 'message': "API 키가 설정되지 않았습니다."}, status=500)

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name='gemini-1.5-flash',
                system_instruction=(
                    f"당신은 '어항 도우미'입니다.\n"
                    f"1. 첫 문장은 반드시 '{display_name}님! 🌊'으로 시작.\n"
                    f"2. 별표(*), 해시(#), 대시(-) 등 특수 기호는 절대 사용 금지.\n"
                    f"3. 아주 쉽고 짧게 핵심만 말할 것.\n"
                    f"4. 가독성을 위해 줄바꿈을 자주 할 것.\n"
                    f"5. 마지막에 [권장설정: 온도 26도, pH 7.0, 환수 7일] 형태를 꼭 포함할 것."
                )
            )
            
            if image_file:
                img = PIL.Image.open(image_file)
                response = model.generate_content([user_message or "이 어항 사진을 분석해줘.", img])
            else:
                response = model.generate_content(user_message)
            
            # 응답 텍스트 정리
            bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
            
            # DB 저장 (message가 비어있을 경우 대응)
            ChatMessage.objects.create(
                user=request.user, 
                message=user_message if user_message else "(사진 분석 요청)", 
                response=bot_response
            )
            
            # 프론트엔드 JS가 'reply' 또는 'response' 중 무엇을 찾든 대응하도록 둘 다 보냅니다.
            return JsonResponse({
                'status': 'success', 
                'reply': bot_response,
                'response': bot_response  # undefined 방지를 위해 추가
            })
            
        except Exception as e:
            print(f"Chatbot Error: {e}")
            return JsonResponse({'status': 'error', 'message': "AI 응답 중 오류가 발생했습니다."}, status=500)
            
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)