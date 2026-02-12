from django.shortcuts import render
from google import genai
from google.genai import types
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
            # 1.5 버전으로 강제 지정 (무료 할당량이 훨씬 많음)
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            config = types.GenerateContentConfig(
                system_instruction="당신은 어항 전문가 '어항 도우미'입니다. 친절하게 답하세요.",
                temperature=0.7,
            )
            
            # 여기서 gemini-1.5-flash로 명확히 써야 합니다.
            response = client.models.generate_content(
                model="gemini-1.5-flash", 
                contents=user_message,
                config=config
            )
            
            bot_response = response.text
            ChatMessage.objects.create(user=request.user, message=user_message, response=bot_response)
            return JsonResponse({'status': 'success', 'message': bot_response})
            
        except Exception as e:
            print(traceback.format_exc()) 
            error_msg = str(e)
            if "429" in error_msg:
                return JsonResponse({'status': 'error', 'message': "구글 무료 할당량이 잠시 초과되었습니다. 1분 뒤 다시 시도해 주세요!"}, status=500)
            return JsonResponse({'status': 'error', 'message': error_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)