from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from .models import Tank, EventLog, DeviceControl
from datetime import date, timedelta
import json
from django.views.decorators.http import require_POST

@login_required 
def index(request):
    """메인 페이지: 어항 카드 목록 (Temp/pH 표시 및 제어)"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        alerts = []
        
        if latest:
            if abs(latest.temperature - tank.target_temp) >= 2.0:
                status = "DANGER"
                alerts.append(f"온도 비정상! ({latest.temperature}°C)")
            elif abs(latest.ph - tank.target_ph) >= 0.5:
                status = "WARNING"
                alerts.append(f"pH 주의! ({latest.ph})")

        # 환수 D-Day 계산 복구
        d_day = None
        if tank.last_water_change:
            next_change = tank.last_water_change + timedelta(days=tank.water_change_period)
            d_day = (next_change - date.today()).days

        # 장치 상태 복구
        light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
        filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')
        
        tank_data.append({
            'tank': tank, 
            'latest': latest, 
            'status': status,
            'alerts': alerts,
            'light_on': light.is_on,
            'filter_on': filter_dev.is_on,
            'd_day': d_day,
        })
        
    return render(request, 'monitoring/index.html', {
        'tank_data': tank_data,
        'page_obj': page_obj
    })

@login_required
def dashboard(request, tank_id=None):
    """상세 대시보드: 특정 어항의 정밀 수치 및 로그 확인"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
        if not tank: return redirect('monitoring:add_tank')

    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:10]
    return render(request, 'monitoring/dashboard.html', {'tank': tank, 'latest': latest, 'logs': logs})

@login_required
def tank_list(request):
    """어항 편집 센터: 목록 수정/삭제"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'monitoring/tank_list.html', {'tank_data': page_obj, 'page_obj': page_obj})

# --- 제어 및 CRUD API 복구 ---
@login_required
@require_POST
def toggle_device(request, tank_id):
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    EventLog.objects.create(tank=tank, message=f"{device.get_type_display()}를 {'켰습니다' if device.is_on else '껏습니다'}")
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def delete_tanks(request):
    tank_ids = request.POST.getlist('tank_ids[]')
    Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
    return redirect('monitoring:index')

# 카메라, 로그 뷰 등 기존 함수 유지
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

def camera_view(request):
    return render(request, 'monitoring/camera.html')