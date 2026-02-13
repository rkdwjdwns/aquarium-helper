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
    """메인 페이지: 어항 카드 목록 및 요약 정보"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        alerts = []
        
        # 최신 수치 기반 상태 체크
        if latest:
            if abs((latest.temperature or 0) - tank.target_temp) >= 2.0:
                status = "DANGER"
                alerts.append("온도 비정상!")
            elif abs((latest.ph or 7.0) - tank.target_ph) >= 0.5:
                status = "WARNING"
                alerts.append("pH 주의!")

        # 환수 D-Day 계산
        d_day = None
        if tank.last_water_change:
            next_change = tank.last_water_change + timedelta(days=tank.water_change_period)
            d_day = (next_change - date.today()).days

        # 장치 상태 가져오기 (없으면 생성)
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

# ... (나머지 dashboard, add_tank, edit_tank 함수들은 기존과 동일하게 유지)

@login_required
@require_POST
def toggle_device(request, tank_id):
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    EventLog.objects.create(tank=tank, message=f"{device.get_type_display()} 제어됨")
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

# ... (perform_water_change, apply_recommendation 등 나머지 함수 유지)