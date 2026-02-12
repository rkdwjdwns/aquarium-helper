from django.shortcuts import render
import google.generativeai as genai  # 안정적인 라이브러리로 변경
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
            # 1. 설정 (안정판 방식)
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # 2. 모델 설정 (v1beta가 아닌 정식 v1 통로를 사용하게 됩니다)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction="당신은 물물박사 '어항 도우미'입니다. 친절하게 답하세요."
            )
            
            # 3. 답변 생성
            response = model.generate_content(user_message)
            bot_response = response.text

            # DB 저장
            ChatMessage.objects.create(
                user=request.user, 
                message=user_message, 
                response=bot_response
            )
            
            return JsonResponse({'status': 'success', 'message': bot_response})
            
        except Exception as e:
            print(f"\n[!] 어항 도우미 디버깅:\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': f"에러 발생: {str(e)}"}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)