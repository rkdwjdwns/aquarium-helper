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
            api_key = settings.GEMINI_API_KEY.strip()
            genai.configure(api_key=api_key)
            
            # 2. 검증된 모델로 변경 (목록에 있던 바로 그 이름!)
            # 2026년형 최신 모델인 2.0-flash를 사용합니다.
            model_name = "gemini-2.0-flash" 
            model = genai.GenerativeModel(model_name)
            
            # 3. 답변 생성
            # 시스템 메시지를 프롬프트에 직접 녹여서 전달합니다.
            prompt = f"당신은 물물박사 '어항 도우미'입니다. 친절하고 전문적으로 답하세요.\n\n질문: {user_message}"
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
            print(f"\n[!] 어항 도우미 최종 디버깅:\n{traceback.format_exc()}")
            return JsonResponse({
                'status': 'error', 
                'message': f"통신 성공했으나 답변 생성 중 오류: {str(e)}"
            }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)