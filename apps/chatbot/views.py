from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import PIL.Image
import os
import json

@login_required
def chatbot_home(request):
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    if request.method == "POST":
        user_message = ""
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                user_message = data.get('message', '').strip()
            except: pass
        else:
            user_message = request.POST.get('message', '').strip()

        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1')),
            getattr(settings, 'GEMINI_API_KEY_2', os.environ.get('GEMINI_API_KEY_2')),
            getattr(settings, 'GEMINI_API_KEY_3', os.environ.get('GEMINI_API_KEY_3')),
        ]
        valid_keys = [k for k in api_keys if k]
        
        last_error = None
        for current_key in valid_keys:
            try:
                genai.configure(api_key=current_key)
                
                # [필살기] 서버가 사용 가능한 모델 목록을 직접 가져옵니다.
                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                
                # 우선순위대로 모델 선택 (목록에 있는 실제 이름을 사용)
                target_model = None
                for candidate in ['models/gemini-1.5-flash', 'models/gemini-pro', 'models/gemini-1.0-pro']:
                    if candidate in available_models:
                        target_model = candidate
                        break
                
                if not target_model:
                    # 만약 위 후보가 없다면 목록 중 첫 번째 모델이라도 사용
                    target_model = available_models[0] if available_models else 'gemini-pro'

                model = genai.GenerativeModel(target_model)
                response = model.generate_content(user_message)
                bot_response = response.text.strip()
                
                ChatMessage.objects.create(user=request.user, message=user_message, response=bot_response)
                return JsonResponse({'status': 'success', 'reply': bot_response})
                
            except Exception as e:
                last_error = e
                continue

        return JsonResponse({'status': 'error', 'message': "박사님이 이름을 잊어버렸대요!", 'debug': str(last_error)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "접근 불가"}, status=405)