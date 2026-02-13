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
    챗봇 질문 처리 (텍스트 + 이미지 분석)
    JSON 요청과 일반 POST 요청을 모두 지원하도록 보완되었습니다.
    """
    if request.method == "POST":
        user_message = ""
        image_file = None

        # [보완] 1. 데이터 추출 (JSON 요청과 일반 Form 요청 구분)
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                user_message = data.get('message', '').strip()
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': '잘못된 JSON 형식입니다.'}, status=400)
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        # 2. 입력값 검증
        if not user_message and not image_file:
            return JsonResponse({
                'status': 'error', 
                'message': "물어보실 내용을 입력하거나 사진을 올려주세요! 🐠"
            }, status=400)
        
        # 3. API 키 로드
        api_keys = [
            getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1')),
            getattr(settings, 'GEMINI_API_KEY_2', os.environ.get('GEMINI_API_KEY_2')),
            getattr(settings, 'GEMINI_API_KEY_3', os.environ.get('GEMINI_API_KEY_3')),
        ]
        valid_keys = [k for k in api_keys if k]
        
        if not valid_keys:
            return JsonResponse({
                'status': 'error', 
                'message': "박사님이 응답할 수 있는 환경(API Key)이 설정되지 않았습니다."
            }, status=500)

        last_error = None
        
        # 4. API 키 순회 시도
        for current_key in valid_keys:
            try:
                genai.configure(api_key=current_key)
                
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=(
                        "당신은 물물박사 '어항 도우미'입니다. 다음 규칙을 엄격히 준수하세요:\n"
                        "1. 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 가독성을 위해 절대 사용하지 마세요.\n"
                        "2. 답변은 친절한 문장 단위로 하되, 줄바꿈을 자주 하여 가독성을 높이세요.\n"
                        "3. 사용자가 물고기 종류를 언급하면 반드시 마지막 줄에 추천 세팅을 포함하세요.\n"
                        "   형식: [SETTING: temp=온도, ph=수치, cycle=환수주기]\n"
                        "4. 사진 분석 요청 시 질병 유무를 먼저 판단하세요."
                    )
                )
                
                # 5. 콘텐츠 구성
                content = []
                if user_message:
                    content.append(user_message)
                if image_file:
                    try:
                        img = PIL.Image.open(image_file)
                        content.append(img)
                    except Exception:
                        return JsonResponse({'status': 'error', 'message': "이미지 파일을 읽을 수 없습니다."}, status=400)
                
                # 6. AI 응답 생성
                response = model.generate_content(content)
                # 특수문자 제거 및 가독성 정리
                bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
                
                # 7. 대화 내역 DB 저장
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message if user_message else "사진 분석 요청 📸", 
                    response=bot_response
                )
                
                # 8. 성공 응답 (JS의 다양한 키값 요구에 대응)
                return JsonResponse({
                    'status': 'success', 
                    'message': bot_response,
                    'reply': bot_response
                })
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # 할당량 초과 시 다음 키로 이동
                if "429" in error_str or "quota" in error_str:
                    continue
                print(f"Gemini API Error: {traceback.format_exc()}")
                continue

        # 모든 키 실패 시
        return JsonResponse({
            'status': 'error', 
            'message': "🐠 물물박사가 지금 너무 바빠서 답변을 못 드렸어요. 잠시 후 다시 시도해 주세요!",
            'debug': str(last_error) if settings.DEBUG else None
        }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)