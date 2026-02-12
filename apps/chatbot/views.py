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
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            config = types.GenerateContentConfig(
                system_instruction="당신은 물물박사 '어항 도우미'입니다. 친절하게 답하세요.",
                temperature=0.7,
            )
            
            # 1.5 대신 확실한 2.0 모델 사용 (이름표 오류 방지)
            response = client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=user_message,
                config=config
            )
            
            bot_response = response.text
            ChatMessage.objects.create(user=request.user, message=user_message, response=bot_response)
            return JsonResponse({'status': 'success', 'message': bot_response})
            
        except Exception as e:
            print(traceback.format_exc()) 
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)