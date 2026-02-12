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
            # 1. API 키 설정
            api_key = settings.GEMINI_API_KEY.strip()
            genai.configure(api_key=api_key)
            
            # [디버깅] 현재 이 키로 사용할 수 있는 모델 목록을 로그에 출력합니다.
            print("\n=== [어항 도우미] 사용 가능한 모델 목록 ===")
            available_models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    print(f"사용 가능 모델: {m.name}")
                    available_models.append(m.name)
            print("=========================================\n")

            # 2. 모델 선택 (가장 표준적인 이름으로 시도)
            # 만약 목록에 다른 이름이 있다면 그 이름을 써야 합니다.
            model_name = "gemini-1.5-flash" 
            model = genai.GenerativeModel(model_name)
            
            # 3. 답변 생성
            response = model.generate_content(user_message)
            bot_response = response.text

            ChatMessage.objects.create(
                user=request.user, 
                message=user_message, 
                response=bot_response
            )
            
            return JsonResponse({'status': 'success', 'message': bot_response})
            
        except Exception as e:
            print(f"\n[!] 어항 도우미 긴급 디버깅:\n{traceback.format_exc()}")
            # 에러 메시지에 모델 목록 정보를 살짝 섞어서 띄워줍니다.
            return JsonResponse({
                'status': 'error', 
                'message': f"통신 실패(404). API 키가 모델에 접근할 수 없습니다. AI Studio에서 새 프로젝트 키를 생성했는지 확인해주세요."
            }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)