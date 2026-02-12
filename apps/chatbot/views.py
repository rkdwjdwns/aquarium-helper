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
            if not settings.GEMINI_API_KEY:
                raise ValueError("API KEY가 설정되지 않았습니다.")

            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            # [핵심 수정] 모델명을 'gemini-1.5-flash-latest'로 변경
            response = client.models.generate_content(
                model="gemini-1.5-flash-latest",  # ← 여기가 핵심!
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
            
            if "404" in error_msg:
                friendly_msg = "구글 서버에서 모델을 찾을 수 없습니다(404). 모델명을 확인해주세요."
            elif "429" in error_msg:
                friendly_msg = "요청이 너무 많습니다(429). 1분 뒤에 다시 시도해주세요."
            else:
                friendly_msg = f"에러 발생: {error_msg}"
                
            return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)