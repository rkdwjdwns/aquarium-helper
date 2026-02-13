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
        
        # [방어코드] 수치가 비어있거나 타입이 안 맞아도 서버가 죽지 않게 try-except 적용
        if latest:
            try:
                temp = float(latest.temperature) if latest.temperature is not None else 0.0
                ph = float(latest.ph) if latest.ph is not None else 7.0
                t_temp = float(tank.target_temp) if tank.target_temp is not None else 26.0
                t_ph = float(tank.target_ph) if tank.target_ph is not None else 7.0
                
                if abs(temp - t_temp) >= 2.0:
                    status = "DANGER"
                    alerts.append("온도 비정상!")
                elif abs(ph - t_ph) >= 0.5:
                    status = "WARNING"
                    alerts.append("pH 주의!")
            except (ValueError, TypeError):
                pass # 계산 중 오류가 나면 무시하고 NORMAL 상태 유지

        # [방어코드] 환수 주기 계산 시 에러 방지
        d_day = None
        if tank.last_water_change:
            try:
                next_change = tank.last_water_change + timedelta(days=int(tank.water_change_period or 7))
                d_day = (next_change - date.today()).days
            except (ValueError, TypeError):
                pass

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
        
    # [주의] 이전에 확인한 대로 index 템플릿은 core에 있는 것을 사용합니다.
    return render(request, 'core/index.html', {
        'tank_data': tank_data,
        'page_obj': page_obj
    })

@login_required
def dashboard(request, tank_id=None):
    """상세 대시보드: 특정 어항 또는 첫 번째 어항 정보 표시"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
        if not tank:
            return redirect('monitoring:add_tank')

    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:10]
    
    return render(request, 'monitoring/dashboard.html', {
        'tank': tank,
        'latest': latest,
        'logs': logs
    })

@login_required
def add_tank(request):
    """새 어항 추가"""
    if request.method == 'POST':
        name = request.POST.get('name', '새 어항')
        fish_species = request.POST.get('fish_species', '')
        capacity = request.POST.get('capacity', '')
        
        # [방어코드] 입력값이 비어있을 때 발생하는 ValueError 방지
        try:
            target_temp = float(request.POST.get('target_temp') or 26.0)
        except ValueError:
            target_temp = 26.0
            
        try:
            target_ph = float(request.POST.get('target_ph') or 7.0)
        except ValueError:
            target_ph = 7.0
            
        try:
            water_change_period = int(request.POST.get('water_change_period') or 7)
        except ValueError:
            water_change_period = 7

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
        tank.name = request.POST.get('name', tank.name)
        tank.fish_species = request.POST.get('fish_species', tank.fish_species)
        tank.capacity = request.POST.get('capacity', tank.capacity)
        
        # [방어코드] 수정 시 빈칸 에러 방지
        try:
            tank.target_temp = float(request.POST.get('target_temp') or tank.target_temp)
            tank.target_ph = float(request.POST.get('target_ph') or tank.target_ph)
            tank.water_change_period = int(request.POST.get('water_change_period') or tank.water_change_period)
        except ValueError:
            pass # 변환 실패 시 기존 값 유지
            
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

@login_required
@require_POST
def toggle_device(request, tank_id):
    device_type = request.POST.get('device_type')
    if not device_type:
        return JsonResponse({'status': 'error', 'message': 'Device type is missing'}, status=400)
        
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

@login_required
@require_POST
def apply_recommendation(request):
    try:
        data = json.loads(request.body)
        tank_id = data.get('tank_id')
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
        if 'target_temp' in data: tank.target_temp = float(data['target_temp'])
        if 'target_ph' in data: tank.target_ph = float(data['target_ph'])
        tank.save()
        EventLog.objects.create(tank=tank, message="AI 추천 설정 적용됨")
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@login_required
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    return render(request, 'monitoring/camera.html')