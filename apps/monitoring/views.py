import json
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
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        
        if latest:
            try:
                temp = float(latest.temperature or 0)
                t_temp = float(tank.target_temp or 26.0)
                if abs(temp - t_temp) >= 2.0: 
                    status = "DANGER"
            except (ValueError, TypeError): 
                pass

        d_day = 7
        if tank.last_water_change:
            try:
                period = int(tank.water_change_period or 7)
                next_change = tank.last_water_change + timedelta(days=period)
                d_day = (next_change - date.today()).days
            except:
                d_day = 7
        
        tank_data.append({
            'tank': tank, 
            'latest': latest, 
            'status': status,
            'd_day': d_day,
        })
        
    return render(request, 'core/index.html', {
        'tank_data': tank_data,
        'page_obj': page_obj
    })

@login_required
def ai_report_list(request):
    """AI 리포트 목록 페이지"""
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'reports/report_list.html', {'tanks': tanks})

@login_required
def dashboard(request, tank_id=None):
    """상세 대시보드"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
        if not tank:
            return redirect('monitoring:add_tank')

    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:5]
    
    light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
    filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')
    
    d_day = 7
    if tank.last_water_change:
        try:
            period = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day = (next_change - date.today()).days
        except:
            pass

    return render(request, 'monitoring/dashboard.html', {
        'tank': tank,
        'latest': latest,
        'logs': logs,
        'light_on': light.is_on,
        'filter_on': filter_dev.is_on,
        'd_day': d_day
    })

@login_required
def add_tank(request):
    """새 어항 추가"""
    if request.method == 'POST':
        try:
            tank = Tank.objects.create(
                user=request.user,
                name=request.POST.get('name', '새 어항'),
                fish_species=request.POST.get('fish_species', ''),
                capacity=request.POST.get('capacity', ''),
                target_temp=float(request.POST.get('target_temp') or 26.0),
                target_ph=float(request.POST.get('target_ph') or 7.0),
                water_change_period=int(request.POST.get('water_change_period') or 7),
                last_water_change=date.today()
            )
            EventLog.objects.create(tank=tank, message=f"'{tank.name}' 어항이 등록되었습니다.")
            return redirect('monitoring:index')
        except Exception as e:
            return render(request, 'monitoring/tank_form.html', {'error': str(e)})
    return render(request, 'monitoring/tank_form.html')

@login_required
def edit_tank(request, tank_id):
    """어항 정보 수정"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    if request.method == 'POST':
        try:
            tank.name = request.POST.get('name', tank.name)
            tank.fish_species = request.POST.get('fish_species', tank.fish_species)
            t_temp = request.POST.get('target_temp')
            t_ph = request.POST.get('target_ph')
            if t_temp: tank.target_temp = float(t_temp)
            if t_ph: tank.target_ph = float(t_ph)
            tank.save()
            messages.success(request, "수정되었습니다.")
            return redirect('monitoring:tank_list')
        except (ValueError, TypeError):
            messages.error(request, "수치 형식이 올바르지 않습니다.")
    return render(request, 'monitoring/tank_form.html', {'tank': tank})

@login_required
@require_POST
def delete_tank(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def toggle_device(request, tank_id):
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    status_str = "켜짐" if device.is_on else "꺼짐"
    EventLog.objects.create(tank=tank, message=f"{device.get_type_display()}가 {status_str}")
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    EventLog.objects.create(tank=tank, message="환수 완료가 기록되었습니다.")
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def chat_api(request):
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '')
        return JsonResponse({'reply': f"'{user_message}'에 대한 분석 결과, 수질이 양호합니다!"})
    except:
        return JsonResponse({'reply': '오류가 발생했습니다.'}, status=400)

@login_required
def tank_list(request):
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {'tank_data': [{'tank': t} for t in all_tanks]})

@login_required
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    return render(request, 'monitoring/camera.html')