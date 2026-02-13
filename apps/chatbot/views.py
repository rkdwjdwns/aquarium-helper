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

        # 1. 데이터 추출
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                user_message = data.get('message', '').strip()
            except:
                return JsonResponse({'status': 'error', 'message': 'Data error'}, status=400)
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        if not user_message and not image_file:
            return JsonResponse({'status': 'error', 'message': "질문을 입력해주세요!"}, status=400)
        
        # 2. API 키 설정
        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1')),
            getattr(settings, 'GEMINI_API_KEY_2', os.environ.get('GEMINI_API_KEY_2')),
            getattr(settings, 'GEMINI_API_KEY_3', os.environ.get('GEMINI_API_KEY_3')),
        ]
        valid_keys = [k for k in api_keys if k]
        
        last_error = None
        
        # 3. 가장 원시적이고 안전한 방식으로 호출
        for current_key in valid_keys:
            try:
                genai.configure(api_key=current_key)
                
                # 시스템 인스트럭션 없이 가장 기본 모델로 설정
                # 구형 라이브러리에서 가장 에러 없는 모델명인 'gemini-pro' 사용
                model = genai.GenerativeModel('gemini-pro')
                
                # 이미지 전송 시 pro-vision으로 강제 전환 (구버전 호환용)
                if image_file:
                    model = genai.GenerativeModel('gemini-pro-vision')
                    img = PIL.Image.open(image_file)
                    response = model.generate_content([user_message or "이 사진 분석해줘", img])
                else:
                    response = model.generate_content(user_message)
                
                bot_response = response.text.strip()
                
                # DB 저장
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message or "사진 분석", 
                    response=bot_response
                )
                
                return JsonResponse({
                    'status': 'success', 
                    'reply': bot_response, 
                    'message': bot_response
                })
                
            except Exception as e:
                last_error = e
                print(f"Critical API Error: {str(e)}")
                continue

        # 모든 시도가 실패했을 때
        return JsonResponse({
            'status': 'error', 
            'message': "물물박사가 잠시 자리를 비웠어요. 잠시 후 다시 시도해주세요!",
            'debug': str(last_error)
        }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "Invalid access"}, status=405)