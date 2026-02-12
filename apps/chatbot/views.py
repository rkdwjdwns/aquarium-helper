from django.shortcuts import render
from google import genai
from google.genai import types
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import traceback

@login_required
def chatbot_home(request):
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    if request.method == "POST":
        user_message = request.POST.get('message')
        if not user_message:
            return JsonResponse({'status': 'error', 'message': "메시지를 입력해주세요."}, status=400)
        
        try:
            # 1. 클라이언트 생성
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            # 2. 설정 구성
            config = types.GenerateContentConfig(
                system_instruction="당신은 물물박사 '어항 도우미'입니다. 친절하게 답하세요.",
                temperature=0.7,
            )
            
            # 3. 답변 생성 (가장 중요한 부분: 모델명을 "gemini-1.5-flash"로 직접 기입)
            # 만약 404가 계속 나면 "models/gemini-1.5-flash"로 바꿔야 할 수도 있지만, 
            # 최신 라이브러리에서는 아래 형식이 기본입니다.
            response = client.models.generate_content(
                model="gemini-1.5-flash", 
                contents=user_message,
                config=config
            )
            
            bot_response = response.text

            # DB 저장
            ChatMessage.objects.create(
                user=request.user, 
                message=user_message, 
                response=bot_response
            )
            
            return JsonResponse({'status': 'success', 'message': bot_response})
            
        except Exception as e:
            print(f"\n[!] 어항 도우미 디버깅:")
            print(traceback.format_exc())
            error_msg = str(e)
            
            # 404 에러 시 사용자에게 보여줄 메시지
            if "404" in error_msg:
                friendly_msg = "구글 AI 모델 인식에 문제가 있습니다. 관리자에게 문의하세요."
            elif "429" in error_msg:
                friendly_msg = "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
            else:
                friendly_msg = "AI와 통신 중 문제가 발생했습니다."
                
            return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)