from django.shortcuts import render
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ChatMessage
import PIL.Image
import os
import traceback

@login_required
def chatbot_home(request):
    """채팅 페이지 홈: 이전 대화 내역 50개를 불러옵니다."""
    # 유저별 대화 내역을 가져와서 템플릿에 전달
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
        
        # 1. 입력값 검증 (메시지나 이미지 중 하나는 반드시 있어야 함)
        if not user_message and not image_file:
            return JsonResponse({
                'status': 'error', 
                'message': "물어보실 내용을 입력하거나 사진을 올려주세요! 🐠"
            }, status=400)
        
        # 2. API 키 로드 (settings.py 우선, 없으면 환경변수 탐색)
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
        
        # 3. 유효한 API 키들을 순회하며 시도
        for current_key in valid_keys:
            try:
                genai.configure(api_key=current_key)
                
                # [보완] 추천 세팅 추출을 위한 강화된 시스템 인스트럭션
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=(
                        "당신은 물물박사 '어항 도우미'입니다. 다음 규칙을 엄격히 준수하세요:\n"
                        "1. 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 가독성을 위해 절대 사용하지 마세요.\n"
                        "2. 답변은 친절한 문장 단위로 하되, 줄바꿈을 자주 하여 가독성을 높이세요.\n"
                        "3. 사용자가 물고기 종류(예: 구피, 베타, 금붕어 등)를 언급하거나 환경을 물어보면 반드시 답변 맨 마지막 줄에 아래의 형식으로 추천 세팅을 포함하세요.\n"
                        "   형식: [SETTING: temp=온도, ph=수치, cycle=환수주기]\n"
                        "   예시: [SETTING: temp=26.0, ph=7.0, cycle=7]\n"
                        "4. 사용자가 물고기 사진을 올리면 외형을 분석하여 백점병, 곰팡이병 등 질병 유무를 먼저 판단하고 조치법을 설명하세요."
                    )
                )
                
                # 4. 콘텐츠 구성 (텍스트 + 이미지)
                content = []
                if user_message:
                    content.append(user_message)
                if image_file:
                    try:
                        img = PIL.Image.open(image_file)
                        content.append(img)
                    except Exception as img_err:
                        return JsonResponse({'status': 'error', 'message': "이미지 파일을 읽을 수 없습니다."}, status=400)
                
                # 5. AI 응답 생성
                response = model.generate_content(content)
                # 마크다운 특수문자 제거 및 정리
                bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
                
                # 6. 대화 내역 DB 저장
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message if user_message else "사진 분석 요청 📸", 
                    response=bot_response
                )
                
                # 7. 성공 응답 반환 (message와 reply 키 모두 제공하여 JS 에러 방지)
                return JsonResponse({
                    'status': 'success', 
                    'message': bot_response,
                    'reply': bot_response
                })
                
            except Exception as e:
                last_error = e
                # 할당량 초과(429) 시 다음 키로 즉시 이동
                if "429" in str(e) or "quota" in str(e).lower():
                    continue
                # 기타 에러 발생 시에도 로그를 남기고 다음 키 시도
                print(f"Gemini API Error with current key: {str(e)}")
                continue

        # 모든 키가 실패했을 경우 최종 에러 반환
        friendly_msg = "🐠 물물박사가 지금 너무 바빠서 답변을 못 드렸어요. 잠시 후 다시 물어봐 주세요!"
        return JsonResponse({
            'status': 'error', 
            'message': friendly_msg,
            'debug': str(last_error) if settings.DEBUG else None
        }, status=500)
    
    return JsonResponse({'status': 'error', 'message': "잘못된 접근입니다."}, status=405)