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
    """기존 메인 페이지: 실시간 수치 확인 및 조작"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "정상"
        alerts = []
        
        if latest:
            if abs(latest.temperature - tank.target_temp) >= 2.0:
                status = "DANGER"
                alerts.append(f"온도 비정상! ({latest.temperature}°C)")
            if abs(latest.ph - tank.target_ph) >= 0.5:
                if status != "DANGER": status = "WARNING"
                alerts.append(f"pH 주의! ({latest.ph})")

        d_day = None
        if tank.last_water_change:
            next_change = tank.last_water_change + timedelta(days=tank.water_change_period)
            d_day = (next_change - date.today()).days

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
    """어항 관리 센터: 메인과 디자인을 통일한 편집/삭제 모드"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        tank_data.append({
            'tank': tank,
            'latest': latest,
        })
    
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
@require_POST
def delete_tanks(request):
    tank_ids = request.POST.getlist('tank_ids')
    if tank_ids:
        deleted = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"선택한 {deleted[0]}개의 어항을 삭제했습니다.")
    return redirect('monitoring:tank_list')

# ... 나머지 logs_view, camera_view 등 API 함수는 동일