from django.shortcuts import render
from google import genai
from google.genai import types
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import traceback

@login_required
def ask_chatbot(request):
    if request.method == "POST":
        user_message = request.POST.get('message')
        if not user_message:
            return JsonResponse({'status': 'error', 'message': "메시지를 입력해주세요."}, status=400)
        
        try:
            if not settings.GEMINI_API_KEY:
                raise ValueError("API 키가 설정되지 않았습니다.")

            # 1. 클라이언트 생성 (최신 라이브러리 방식)
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            # 2. 모델 ID 설정 
            # 최신 google-genai SDK에서는 "gemini-1.5-flash"만 써도 작동하지만, 
            # 에러가 난다면 다시 한번 "gemini-1.5-flash"로 시도해 봅니다.
            model_id = "gemini-1.5-flash" 
            
            config = types.GenerateContentConfig(
                system_instruction=(
                    "당신은 물물박사 '어항 도우미'입니다. "
                    "1. 사용자가 어종에 대해 물어보면 적정 수온, pH, 사육 난이도를 친절히 설명하세요. "
                    "2. 여러 어종을 나열하며 '합사'나 '같이 키우기'를 물어보면 호환성(공격성, 활동영역 등)을 분석하세요. "
                    "3. 답변 마지막 줄에는 반드시 이 형식을 포함하세요: [추천 세팅: 어종명 / 온도: OO.O / pH: O.O]"
                ),
                temperature=0.7,
                max_output_tokens=1000,
            )
            
            # 3. 답변 생성
            response = client.models.generate_content(
                model=model_id,
                contents=user_message,  # contents=user_message 형식을 유지합니다.
                config=config
            )
            
            bot_response = response.text

            # 4. DB 저장
            ChatMessage.objects.create(
                user=request.user, 
                message=user_message, 
                response=bot_response
            )
            
            return JsonResponse({'status': 'success', 'message': bot_response})
            
        except Exception as e:
            print(f"\n[!] 어항 도우미 긴급 디버깅 로그:")
            print(traceback.format_exc()) 
            error_msg = str(e).lower()
            
            # 에러 메시지에 '404'나 'not found'가 포함되면 출력
            if "429" in error_msg:
                friendly_msg = "현재 요청이 너무 많아 구글이 잠시 쉬고 있어요. 잠시 후 다시 시도해 주세요! 🐠"
            elif "404" in error_msg or "not found" in error_msg:
                friendly_msg = f"모델 인식 오류가 발생했습니다. (에러내용: {error_msg[:50]})"
            else:
                friendly_msg = "AI와 통신 중 문제가 발생했습니다. API 키와 설정을 확인해주세요."
                
            return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)