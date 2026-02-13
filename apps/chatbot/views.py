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
    """
    모델명 자동 감지 + 친절하고 간결한 답변 스타일 적용 버전
    """
    if request.method == "POST":
        user_message = ""
        image_file = None

        # 1. 데이터 추출 (JSON 및 Form 데이터 모두 대응)
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                user_message = data.get('message', '').strip()
            except:
                pass
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        # 질문이 아예 없는 경우 방어 로직
        if not user_message and not image_file:
            return JsonResponse({'status': 'error', 'message': "궁금한 점을 입력해 주세요! 🌊"}, status=400)
        
        # 2. API 키 로드
        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1')),
            getattr(settings, 'GEMINI_API_KEY_2', os.environ.get('GEMINI_API_KEY_2')),
            getattr(settings, 'GEMINI_API_KEY_3', os.environ.get('GEMINI_API_KEY_3')),
        ]
        valid_keys = [k for k in api_keys if k]
        
        if not valid_keys:
            return JsonResponse({'status': 'error', 'message': "API 키가 설정되지 않았습니다."}, status=500)

        last_error = None
        nickname = request.user.username  # 로그인한 유저의 닉네임 가져오기
        
        # 3. API 키 순회 및 모델 실행
        for current_key in valid_keys:
            try:
                genai.configure(api_key=current_key)
                
                # [404 에러 방지] 사용 가능한 모델 목록 직접 조회
                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                
                # 가장 성능 좋은 모델부터 순차적으로 매칭
                target_model = None
                for candidate in ['models/gemini-1.5-flash', 'models/gemini-pro', 'models/gemini-1.5-flash-latest']:
                    if candidate in available_models:
                        target_model = candidate
                        break
                
                if not target_model:
                    target_model = available_models[0] if available_models else 'models/gemini-pro'

                # 4. 시스템 인스트럭션 설정 (가독성 및 스타일 강제)
                model = genai.GenerativeModel(
                    model_name=target_model,
                    system_instruction=(
                        f"당신은 '어항 도우미'입니다. 다음 규칙을 엄격히 지키세요:\n"
                        f"1. 첫 인사는 반드시 '안녕하세요 {nickname}님! 🌊 궁금한 점이 있다면 물어봐 주세요.'로 시작하세요.\n"
                        f"2. 답변에서 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 절대 쓰지 마세요.\n"
                        f"3. 아주 쉬운 말로 설명하고, 답변은 짧고 간결하게 핵심만 말하세요.\n"
                        f"4. 가독성을 위해 줄바꿈을 아주 자주 하세요.\n"
                        f"5. 답변 끝에는 반드시 다음 형식을 포함하세요: [SETTING: temp=온도, ph=수치, cycle=환수주기]"
                    )
                )
                
                # 5. 콘텐츠 생성 (텍스트 또는 이미지 포함)
                if image_file:
                    img = PIL.Image.open(image_file)
                    response = model.generate_content([user_message or "이 사진 분석해줘", img])
                else:
                    response = model.generate_content(user_message)
                
                # 6. 응답 텍스트 정제 (특수문자 2차 제거)
                bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
                
                # 7. DB 저장 및 성공 응답
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message or "사진 분석 요청 📸", 
                    response=bot_response
                )
                
                return JsonResponse({
                    'status': 'success', 
                    'reply': bot_response,
                    'message': bot_response
                })
                
            except Exception as e:
                last_error = e
                print(f"Gemini API Error: {traceback.format_exc()}")
                continue

        # 모든 키가 실패한 경우
        return JsonResponse({
            'status': 'error', 
            'message': "물물박사가 잠시 자리를 비웠어요. 잠시 후 다시 시도해 주세요!",
            'debug': str(last_error) if settings.DEBUG else None
        }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)