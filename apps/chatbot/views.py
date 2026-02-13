from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import PIL.Image
import os

@login_required
def chatbot_home(request):
    """채팅 페이지 홈: 이전 대화 내역 50개를 불러옵니다."""
    history = ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]
    return render(request, 'chatbot/chat.html', {'history': reversed(list(history))})

@login_required
def ask_chatbot(request):
    """
    챗봇 질문 처리 (텍스트 + 이미지 분석)
    API 키 3개를 순회하며 할당량 초과 시 자동으로 다음 키를 사용합니다.
    """
    if request.method == "POST":
        user_message = request.POST.get('message', '').strip()
        image_file = request.FILES.get('image')
        
        # 입력값 검증
        if not user_message and not image_file:
            return JsonResponse({
                'status': 'error', 
                'message': "메시지를 입력하거나 사진을 올려주세요."
            }, status=400)
        
        # settings.py 또는 환경변수에서 API 키 3개 가져오기
        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1')),
            getattr(settings, 'GEMINI_API_KEY_2', os.environ.get('GEMINI_API_KEY_2')),
            getattr(settings, 'GEMINI_API_KEY_3', os.environ.get('GEMINI_API_KEY_3')),
        ]
        valid_keys = [k for k in api_keys if k]
        
        if not valid_keys:
            return JsonResponse({
                'status': 'error', 
                'message': "설정된 API 키가 없습니다. 관리자에게 문의하세요."
            }, status=500)

        last_error = None
        
        # 유효한 API 키들을 순회하며 시도
        for current_key in valid_keys:
            try:
                genai.configure(api_key=current_key)
                
                # 시스템 프롬프트 설정
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=(
                        "당신은 물물박사 '어항 도우미'입니다. 답변 규칙:\n"
                        "1. 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 절대 사용하지 마세요.\n"
                        "2. 사용자가 물고기 사진을 올리면 외형을 분석해 질병 유무를 진단하고 치료법을 알려주세요.\n"
                        "3. 답변은 간결하게 문장 단위로 줄바꿈하세요.\n"
                        "4. 특정 물고기 환경 추천 시 답변 끝에 반드시 아래 형식을 붙이세요.\n"
                        "[SETTING: temp=26.0, ph=7.0, cycle=7]"
                    )
                )
                
                # 콘텐츠 구성 (텍스트 + 이미지)
                content = []
                if user_message:
                    content.append(user_message)
                if image_file:
                    img = PIL.Image.open(image_file)
                    content.append(img)
                
                # AI 응답 생성
                response = model.generate_content(content)
                # 특수문자 제거 및 줄바꿈 정리
                bot_response = response.text.replace('*', '').replace('#', '').strip()
                
                # 대화 내역 DB 저장
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message if user_message else "사진 분석 요청 📸", 
                    response=bot_response
                )
                
                # [중요] 'message'와 'reply' 모두 담아서 undefined 원천 차단
                return JsonResponse({
                    'status': 'success', 
                    'message': bot_response,
                    'reply': bot_response
                })
                
            except Exception as e:
                # 429(할당량 초과) 에러 등이 발생하면 다음 키로 넘어감
                last_error = e
                if "429" in str(e) or "quota" in str(e).lower():
                    continue
                # 그 외의 에러도 일단 다음 키 시도
                continue

        # 모든 키가 실패했을 경우
        friendly_msg = f"🐠 물물박사가 지금은 너무 바쁘네요! (사유: {str(last_error)})"
        return JsonResponse({
            'status': 'error', 
            'message': friendly_msg
        }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)