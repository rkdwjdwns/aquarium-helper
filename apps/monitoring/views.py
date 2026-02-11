from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Tank, EventLog, DeviceControl

@login_required 
def dashboard(request):
    tank_data = []
    tanks = Tank.objects.filter(user=request.user)
    
    for tank in tanks:
        latest = tank.readings.order_by('-created_at').first()
        status = "정상"
        alerts = []

        if latest:
            # 1. 수질 분석 로직
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
        
        # 2. 장비 상태 가져오기 (없으면 자동 생성)
        light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
        filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')

        # 최근 로그 5개
        logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:5]
        
        tank_data.append({
            'tank': tank, 
            'latest': latest, 
            'logs': logs,
            'status': status,
            'alerts': alerts,
            'light_on': light.is_on,
            'filter_on': filter_dev.is_on,
        })
        
    return render(request, 'monitoring/dashboard.html', {'tank_data': tank_data})

@login_required
def toggle_device(request, tank_id):
    if request.method == "POST":
        device_type = request.POST.get('device_type')
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
        device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
        
        device.is_on = not device.is_on
        device.save()
        
        action = "켰습니다 💡" if device.is_on else "껐습니다 🌑"
        EventLog.objects.create(
            tank=tank,
            level='INFO',
            message=f"{device.get_type_display()}를 {action}"
        )
        
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
                user=request.user, name=name, 
                capacity=request.POST.get('capacity', 0.0),
                fish_species=request.POST.get('fish_species', ""),
                target_temp=request.POST.get('target_temp', 25.0),
                target_ph=request.POST.get('target_ph', 7.0)
            )
            messages.success(request, f"'{name}' 어항이 성공적으로 등록되었습니다!")
            return redirect('monitoring:dashboard')
    return render(request, 'monitoring/add_tank.html')

@login_required
def camera_view(request):
    return render(request, 'monitoring/camera.html')