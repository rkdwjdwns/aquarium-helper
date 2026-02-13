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
def dashboard(request):
    """실시간 대시보드: 수치 확인 및 장치 제어"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    tank_data = []
    for tank in page_obj:
        # 템플릿의 item.latest와 매칭
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        alerts = []
        
        if latest:
            # 위험/경고 로직
            if abs(latest.temperature - tank.target_temp) >= 2.0:
                status = "DANGER"
                alerts.append(f"온도 비정상! ({latest.temperature}°C)")
            elif abs(latest.ph - tank.target_ph) >= 0.5:
                status = "WARNING"
                alerts.append(f"pH 주의! ({latest.ph})")

        # 환수 D-Day 계산
        d_day = None
        if tank.last_water_change:
            next_change = tank.last_water_change + timedelta(days=tank.water_change_period)
            d_day = (next_change - date.today()).days

        # 템플릿의 light_on, filter_on과 매칭
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
            'logs': EventLog.objects.filter(tank=tank).order_by('-created_at')[:5]
        })
        
    return render(request, 'monitoring/dashboard.html', {
        'tank_data': tank_data,
        'page_obj': page_obj
    })

@login_required
def tank_list(request):
    """어항 관리 센터 (편집/삭제)"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        tank_data.append({'tank': tank, 'latest': latest})
    
    return render(request, 'monitoring/tank_list.html', {
        'tank_data': tank_data,
        'page_obj': page_obj
    })

@login_required
def add_tank(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            Tank.objects.create(
                user=request.user, 
                name=name, 
                capacity=request.POST.get('capacity') or 0.0,
                fish_species=request.POST.get('fish_species', ""),
                target_temp=request.POST.get('target_temp') or 25.0,
                target_ph=request.POST.get('target_ph') or 7.0,
                water_change_period=request.POST.get('water_change_period') or 7
            )
            messages.success(request, f"'{name}' 어항이 등록되었습니다!")
            return redirect('monitoring:tank_list')
    return render(request, 'monitoring/add_tank.html')

@login_required
def edit_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        tank.name = request.POST.get('name', tank.name)
        tank.fish_species = request.POST.get('fish_species', tank.fish_species)
        tank.capacity = float(request.POST.get('capacity') or tank.capacity)
        tank.target_temp = float(request.POST.get('target_temp') or tank.target_temp)
        tank.target_ph = float(request.POST.get('target_ph') or tank.target_ph)
        tank.save()
        messages.success(request, f"'{tank.name}' 정보가 수정되었습니다.")
        return redirect('monitoring:tank_list')
    return render(request, 'monitoring/edit_tank.html', {'tank': tank})

@login_required
def delete_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    name = tank.name
    tank.delete()
    messages.success(request, f"'{name}' 어항이 삭제되었습니다.")
    return redirect('monitoring:tank_list')

@login_required
def logs_view(request):
    """전체 활동 로그"""
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    """카메라 스트리밍"""
    return render(request, 'monitoring/camera.html')

@login_required
@require_POST
def toggle_device(request, tank_id):
    """장치 On/Off API"""
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    
    status_msg = "켰습니다 💡" if device.is_on else "껐습니다 🌑"
    EventLog.objects.create(tank=tank, message=f"{device.get_type_display()}를 {status_msg}")
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    """환수 완료 API"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    EventLog.objects.create(tank=tank, message="환수를 완료했습니다. 🌊")
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def apply_recommendation(request):
    """AI 추천 수치 적용 API"""
    try:
        data = json.loads(request.body)
        tank = Tank.objects.filter(user=request.user).first()
        if tank:
            tank.target_temp = float(data.get('temp', tank.target_temp))
            tank.target_ph = float(data.get('ph', tank.target_ph))
            tank.save()
            return JsonResponse({'status': 'success'})
        return JsonResponse({'status': 'error', 'message': '어항을 찾을 수 없습니다.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})