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
    """챗봇에게 질문하고 답변 받기 (추천 설정 추출 기능 포함)"""
    if request.method == "POST":
        user_message = request.POST.get('message')
        if not user_message:
            return JsonResponse({'status': 'error', 'message': "메시지를 입력해주세요."}, status=400)
        
        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', None),
            getattr(settings, 'GEMINI_API_KEY_2', None),
            getattr(settings, 'GEMINI_API_KEY_3', None),
        ]
        valid_keys = [k for k in api_keys if k]
        
        if not valid_keys:
            return JsonResponse({'status': 'error', 'message': "설정된 API 키가 없습니다."}, status=500)

        last_error = None
        for i, current_key in enumerate(valid_keys):
            try:
                genai.configure(api_key=current_key)
                models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash"]
                
                for model_name in models_to_try:
                    try:
                        model = genai.GenerativeModel(
                            model_name=model_name,
                            system_instruction=(
                                "당신은 물물박사 '어항 도우미'입니다. 답변 규칙:\n"
                                "1. 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 절대 사용하지 마세요.\n"
                                "2. 답변은 5문장 내외로 간결하게 말하고 문장 단위로 줄바꿈하세요.\n"
                                "3. 특정 물고기의 환경을 추천할 때는 반드시 답변 맨 끝에 아래 형식을 정확히 붙이세요.\n"
                                "[SETTING: temp=26.0, ph=7.0, cycle=7]\n"
                                "(숫자는 추천값에 따라 변경하세요)"
                            )
                        )
                        
                        response = model.generate_content(user_message)
                        bot_response = response.text
                        
                        ChatMessage.objects.create(
                            user=request.user, 
                            message=user_message, 
                            response=bot_response
                        )
                        return JsonResponse({'status': 'success', 'message': bot_response})
                        
                    except Exception as model_error:
                        if "429" in str(model_error) or "quota" in str(model_error).lower():
                            break 
                        last_error = model_error
                        continue
                
            except Exception as key_error:
                last_error = key_error
                continue

        error_msg = str(last_error)
        if "429" in error_msg or "quota" in error_msg.lower():
            friendly_msg = "🐠 모든 물물박사들이 지금은 쉬고 있어요! 내일 아침에 다시 새 티켓을 가지고 올게요."
        else:
            friendly_msg = "서비스 연결이 잠시 원활하지 않아요. 잠시 후 다시 시도해 주세요!"
            
        return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)