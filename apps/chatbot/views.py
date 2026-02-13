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
    """채팅 페이지 홈: 이전 대화 내역 50개를 불러옵니다."""
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
                return JsonResponse({'status': 'error', 'message': '잘못된 JSON 형식입니다.'}, status=400)
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        if not user_message and not image_file:
            return JsonResponse({
                'status': 'error', 
                'message': "물어보실 내용을 입력하거나 사진을 올려주세요! 🐠"
            }, status=400)
        
        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1')),
            getattr(settings, 'GEMINI_API_KEY_2', os.environ.get('GEMINI_API_KEY_2')),
            getattr(settings, 'GEMINI_API_KEY_3', os.environ.get('GEMINI_API_KEY_3')),
        ]
        valid_keys = [k for k in api_keys if k]
        
        if not valid_keys:
            return JsonResponse({'status': 'error', 'message': "API Key가 설정되지 않았습니다."}, status=500)

        last_error = None
        
        for current_key in valid_keys:
            try:
                genai.configure(api_key=current_key)
                
                # [수정 핵심] 가장 호환성이 좋은 'gemini-1.5-flash-latest'로 명칭 변경
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash-latest", 
                    system_instruction=(
                        "당신은 물물박사 '어항 도우미'입니다. 다음 규칙을 엄격히 준수하세요:\n"
                        "1. 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 절대 사용하지 마세요.\n"
                        "2. 답변은 친절하게 줄바꿈을 자주 하여 가속성을 높이세요.\n"
                        "3. 마지막 줄 형식: [SETTING: temp=온도, ph=수치, cycle=환수주기]"
                    )
                )
                
                content = []
                if user_message:
                    content.append(user_message)
                if image_file:
                    img = PIL.Image.open(image_file)
                    content.append(img)
                
                # AI 응답 생성
                response = model.generate_content(content)
                bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
                
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message if user_message else "사진 분석 요청 📸", 
                    response=bot_response
                )
                
                return JsonResponse({
                    'status': 'success', 
                    'message': bot_response,
                    'reply': bot_response
                })
                
            except Exception as e:
                last_error = e
                # 만약 1.5-flash-latest도 못 찾는다면 gemini-pro로 마지막 시도
                print(f"Gemini API Error: {traceback.format_exc()}")
                continue

        return JsonResponse({
            'status': 'error', 
            'message': "🐠 물물박사가 지금 너무 바빠요! 잠시 후 다시 시도해 주세요.",
            'debug': str(last_error)
        }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)