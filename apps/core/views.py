import json
import os
import unicodedata
import PIL.Image
import google.generativeai as genai
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from datetime import date, timedelta
from django.core.paginator import Paginator

from monitoring.models import Tank, SensorReading


# ── 사용 가능한 모델 목록 (2026-05 기준 확인됨) ──
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
]


def home(request):
    if request.user.is_authenticated:
        return index(request)
    return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})


def index(request):
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10)
    page_obj  = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        try:
            if latest and latest.temperature is not None:
                if abs(float(latest.temperature) - float(tank.target_temp or 26.0)) >= 2.0:
                    status = "DANGER"
        except (ValueError, TypeError):
            status = "UNKNOWN"

        d_day = 7
        if tank.last_water_change:
            period      = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day       = (next_change - date.today()).days

        tank_data.append({'tank': tank, 'latest': latest, 'status': status, 'd_day': d_day})

    return render(request, 'core/index.html', {
        'tank_data': tank_data,
        'page_obj':  page_obj,
        'is_guest':  False,
        'has_tanks': all_tanks.exists(),
    })


# ──────────────────────────────────────────────
# 챗봇 프롬프트
# ──────────────────────────────────────────────

def _build_prompt(user_message: str) -> str:
    return f"""너는 어항 관리 전문 도우미야. 질문 유형에 맞게 답해.

[말투 규칙]
- 존댓말 사용, 문장은 짧고 핵심만
- 이모지 사용 금지
- 인사말("안녕하세요" 등) 금지
- 어항 정보 없다는 언급 금지
- 문장을 절대 중간에 끊지 말고 완성된 문장으로 마무리

[질문 유형별 답변 형식]

1. 물고기 추천 (초보자용, 같이 키울 수 있는 물고기 등)
→ 추천 2~3종, 각각 아래 형식으로 완성해서 작성
   물고기명
   특징: 한 문장으로 완성
   수온: XX~XX도 / pH: X.X~X.X / 난이도: 하(또는 중, 상)

2. 수질/센서 설정 (수온, pH, 금붕어 수질 등)
→ 수치를 항목별로
   수온: XX~XX도
   pH: X.X~X.X
   DO: Xmg/L 이상
   탁도: XXNTU 이하

3. 어항 세팅 (처음 세팅, 여과기, 어항 크기 등)
→ 핵심 순서 또는 항목별로 3~5줄, 각 문장 완성해서 작성

4. 관리/질병 (먹이, 환수, 병 증상 등)
→ 원인 한 줄 + 해결책 위주로, 문장 완성해서 작성

5. 기타
→ 핵심만 3~5줄, 문장 완성해서 작성

질문: {user_message}"""


def _clean_reply(raw: str) -> str:
    """이모지 및 마크다운 제거 후 정리"""
    raw = raw.replace('**', '').replace('##', '').replace('# ', '').strip()

    cleaned = []
    for ch in raw:
        cp = ord(ch)
        if 0x1F300 <= cp <= 0x1FAFF:
            continue
        if 0x2600 <= cp <= 0x27BF:
            continue
        if 0x1F000 <= cp <= 0x1F02F:
            continue
        cleaned.append(ch)
    raw = ''.join(cleaned).strip()

    lines      = raw.split('\n')
    result     = []
    prev_blank = False
    for line in lines:
        if line.strip() == '':
            if not prev_blank:
                result.append('')
            prev_blank = True
        else:
            result.append(line.rstrip())
            prev_blank = False

    return '\n'.join(result).strip()


# ──────────────────────────────────────────────
# 챗봇 API
# ──────────────────────────────────────────────

@login_required
@require_POST
def chat_api(request):
    user_message = ""
    image_file   = None

    if request.content_type == 'application/json':
        try:
            user_message = json.loads(request.body).get('message', '').strip()
        except:
            pass
    else:
        user_message = request.POST.get('message', '').strip()
        image_file   = request.FILES.get('image')

    api_keys = [k for k in [
        os.getenv('GEMINI_API_KEY_1'),
        os.getenv('GEMINI_API_KEY_2'),
        os.getenv('GEMINI_API_KEY_3'),
        getattr(settings, 'GEMINI_API_KEY', None),
    ] if k]

    if not api_keys:
        return JsonResponse({'status': 'error', 'message': 'API 키가 없습니다.'}, status=500)

    last_error = ""
    for api_key in api_keys:
        for model_name in GEMINI_MODELS:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(model_name=model_name)

                prompt_parts = [_build_prompt(user_message)]
                if image_file:
                    image_file.seek(0)
                    prompt_parts.insert(0, PIL.Image.open(image_file))

                response = model.generate_content(
                    prompt_parts,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=600,   # 답변 잘림 방지
                        temperature=0.4,
                    ),
                    request_options={"timeout": 15},
                )

                if response and response.text:
                    reply = _clean_reply(response.text)

                    try:
                        ChatMessage = apps.get_model('chatbot', 'ChatMessage')
                        ChatMessage.objects.create(
                            user=request.user,
                            message=user_message or "(사진 분석)",
                            response=reply,
                        )
                    except:
                        pass

                    return JsonResponse({'status': 'success', 'reply': reply, 'response': reply})

            except Exception as e:
                last_error = str(e)
                continue

    return JsonResponse({'status': 'error', 'message': f'연결 실패: {last_error}'}, status=500)


# ──────────────────────────────────────────────
# 대화 내역 조회 API
# ──────────────────────────────────────────────

@login_required
def chat_history(request):
    """GET /chatbot/history/"""
    try:
        ChatMessage = apps.get_model('chatbot', 'ChatMessage')
        messages    = ChatMessage.objects.filter(
            user=request.user
        ).order_by('-created_at')[:50]

        history = [
            {
                "id":         m.id,
                "message":    m.message,
                "response":   m.response,
                "created_at": m.created_at.strftime("%m/%d %H:%M"),
            }
            for m in reversed(list(messages))
        ]
        return JsonResponse({"status": "ok", "history": history})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def chat_clear(request):
    """POST /chatbot/clear/"""
    try:
        ChatMessage = apps.get_model('chatbot', 'ChatMessage')
        count, _    = ChatMessage.objects.filter(user=request.user).delete()
        return JsonResponse({"status": "ok", "deleted": count})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)