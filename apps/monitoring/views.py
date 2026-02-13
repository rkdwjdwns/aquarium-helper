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
    """상세 대시보드: 특정 어항 상세 정보"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
        if not tank: return redirect('monitoring:add_tank')

    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:10]
    return render(request, 'monitoring/dashboard.html', {'tank': tank, 'latest': latest, 'logs': logs})

# --- CRUD 함수 ---

@login_required
def add_tank(request):
    """새 어항 추가"""
    if request.method == 'POST':
        name = request.POST.get('name')
        fish_species = request.POST.get('fish_species')
        capacity = request.POST.get('capacity')
        target_temp = float(request.POST.get('target_temp', 26.0))
        target_ph = float(request.POST.get('target_ph', 7.0))
        water_change_period = int(request.POST.get('water_change_period', 7))

        tank = Tank.objects.create(
            user=request.user, name=name, fish_species=fish_species, capacity=capacity,
            target_temp=target_temp, target_ph=target_ph, 
            water_change_period=water_change_period, last_water_change=date.today()
        )
        EventLog.objects.create(tank=tank, message=f"'{name}' 어항이 등록되었습니다.")
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
        tank.target_temp = float(request.POST.get('target_temp'))
        tank.target_ph = float(request.POST.get('target_ph'))
        tank.water_change_period = int(request.POST.get('water_change_period'))
        tank.save()
        return redirect('monitoring:tank_list')
    return render(request, 'monitoring/tank_form.html', {'tank': tank})

@login_required
@require_POST
def delete_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def delete_tanks(request):
    tank_ids = request.POST.getlist('tank_ids[]')
    Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
    return redirect('monitoring:index')

@login_required
def tank_list(request):
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4)
    page_obj = paginator.get_page(request.GET.get('page'))
    tank_data = [{'tank': t} for t in page_obj]
    return render(request, 'monitoring/tank_list.html', {'tank_data': tank_data, 'page_obj': page_obj})

# --- 장치 및 액션 API ---

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

@login_required
@require_POST
def perform_water_change(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    EventLog.objects.create(tank=tank, message="환수 완료 기록됨")
    return JsonResponse({'status': 'success'})

# --- ⚠️ 이번 에러의 원인이었던 누락된 AI 추천 적용 함수 복구 ---

@login_required
@require_POST
def apply_recommendation(request):
    """AI가 추천한 수치(온도, pH 등)를 실제 어항 설정에 반영"""
    try:
        data = json.loads(request.body)
        tank_id = data.get('tank_id')
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
        
        if 'target_temp' in data:
            tank.target_temp = data['target_temp']
        if 'target_ph' in data:
            tank.target_ph = data['target_ph']
            
        tank.save()
        EventLog.objects.create(tank=tank, message="AI 추천 설정이 적용되었습니다.")
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

# --- 기타 페이지 ---

@login_required
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    return render(request, 'monitoring/camera.html')