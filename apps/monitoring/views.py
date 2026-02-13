import json
import os
import PIL.Image
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.conf import settings
from django.views.decorators.http import require_POST
from django.apps import apps
from datetime import date, timedelta

# 현재 앱의 모델 임포트
from .models import Tank, EventLog, DeviceControl

# ChatMessage 모델을 안전하게 가져오는 함수 (RuntimeError 방지)
def get_chat_message_model():
    try:
        return apps.get_model('chatbot', 'ChatMessage')
    except (LookupError, ValueError):
        try:
            return apps.get_model('apps.chatbot', 'ChatMessage')
        except:
            return None

# --- [메인 기능: 대시보드 및 리스트] ---

@login_required 
def index(request):
    """메인 페이지: 어항 카드 목록"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        if latest and latest.temperature is not None:
            try:
                if abs(float(latest.temperature) - float(tank.target_temp or 26.0)) >= 2.0: 
                    status = "DANGER"
            except: pass

        d_day = 7
        if tank.last_water_change:
            try:
                period = int(tank.water_change_period or 7)
                next_change = tank.last_water_change + timedelta(days=period)
                d_day = (next_change - date.today()).days
            except: pass
        
        tank_data.append({'tank': tank, 'latest': latest, 'status': status, 'd_day': d_day})
        
    return render(request, 'core/index.html', {'tank_data': tank_data, 'page_obj': page_obj})

@login_required
def dashboard(request, tank_id=None):
    """상세 대시보드"""
    user_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    
    # 어항이 하나도 없을 경우 추가 페이지로 리다이렉트
    if not user_tanks.exists():
        return redirect('monitoring:add_tank')

    tank = get_object_or_404(Tank, id=tank_id, user=request.user) if tank_id else user_tanks.first()
    
    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:5]
    light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
    filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')
    
    d_day = 7
    if tank.last_water_change:
        try:
            next_change = tank.last_water_change + timedelta(days=int(tank.water_change_period or 7))
            d_day = (next_change - date.today()).days
        except: pass

    return render(request, 'monitoring/dashboard.html', {
        'tank': tank, 'user_tanks': user_tanks, 'latest': latest, 'logs': logs,
        'light_on': light.is_on, 'filter_on': filter_dev.is_on, 'd_day': d_day,
        'is_water_changed_today': (tank.last_water_change == date.today())
    })

# --- [핵심: 주인님의 멀티 API 키 Gemini 챗봇 로직] ---

@login_required
@require_POST
def chat_api(request):
    """텍스트 + 이미지 분석 지원 (닉네임 인사말 적용)"""
    user_message = request.POST.get('message', '').strip()
    image_file = request.FILES.get('image') 
    
    if not user_message and not image_file:
        return JsonResponse({'status': 'error', 'message': "궁금한 점을 입력해 주세요! 🌊"}, status=400)
    
    # 닉네임 가져오기
    display_name = getattr(request.user, 'nickname', request.user.first_name if request.user.first_name else request.user.username)
    
    api_keys = [
        getattr(settings, 'GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY_1')),
        getattr(settings, 'GEMINI_API_KEY_2', os.environ.get('GEMINI_API_KEY_2')),
        getattr(settings, 'GEMINI_API_KEY_3', os.environ.get('GEMINI_API_KEY_3')),
    ]
    valid_keys = [k for k in api_keys if k]
    
    if not valid_keys:
        return JsonResponse({'status': 'error', 'message': "API 키가 설정되지 않았습니다."}, status=500)

    last_error = None
    for current_key in valid_keys:
        try:
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=(
                    f"당신은 '어항 도우미'입니다. 다음 규칙을 엄격히 지키세요:\n"
                    f"1. 첫 인사는 반드시 '{display_name}님! 🌊'으로 시작하세요.\n"
                    f"2. 답변에서 별표(*), 대시(-), 해시태그(#) 같은 특수 기호는 절대 쓰지 마세요.\n"
                    f"3. 아주 쉬운 말로 설명하고, 답변은 짧고 간결하게 핵심만 말하세요.\n"
                    f"4. 가독성을 위해 줄바꿈을 아주 자주 하세요.\n"
                    f"5. 답변 끝에는 반드시 다음 형식을 포함하세요: [SETTING: temp=온도, ph=수치, cycle=환수주기]"
                )
            )
            
            content = []
            if user_message: content.append(user_message)
            if image_file: content.append(PIL.Image.open(image_file))
            
            response = model.generate_content(content)
            bot_response = response.text.replace('*', '').replace('#', '').replace('-', ' ').strip()
            
            # 모델 저장
            ChatMessage = get_chat_message_model()
            if ChatMessage:
                ChatMessage.objects.create(
                    user=request.user, 
                    message=user_message if user_message else "사진 분석 요청 📸", 
                    response=bot_response
                )
            
            return JsonResponse({'status': 'success', 'reply': bot_response, 'message': bot_response})
            
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                continue 
            last_error = e
            continue

    return JsonResponse({'status': 'error', 'message': "물물박사가 잠시 자리를 비웠어요. 잠시 후 다시 시도해 주세요!"}, status=500)

# --- [어항 편집 및 관리 기능: 500 에러 방어] ---

@login_required
def tank_list(request):
    """어항 관리 센터"""
    try:
        all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
        tank_data = [{'tank': t} for t in all_tanks]
        return render(request, 'monitoring/tank_list.html', {
            'tank_data': tank_data,
            'tanks': all_tanks
        })
    except Exception as e:
        return render(request, 'monitoring/tank_list.html', {'error': str(e)})

@login_required
@require_POST
def delete_tanks(request):
    """선택 삭제 처리"""
    tank_ids = request.POST.getlist('tank_ids[]')
    if tank_ids:
        deleted_count, _ = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"{deleted_count}개의 어항이 삭제되었습니다.")
    return redirect('monitoring:tank_list')

@login_required
def add_tank(request):
    """어항 추가 (완료 후 메인 화면으로 이동)"""
    if request.method == 'POST':
        try:
            name = request.POST.get('name', '새 어항').strip() or '새 어항'
            species = request.POST.get('fish_species', '').strip()
            temp = float(request.POST.get('target_temp') or 26.0)
            period = int(request.POST.get('water_change_period') or 7)
            
            tank = Tank.objects.create(
                user=request.user,
                name=name,
                fish_species=species,
                target_temp=temp,
                water_change_period=period,
                last_water_change=date.today()
            )
            messages.success(request, f"'{tank.name}' 어항이 생성되었습니다.")
            # [수정] 메인 화면(index)으로 이동
            return redirect('monitoring:index')
        except Exception as e:
            return render(request, 'monitoring/tank_form.html', {'error': f"입력값을 확인해주세요: {e}", 'title': '어항 등록'})
            
    return render(request, 'monitoring/tank_form.html', {'title': '어항 등록'})

@login_required
def edit_tank(request, tank_id):
    """어항 수정 (완료 후 메인 화면으로 이동)"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        try:
            tank.name = request.POST.get('name', tank.name).strip()
            tank.fish_species = request.POST.get('fish_species', tank.fish_species).strip()
            tank.target_temp = float(request.POST.get('target_temp') or 26.0)
            tank.water_change_period = int(request.POST.get('water_change_period') or 7)
            tank.save()
            messages.success(request, f"'{tank.name}' 정보가 수정되었습니다.")
            # [수정] 메인 화면(index)으로 이동
            return redirect('monitoring:index')
        except Exception as e:
            return render(request, 'monitoring/tank_form.html', {'tank': tank, 'error': f"수정 실패: {e}", 'title': '어항 수정'})
            
    return render(request, 'monitoring/tank_form.html', {'tank': tank, 'title': '어항 수정'})

@login_required
def delete_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    messages.success(request, "어항이 삭제되었습니다.")
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def toggle_device(request, tank_id):
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on; device.save()
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today(); tank.save()
    return JsonResponse({'status': 'success'})

@login_required
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'monitoring/camera.html', {'tanks': tanks})

@login_required
def ai_report_list(request):
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'reports/report_list.html', {'first_tank': tanks.first(), 'tanks': tanks})