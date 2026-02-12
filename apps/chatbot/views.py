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
    """챗봇에게 질문하고 답변 받기 (멀티 API 키 순회 방식)"""
    if request.method == "POST":
        user_message = request.POST.get('message')
        if not user_message:
            return JsonResponse({'status': 'error', 'message': "메시지를 입력해주세요."}, status=400)
        
        # 1. 사용할 API 키 리스트 준비
        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', None),
            getattr(settings, 'GEMINI_API_KEY_2', None),
            getattr(settings, 'GEMINI_API_KEY_3', None),
        ]
        # 유효한 키만 필터링
        valid_keys = [k for k in api_keys if k]
        
        if not valid_keys:
            return JsonResponse({'status': 'error', 'message': "설정된 API 키가 없습니다."}, status=500)

        last_error = None
        
        # 2. 키를 하나씩 돌려가며 시도
        for i, current_key in enumerate(valid_keys):
            try:
                genai.configure(api_key=current_key)
                
                # 시도할 모델 리스트 (안정적인 1.5-flash를 우선순위에 두면 더 많이 질문 가능해요!)
                models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash"]
                
                for model_name in models_to_try:
                    try:
                        print(f"🔄 키 #{i+1} 시도 중... 모델: {model_name}")
                        
                        model = genai.GenerativeModel(
                            model_name=model_name,
                            system_instruction=(
                                "당신은 물물박사 '어항 도우미'입니다. 답변 규칙을 반드시 지키세요:\n"
                                "1. 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 절대 사용하지 마세요.\n"
                                "2. 답변은 5문장 내외로 핵심만 아주 간결하게 말하세요.\n"
                                "3. 문장 단위로 줄바꿈을 해서 읽기 편하게 만드세요.\n"
                                "4. 친절한 대화체(~해요, ~입니다)를 사용하세요."
                            )
                        )
                        
                        response = model.generate_content(user_message)
                        bot_response = response.text
                        
                        # 성공 시 DB 저장 및 즉시 반환
                        ChatMessage.objects.create(
                            user=request.user, 
                            message=user_message, 
                            response=bot_response
                        )
                        
                        print(f"✅ 키 #{i+1}로 성공! ({model_name})")
                        return JsonResponse({'status': 'success', 'message': bot_response})
                        
                    except Exception as model_error:
                        # 429(할당량 초과) 발생 시 해당 키 포기하고 다음 키로 점프
                        if "429" in str(model_error) or "quota" in str(model_error).lower():
                            print(f"⚠️ 키 #{i+1} 할당량 초과. 다음 키로 넘어갑니다.")
                            last_error = model_error
                            break # inner loop 탈출 -> 다음 키 시도
                        
                        # 그 외의 에러는 다음 모델 시도
                        last_error = model_error
                        continue
                
            except Exception as key_error:
                last_error = key_error
                continue

        # 모든 키와 모델이 실패했을 경우
        print(f"\n[!] 모든 키 사용 실패:\n{traceback.format_exc()}")
        error_msg = str(last_error)
        
        if "429" in error_msg or "quota" in error_msg.lower():
            friendly_msg = "🐠 모든 물물박사들이 지금은 쉬고 있어요! 내일 아침에 다시 새 티켓을 가지고 올게요."
        else:
            friendly_msg = "서비스 연결이 잠시 원활하지 않아요. 잠시 후 다시 시도해 주세요!"
            
        return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)