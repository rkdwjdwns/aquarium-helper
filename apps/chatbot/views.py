from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import PIL.Image
import os
import json
import traceback

@login_required
def chatbot_home(request):
    """채팅 페이지 홈"""
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    if request.method == "POST":
        user_message = ""
        image_file = None

        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                user_message = data.get('message', '').strip()
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': '잘못된 데이터 형식입니다.'}, status=400)
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        if not user_message and not image_file:
            return JsonResponse({'status': 'error', 'message': "질문을 입력해주세요! 🐠"}, status=400)
        
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
                
                # [안전제일] 가장 호환성이 높은 모델명 리스트 순회
                # 1.5-flash가 안되면 pro로, 그것도 안되면 최신 flash 버전으로 시도
                success = False
                for model_name in ["gemini-pro", "gemini-1.5-flash", "gemini-1.5-pro"]:
                    try:
                        # 이미지가 있을 경우 vision 모델로 자동 전환 (구버전 라이브러리 대응)
                        target_model = model_name
                        if image_file and model_name == "gemini-pro":
                            target_model = "gemini-pro-vision"
                        
                        model = genai.GenerativeModel(target_model)
                        
                        content = []
                        if user_message: content.append(user_message)
                        if image_file:
                            img = PIL.Image.open(image_file)
                            content.append(img)
                        
                        response = model.generate_content(content)
                        bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
                        
                        # 성공 시 루프 탈출
                        ChatMessage.objects.create(
                            user=request.user, 
                            message=user_message or "사진 분석", 
                            response=bot_response
                        )
                        return JsonResponse({'status': 'success', 'reply': bot_response, 'message': bot_response})
                    
                    except Exception as inner_e:
                        last_error = inner_e
                        continue # 다음 모델로 시도
                
            except Exception as e:
                last_error = e
                continue

        return JsonResponse({
            'status': 'error', 
            'message': "물물박사가 수리 중이에요! 잠시만 기다려주세요.",
            'debug': str(last_error)
        }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)