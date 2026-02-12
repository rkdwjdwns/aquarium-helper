from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import traceback

@login_required
def chatbot_home(request):
    """채팅 페이지 홈"""
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    """챗봇에게 질문하고 답변 받기"""
    if request.method == "POST":
        user_message = request.POST.get('message')
        if not user_message:
            return JsonResponse({'status': 'error', 'message': "메시지를 입력해주세요."}, status=400)
        
        try:
            # 1. API KEY 설정 확인
            if not getattr(settings, 'GEMINI_API_KEY', None):
                raise ValueError("서버 환경 설정에 API KEY가 누락되었습니다.")

            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # 2. 시도할 모델 리스트 (2026년 기준 최신순)
            models_to_try = [
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-1.5-flash",  # 가장 안정적인 모델 추가
                "gemini-flash-latest",
            ]
            
            last_error = None
            
            # 3. 성공할 때까지 모델 순회 시도
            for model_name in models_to_try:
                try:
                    print(f"🔄 시도 중인 모델: {model_name}")
                    
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction="당신은 물물박사 '어항 도우미'입니다. 어항 관리, 물고기 질병, 수초 육성에 대해 친절하고 전문적으로 답하세요."
                    )
                    
                    response = model.generate_content(user_message)
                    bot_response = response.text
                    
                    # 답변이 성공하면 DB 저장 후 즉시 반환
                    ChatMessage.objects.create(
                        user=request.user, 
                        message=user_message, 
                        response=bot_response
                    )
                    
                    print(f"✅ 모델 작동 성공: {model_name}")
                    return JsonResponse({'status': 'success', 'message': bot_response})
                    
                except Exception as model_error:
                    last_error = model_error
                    error_str = str(model_error)
                    
                    # 429(할당량 초과)는 모델을 바꿔도 같을 확률이 높으므로 즉시 중단
                    if "429" in error_str or "quota" in error_str.lower():
                        print(f"⚠️ {model_name}: 할당량 초과 발생")
                        raise model_error
                    
                    # 그 외의 에러(404 등)는 다음 모델로 넘어감
                    print(f"❌ {model_name} 실패: {error_str[:50]}...")
                    continue
            
            # 모든 모델 시도 실패 시 마지막 에러 발생
            if last_error:
                raise last_error
            
        except Exception as e:
            print(f"\n[!] 어항 도우미 최종 디버깅:")
            print(traceback.format_exc())
            error_msg = str(e)
            
            # 사용자 친절 메시지 처리
            if "429" in error_msg or "quota" in error_msg.lower():
                friendly_msg = "🐠 AI 물물박사가 잠시 쉬는 시간이에요! 하루 무료 사용량을 다 썼습니다. 1분 후 다시 시도하거나, Google AI Studio에서 새 API 키를 발급받아주세요."
            elif "404" in error_msg:
                friendly_msg = "모델을 찾을 수 없습니다(404). API 키의 프로젝트 권한을 확인해주세요."
            elif "403" in error_msg:
                friendly_msg = "API 키 권한이 없습니다(403). AI Studio에서 API 활성화 상태를 확인해주세요."
            else:
                friendly_msg = f"서비스가 일시적으로 원활하지 않습니다: {error_msg[:100]}"
                
            return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)