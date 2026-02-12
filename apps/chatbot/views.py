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
            # 1. API 키가 제대로 설정되어 있는지 다시 확인 (가장 기초적인 단계)
            api_key = settings.GEMINI_API_KEY.strip() if settings.GEMINI_API_KEY else None
            if not api_key:
                return JsonResponse({'status': 'error', 'message': "API 키가 설정되지 않았습니다."}, status=500)

            genai.configure(api_key=api_key)
            
            # 2. 'latest'를 붙여서 최신 통로를 강제로 타게 합니다.
            # 이 이름은 v1beta와 v1 모두에서 가장 잘 인식됩니다.
            model = genai.GenerativeModel("gemini-1.5-flash-latest")
            
            # 3. 답변 생성
            response = model.generate_content(user_message)
            
            # 응답이 비어있을 경우 예외 처리
            if not response.text:
                raise ValueError("AI가 빈 답변을 보냈습니다.")
                
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
            # 실제 에러 메시지를 사용자에게 보여주어 원인을 파악합니다.
            return JsonResponse({'status': 'error', 'message': f"통신 실패: {str(e)}"}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)