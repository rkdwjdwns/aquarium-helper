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
            # 1. API 키 확인
            if not settings.GEMINI_API_KEY:
                raise ValueError("API KEY가 설정되지 않았습니다.")

            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            # 2. 모델명 수정 (여기가 범인입니다! 2.0이 아니라 1.5로!)
            response = client.models.generate_content(
                model="gemini-1.5-flash-8b",  # <--- 반드시 이 이름이어야 합니다.
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction="당신은 물물박사 '어항 도우미'입니다. 친절하게 답하세요.",
                    temperature=0.7,
                )
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
            
            # 에러 메시지 처리
            if "404" in error_msg:
                friendly_msg = "모델을 찾을 수 없습니다. (gemini-1.5-flash인지 확인 필요)"
            elif "429" in error_msg:
                friendly_msg = "요청이 너무 많습니다. 잠시만 기다려주세요."
            else:
                friendly_msg = f"에러가 발생했습니다: {error_msg}"
                
            return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)
# Final Build Version: 1.5-flash-fixed