from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import traceback
import PIL.Image  # 이미지 처리를 위해 추가

@login_required
def chatbot_home(request):
    """채팅 페이지 홈"""
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    """챗봇에게 질문하고 답변 받기 (텍스트 + 이미지 분석 지원)"""
    if request.method == "POST":
        user_message = request.POST.get('message', '')
        image_file = request.FILES.get('image') # 이미지 파일 가져오기
        
        if not user_message and not image_file:
            return JsonResponse({'status': 'error', 'message': "메시지를 입력하거나 사진을 올려주세요."}, status=400)
        
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
                # 이미지 분석을 위해 1.5-flash 이상의 모델 사용
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=(
                        "당신은 물물박사 '어항 도우미'입니다. 답변 규칙:\n"
                        "1. 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 절대 사용하지 마세요.\n"
                        "2. 사용자가 물고기 사진을 올리면 외형을 분석해 질병 유무(백점병, 곰팡이병 등)를 진단하고 치료법을 알려주세요.\n"
                        "3. 답변은 간결하게 문장 단위로 줄바꿈하세요.\n"
                        "4. 특정 물고기 환경 추천 시 답변 끝에 반드시 아래 형식을 붙이세요.\n"
                        "[SETTING: temp=26.0, ph=7.0, cycle=7]"
                    )
                )
                
                # 메시지와 이미지를 함께 전달
                content = []
                if user_message:
                    content.append(user_message)
                if image_file:
                    img = PIL.Image.open(image_file)
                    content.append(img)
                
                response = model.generate_content(content)
                bot_response = response.text
                
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message if user_message else "사진 분석 요청", 
                    response=bot_response
                )
                return JsonResponse({'status': 'success', 'message': bot_response})
                
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    continue 
                last_error = e
                continue

        error_msg = str(last_error)
        friendly_msg = "🐠 물물박사가 지금은 쉬고 있어요! 잠시 후 다시 시도해 주세요."
        return JsonResponse({'status': 'error', 'message': friendly_msg}, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)