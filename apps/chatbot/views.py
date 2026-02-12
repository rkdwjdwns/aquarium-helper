from google import genai
from google.genai import types
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import traceback

@login_required
def ask_chatbot(request):
    """
    사용자의 질문을 받아 Gemini AI 응답을 생성하는 뷰 (1.5-flash 모델 사용)
    """
    if request.method == "POST":
        if not request.user.is_authenticated:
            return JsonResponse({
                'status': 'error', 
                'message': "로그인 세션이 만료되었습니다. 다시 로그인해 주세요."
            }, status=401)

        user_message = request.POST.get('message')
        
        if not user_message:
            return JsonResponse({'status': 'error', 'message': "메시지를 입력해주세요."})
        
        try:
            # 1. 클라이언트 설정 (settings에 등록된 API 키 사용)
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            # 2. 모델 설정 (할당량이 넉넉한 1.5-flash로 변경)
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
                contents=user_message,
                config=config
            )
            
            if not response or not hasattr(response, 'text'):
                raise ValueError("API 응답 데이터가 올바르지 않습니다.")
                
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
            print(traceback.format_exc()) # 상세 에러 로그 출력
            
            error_msg = str(e)
            
            if "429" in error_msg:
                friendly_msg = "현재 질문이 너무 많아 구글이 잠시 쉬고 있어요. 1분만 기다려 주세요! 🐠"
            elif "401" in error_msg or "403" in error_msg:
                friendly_msg = "API 키 인증에 문제가 발생했습니다. Render의 Environment 설정을 확인해주세요."
            else:
                friendly_msg = "AI와 통신 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요."

            return JsonResponse({
                'status': 'error', 
                'message': friendly_msg
            }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)