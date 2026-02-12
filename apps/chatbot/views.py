from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import traceback

@login_required
def ask_chatbot(request):
    if request.method == "POST":
        user_message = request.POST.get('message')
        try:
            # 1. API 설정
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # 2. 모델 설정 (가장 기본형으로 호출)
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            # 3. 답변 생성 (시스템 메시지 없이 순수하게 질문만 전달)
            # 시스템 메시지는 질문 앞에 텍스트로 붙여서 보냅니다.
            prompt = f"당신은 어항 도우미입니다. 질문에 답하세요: {user_message}"
            response = model.generate_content(prompt)
            
            bot_response = response.text

            # DB 저장
            ChatMessage.objects.create(
                user=request.user, 
                message=user_message, 
                response=bot_response
            )
            
            return JsonResponse({'status': 'success', 'message': bot_response})
            
        except Exception as e:
            print(f"\n[!] 어항 도우미 긴급 디버깅:\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': f"구글 API 응답 에러가 발생했습니다."}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)