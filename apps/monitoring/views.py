from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Tank, EventLog, DeviceControl
from datetime import date, timedelta
import json
from django.views.decorators.http import require_POST

@login_required 
def dashboard(request):
    tank_data = []
    tanks = Tank.objects.filter(user=request.user)
    
    for tank in tanks:
        latest = tank.readings.order_by('-created_at').first()
        status = "정상"
        alerts = []

        if latest:
            temp_diff = abs(latest.temperature - tank.target_temp)
            if temp_diff >= 2.0:
                status = "DANGER"
                msg = f"온도 비정상! (현재:{latest.temperature}°C / 권장:{tank.target_temp}°C)"
                alerts.append(msg)
                EventLog.objects.get_or_create(tank=tank, level='DANGER', message=msg)

            ph_diff = abs(latest.ph - tank.target_ph)
            if ph_diff >= 0.5:
                if status != "DANGER": status = "WARNING"
                msg = f"pH 수치 주의! (현재:{latest.ph} / 권장:{tank.target_ph})"
                alerts.append(msg)
                EventLog.objects.get_or_create(tank=tank, level='WARNING', message=msg)
        
        d_day = None
        if tank.last_water_change:
            next_change = tank.last_water_change + timedelta(days=tank.water_change_period)
            d_day = (next_change - date.today()).days

        light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
        filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')
        logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:5]
        
        tank_data.append({
            'tank': tank, 
            'latest': latest, 
            'logs': logs,
            'status': status,
            'alerts': alerts,
            'light_on': light.is_on,
            'filter_on': filter_dev.is_on,
            'd_day': d_day,
        })
        
    return render(request, 'monitoring/dashboard.html', {'tank_data': tank_data})

@login_required
@require_POST
def apply_recommendation(request):
    """AI 추천 설정을 실제 어항에 적용"""
    try:
        data = json.loads(request.body)
        tank = Tank.objects.filter(user=request.user).first()
        if not tank:
            return JsonResponse({'status': 'error', 'message': '등록된 어항이 없습니다.'})

        tank.target_temp = float(data.get('temp', tank.target_temp))
        tank.target_ph = float(data.get('ph', tank.target_ph))
        tank.water_change_period = int(data.get('cycle', tank.water_change_period))
        tank.save()

        EventLog.objects.create(
            tank=tank, level='INFO',
            message=f"AI 추천 설정 적용: {tank.target_temp}°C, pH {tank.target_ph}, {tank.water_change_period}일 주기"
        )
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def perform_water_change(request, tank_id):
    if request.method == "POST":
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
        tank.last_water_change = date.today()
        tank.save()
        EventLog.objects.create(tank=tank, level='INFO', message="환수를 완료했습니다. 물이 깨끗해졌어요! 🌊")
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def toggle_device(request, tank_id):
    if request.method == "POST":
        device_type = request.POST.get('device_type')
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
        device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
        device.is_on = not device.is_on
        device.save()
        action = "켰습니다 💡" if device.is_on else "껐습니다 🌑"
        EventLog.objects.create(tank=tank, level='INFO', message=f"{device.get_type_display()}를 {action}")
        return JsonResponse({'status': 'success', 'is_on': device.is_on})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def add_tank(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            Tank.objects.create(
                user=request.user, 
                name=name, 
                capacity=request.POST.get('capacity', 0.0),
                fish_species=request.POST.get('fish_species', ""),
                target_temp=request.POST.get('target_temp', 25.0),
                target_ph=request.POST.get('target_ph', 7.0),
                water_change_period=request.POST.get('water_change_period', 7)
            )
            messages.success(request, f"'{name}' 어항이 성공적으로 등록되었습니다!")
            return redirect('home') # 메인 페이지로 이동
    return render(request, 'monitoring/add_tank.html')

@login_required
def camera_view(request):
    return render(request, 'monitoring/camera.html')

# [신규] 여러 개 어항 선택 삭제 기능
@login_required
@require_POST
def delete_tanks(request):
    tank_ids = request.POST.getlist('tank_ids[]')
    if tank_ids:
        deleted_count = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"{deleted_count[0]}개의 어항이 삭제되었습니다.")
    else:
        messages.warning(request, "삭제할 어항을 선택해주세요.")
    return redirect('home')