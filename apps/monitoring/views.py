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
    """메인 페이지: 어항 카드 목록 (깔끔한 요약 버전)"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        # readings는 모델의 related_name 설정에 따라 다를 수 있으니 확인 필요
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        
        # 수온/pH 상태 체크 로직 (가이드라인 반영)
        if latest:
            try:
                temp = float(latest.temperature or 0)
                t_temp = float(tank.target_temp or 26.0)
                # 목표 온도보다 2도 이상 차이 나면 위험 상태
                if abs(temp - t_temp) >= 2.0: 
                    status = "DANGER"
            except (ValueError, TypeError): 
                pass

        # 환수 D-Day 계산
        d_day = None
        if tank.last_water_change:
            try:
                period = int(tank.water_change_period or 7)
                next_change = tank.last_water_change + timedelta(days=period)
                d_day = (next_change - date.today()).days
            except (ValueError, TypeError):
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
def dashboard(request, tank_id=None):
    """상세 대시보드: 수질 가이드라인 및 제어 기능 포함"""
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = Tank.objects.filter(user=request.user).first()
        if not tank:
            return redirect('monitoring:add_tank')

    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:5]
    
    # 장치 상태 가져오기 (템플릿의 light_on, filter_on 변수와 일치)
    light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
    filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')
    
    # 환수 D-Day 재계산
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
    """새 어항 추가 (방어코드 강화)"""
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
            tank.target_temp = float(request.POST.get('target_temp') or tank.target_temp)
            tank.target_ph = float(request.POST.get('target_ph') or tank.target_ph)
            tank.save()
            messages.success(request, "어항 정보가 수정되었습니다.")
            return redirect('monitoring:tank_list')
        except ValueError:
            messages.error(request, "수치 입력 형식이 올바르지 않습니다.")
            
    return render(request, 'monitoring/tank_form.html', {'tank': tank})

@login_required
@require_POST
def delete_tank(request, tank_id):
    """단일 어항 삭제 (URL name='delete_tank'와 매칭)"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.delete()
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def delete_tanks(request):
    """여러 어항 선택 삭제"""
    tank_ids = request.POST.getlist('tank_ids[]')
    if tank_ids:
        Tank.objects.filter(id__in=tank_ids, user=request.user).delete()
    return redirect('monitoring:tank_list')

@login_required
@require_POST
def toggle_device(request, tank_id):
    """비동기 장치 제어 API (조명/여과기)"""
    device_type = request.POST.get('device_type')
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    device, _ = DeviceControl.objects.get_or_create(tank=tank, type=device_type)
    device.is_on = not device.is_on
    device.save()
    
    status_str = "ON" if device.is_on else "OFF"
    EventLog.objects.create(tank=tank, message=f"{device.get_type_display()} 장치가 {status_str} 되었습니다.")
    
    return JsonResponse({'status': 'success', 'is_on': device.is_on})

@login_required
@require_POST
def perform_water_change(request, tank_id):
    """대시보드 환수 완료 버튼 처리"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    EventLog.objects.create(tank=tank, message="수동 환수 완료가 기록되었습니다.")
    return JsonResponse({'status': 'success'})

@login_required
def tank_list(request):
    """어항 편집 센터 리스트 표시"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    tank_data = [{'tank': t} for t in all_tanks]
    return render(request, 'monitoring/tank_list.html', {'tank_data': tank_data})

@login_required
def logs_view(request):
    """전체 활동 로그 보기"""
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    """실시간 카메라 화면"""
    return render(request, 'monitoring/camera.html')