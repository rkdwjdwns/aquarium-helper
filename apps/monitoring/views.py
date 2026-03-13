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

# 모델 임포트
from .models import Tank, EventLog, DeviceControl, SensorReading

# --- [대시보드 및 상세 페이지] ---

@login_required
def dashboard(request, tank_id=None):
    """특정 어항 상세 모니터링 대시보드"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
    
    readings = []
    if tank:
        readings = tank.readings.all().order_by('-created_at')[:20]
    
    return render(request, 'monitoring/dashboard.html', {
        'tank': tank, 
        'readings': readings
    })

# --- [어항 관리 CRUD] ---

@login_required
def tank_list(request):
    """어항 관리 목록 페이지"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {'tanks': all_tanks})

@login_required
def add_tank(request):
    """어항 등록 로직 (메인으로 리다이렉트)"""
    if request.method == 'POST':
        try:
            tank = Tank.objects.create(
                user=request.user,
                name=request.POST.get('name', '새 어항'),
                target_temp=float(request.POST.get('target_temp') or 26.0),
                water_change_period=int(request.POST.get('water_change_period') or 7),
                last_water_change=date.today()
            )
            messages.success(request, f"'{tank.name}' 어항이 등록되었습니다.")
            return redirect('/') 
        except Exception as e:
            messages.error(request, f"등록 중 오류 발생: {e}")
            
    return render(request, 'monitoring/tank_form.html', {'title': '어항 등록'})

@login_required
def edit_tank(request, tank_id):
    """어항 정보 수정"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        try:
            tank.name = request.POST.get('name', tank.name)
            tank.target_temp = float(request.POST.get('target_temp') or 26.0)
            tank.water_change_period = int(request.POST.get('water_change_period') or 7)
            tank.save()
            messages.success(request, "정보가 수정되었습니다.")
            return redirect('/')
        except Exception as e:
            messages.error(request, f"수정 중 오류 발생: {e}")
            
    return render(request, 'monitoring/tank_form.html', {'tank': tank, 'title': '어항 수정'})

@login_required
def delete_tank(request, tank_id):
    """단일 어항 삭제"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    messages.success(request, "어항이 삭제되었습니다.")
    return redirect('/')

@login_required
@require_POST
def delete_tanks(request):
    """일괄 어항 삭제"""
    tank_ids = request.POST.getlist('tank_ids')
    if tank_ids:
        deleted_count, _ = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"{deleted_count}개의 어항이 삭제되었습니다.")
    return redirect('/')

# --- [장치 제어 및 부가 기능] ---

@login_required
@require_POST
def toggle_device(request, tank_id):
    """스마트 플러그 및 장치 제어 토글"""
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, created = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    
    # 제어 로그 기록
    EventLog.objects.create(
        tank=tank, 
        event_type="DEVICE_CONTROL", 
        message=f"{device_type} 장치가 {'켜짐' if device.is_on else '꺼짐'} 상태로 변경되었습니다."
    )
    
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    """환수 작업 완료 기록"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    
    EventLog.objects.create(tank=tank, event_type="WATER_CHANGE", message="환수 완료 기록됨")
    return JsonResponse({'status': 'success'})

@login_required
def logs_view(request):
    """시스템 및 사용자 로그 보기"""
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    """실시간 카메라 뷰 (전체 어항)"""
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'monitoring/camera.html', {'tanks': tanks})

# --- [AI 리포트 및 챗봇] ---

@login_required
def ai_report_list(request):
    """AI 리포트 리스트 페이지"""
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'reports/report_list.html', {
        'first_tank': tanks.first(), 
        'tanks': tanks
    })

def get_chat_message_model():
    """챗봇 모델 지연 로딩"""
    try:
        return apps.get_model('chatbot', 'ChatMessage')
    except (LookupError, ValueError):
        return None

@login_required
@require_POST
def chat_api(request):
    """AI 챗봇 API (monitoring 앱 전용)"""
    # core/views.py의 chat_api와 동일한 로직 적용 가능
    # 여기서는 정준님이 monitoring 앱에서도 챗봇을 호출할 경우를 대비해 유지합니다.
    try:
        user_message = ""
        image_file = None
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()
        else:
            user_message = request.POST.get('message', '').strip()
            image_file = request.FILES.get('image')

        # [실행 로직 생략 - core/views.py의 chat_api와 동일하게 설정 가능]
        # 필요시 core.views.chat_api를 임포트해서 사용하거나 로직을 복사하세요.
        pass
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)