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
    """메인 대시보드: 어항별 상태 요약 및 제어"""
    tanks = Tank.objects.filter(user=request.user)
    
    if not tanks.exists():
        return render(request, 'monitoring/dashboard.html', {'tank_data': [], 'no_tanks': True})

    tank_data = []
    for tank in tanks:
        # readings related_name 확인 필요 (보통 readings)
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
        
    return render(request, 'monitoring/dashboard.html', {'tank_data': tank_data})

@login_required
def tank_list(request):
    """어항 관리 센터: 대시보드 스타일의 편집 모드 제공"""
    tanks = Tank.objects.filter(user=request.user)
    tank_data = []
    
    for tank in tanks:
        latest = tank.readings.order_by('-created_at').first()
        tank_data.append({
            'tank': tank,
            'latest': latest,
        })
    
    return render(request, 'monitoring/tank_list.html', {'tank_data': tank_data})

@login_required
def add_tank(request):
    """신규 어항 등록"""
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
    """어항 정보 수정"""
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

# --- 에러 해결의 핵심: 개별 삭제 함수 추가 ---
@login_required
def delete_tank(request, tank_id):
    """개별 어항 삭제 기능 (URL conf의 'delete_tank'와 일치)"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    name = tank.name
    tank.delete()
    messages.success(request, f"'{name}' 어항이 삭제되었습니다.")
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def delete_tanks(request):
    """일괄 삭제 로직"""
    tank_ids = request.POST.getlist('tank_ids')
    if tank_ids:
        deleted = Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
        messages.success(request, f"선택한 {deleted[0]}개의 어항을 삭제했습니다.")
    else:
        messages.warning(request, "삭제할 어항을 선택해주세요.")
    return redirect('monitoring:tank_list')

@login_required
def logs_view(request):
    """전체 이벤트 로그 조회"""
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    """카메라 뷰"""
    return render(request, 'monitoring/camera.html')

@login_required
@require_POST
def toggle_device(request, tank_id):
    """하드웨어 토글 API"""
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    status_str = "켰습니다 💡" if device.is_on else "껐습니다 🌑"
    EventLog.objects.create(tank=tank, level='INFO', message=f"{device.get_type_display()}를 {status_str}")
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    """환수 날짜 갱신 API"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    EventLog.objects.create(tank=tank, level='INFO', message="환수를 완료했습니다. 🌊")
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def apply_recommendation(request):
    """AI 추천 수치 반영 API"""
    try:
        data = json.loads(request.body)
        tank = Tank.objects.filter(user=request.user).first()
        if not tank:
            return JsonResponse({'status': 'error', 'message': '어항이 없습니다.'})

        tank.target_temp = float(data.get('temp', tank.target_temp))
        tank.target_ph = float(data.get('ph', tank.target_ph))
        tank.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})