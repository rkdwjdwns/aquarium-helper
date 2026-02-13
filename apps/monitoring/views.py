from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from .models import Tank, EventLog, DeviceControl
from datetime import date, timedelta
from django.views.decorators.http import require_POST

@login_required 
def index(request):
    """메인 페이지: 어항 카드 목록"""
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
                alerts.append(f"온도 비정상!")
            elif abs(latest.ph - tank.target_ph) >= 0.5:
                status = "WARNING"
                alerts.append(f"pH 주의!")

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
        })
        
    return render(request, 'monitoring/index.html', {
        'tank_data': tank_data,
        'page_obj': page_obj
    })

@login_required
def dashboard(request, tank_id=None):
    """상세 대시보드"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
        if not tank: return redirect('monitoring:add_tank')

    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:10]
    return render(request, 'monitoring/dashboard.html', {'tank': tank, 'latest': latest, 'logs': logs})

# --- ⚠️ 아래는 누락되었던 핵심 CRUD 함수들입니다 ---

@login_required
def add_tank(request):
    """새 어항 추가"""
    if request.method == 'POST':
        name = request.POST.get('name')
        fish_species = request.POST.get('fish_species')
        capacity = request.POST.get('capacity')
        target_temp = request.POST.get('target_temp', 26.0)
        target_ph = request.POST.get('target_ph', 7.0)
        water_change_period = request.POST.get('water_change_period', 7)

        tank = Tank.objects.create(
            user=request.user,
            name=name,
            fish_species=fish_species,
            capacity=capacity,
            target_temp=target_temp,
            target_ph=target_ph,
            water_change_period=water_change_period,
            last_water_change=date.today()
        )
        EventLog.objects.create(tank=tank, message=f"'{name}' 어항이 새로 등록되었습니다.")
        return redirect('monitoring:index')
    return render(request, 'monitoring/tank_form.html')

@login_required
def edit_tank(request, tank_id):
    """어항 정보 수정"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        tank.name = request.POST.get('name')
        tank.fish_species = request.POST.get('fish_species')
        tank.capacity = request.POST.get('capacity')
        tank.target_temp = request.POST.get('target_temp')
        tank.target_ph = request.POST.get('target_ph')
        tank.water_change_period = request.POST.get('water_change_period')
        tank.save()
        messages.success(request, "어항 정보가 수정되었습니다.")
        return redirect('monitoring:tank_list')
    return render(request, 'monitoring/tank_form.html', {'tank': tank})

@login_required
@require_POST
def delete_tank(request, tank_id):
    """어항 단일 삭제"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def delete_tanks(request):
    """어항 다중 삭제 (메인 페이지용)"""
    tank_ids = request.POST.getlist('tank_ids[]')
    if tank_ids:
        Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
    return redirect('monitoring:index')

@login_required
def tank_list(request):
    """어항 관리 목록"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # 템플릿 호환성을 위해 tank_data 구조를 index와 맞춤
    tank_data = [{'tank': tank} for tank in page_obj]
    return render(request, 'monitoring/tank_list.html', {
        'tank_data': tank_data, 
        'page_obj': page_obj
    })

# --- 제어 및 기타 뷰 ---

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
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    return render(request, 'monitoring/camera.html')