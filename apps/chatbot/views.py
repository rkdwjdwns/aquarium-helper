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
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    if request.method == "POST":
        user_message = ""
        image_file = None

        # JSON 요청과 일반 Form 요청 모두 대응
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                user_message = data.get('message', '').strip()
            except: pass
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        # 닉네임 설정 (없으면 username)
        display_name = getattr(request.user, 'nickname', request.user.username)
        
        # [수정] settings.py에 정의된 GEMINI_API_KEY를 우선 참조
        api_key = getattr(settings, 'GEMINI_API_KEY', None) or \
                  getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1'))

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
                response = model.generate_content([user_message or "분석해줘", img])
            else:
                response = model.generate_content(user_message)
            
            # 특수기호 제거 및 정리
            bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
            
            # DB 저장
            ChatMessage.objects.create(user=request.user, message=user_message, response=bot_response)
            
            # 응답 반환 (base.html의 JS가 'reply'를 찾음)
            return JsonResponse({'status': 'success', 'reply': bot_response})
            
        except Exception as e:
            print(f"Chatbot Error: {e}") # 터미널에서 에러 확인용
            return JsonResponse({'status': 'error', 'message': "잠시 후 다시 시도해주세요!"}, status=500)
            
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)