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
    """메인 페이지: 어항 카드 목록 (Paginator 적용)"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 4) 
    page_obj = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        
        # 온도 분석 (None 처리 보완)
        if latest and latest.temperature is not None:
            try:
                temp = float(latest.temperature)
                t_temp = float(tank.target_temp or 26.0)
                if abs(temp - t_temp) >= 2.0: 
                    status = "DANGER"
            except (ValueError, TypeError): 
                pass

        # D-Day 계산 (None 처리 보완)
        d_day = 7
        if tank.last_water_change:
            try:
                period = int(tank.water_change_period or 7)
                next_change = tank.last_water_change + timedelta(days=period)
                d_day = (next_change - date.today()).days
            except (ValueError, TypeError):
                pass
        
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
    """상세 대시보드: 어항 선택 기능 포함"""
    user_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    
    if tank_id:
        tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    else:
        tank = user_tanks.first()
        if not tank:
            return redirect('monitoring:add_tank')

    latest = tank.readings.order_by('-created_at').first()
    logs = EventLog.objects.filter(tank=tank).order_by('-created_at')[:5]
    
    # 장치 제어 객체 안전하게 가져오기
    light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
    filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')
    
    is_water_changed_today = (tank.last_water_change == date.today())

    # D-Day 계산 안전화
    d_day = 7
    if tank.last_water_change:
        try:
            period = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day = (next_change - date.today()).days
        except (ValueError, TypeError, Exception): 
            pass

    return render(request, 'monitoring/dashboard.html', {
        'tank': tank,
        'user_tanks': user_tanks,
        'latest': latest,
        'logs': logs,
        'light_on': light.is_on,
        'filter_on': filter_dev.is_on,
        'd_day': d_day,
        'is_water_changed_today': is_water_changed_today
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
                target_temp=float(request.POST.get('target_temp') or 26.0),
                water_change_period=int(request.POST.get('water_change_period') or 7),
                last_water_change=date.today()
            )
            EventLog.objects.create(tank=tank, message=f"'{tank.name}' 어항이 등록되었습니다.")
            messages.success(request, f"'{tank.name}' 어항이 추가되었습니다.")
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
            tank.name = request.POST.get('name')
            tank.fish_species = request.POST.get('fish_species')
            tank.target_temp = float(request.POST.get('target_temp', 26.0))
            tank.water_change_period = int(request.POST.get('water_change_period', 7))
            tank.save()
            messages.success(request, "어항 정보가 수정되었습니다.")
            return redirect('monitoring:dashboard', tank_id=tank.id)
        except Exception as e:
            return render(request, 'monitoring/tank_form.html', {'tank': tank, 'error': str(e)})
    return render(request, 'monitoring/tank_form.html', {'tank': tank})

@login_required
def delete_tank(request, tank_id):
    """어항 삭제"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank_name = tank.name
    tank.delete()
    messages.success(request, f"'{tank_name}' 어항이 삭제되었습니다.")
    return redirect('monitoring:index')

@login_required
@require_POST
def toggle_device(request, tank_id):
    """장치 제어 (조명/여과기)"""
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
    """환수 완료 처리"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    tank.last_water_change = date.today()
    tank.save()
    EventLog.objects.create(tank=tank, message="환수 완료가 기록되었습니다.")
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def chat_api(request):
    """챗봇 분석 API"""
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '')
        
        if "온도" in user_message:
            reply = "현재 수온은 설정하신 목표 온도와 비교하여 모니터링 중입니다. 센서 데이터를 확인해 보세요!"
        elif "환수" in user_message:
            reply = "환수 주기가 다가오면 제가 알려드릴게요. 보통 주 1회 30% 환수를 권장합니다."
        else:
            reply = f"질문하신 '{user_message}'에 대해 확인해본 결과, 현재 시스템상 어항 수질은 양호한 편입니다!"
            
        return JsonResponse({'reply': reply})
    except Exception:
        return JsonResponse({'reply': '죄송합니다. 메시지 처리 중 오류가 발생했습니다.'}, status=400)

@login_required
def ai_report_list(request):
    """AI 리포트 목록"""
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'reports/report_list.html', {
        'first_tank': tanks.first(),
        'tanks': tanks
    })

@login_required
def tank_list(request):
    """어항 관리 센터 (500 에러 방지 보완)"""
    try:
        all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
        # 템플릿의 {% for item in tank_data %} 구조를 위해 딕셔너리 리스트 생성
        tank_data = [{'tank': t} for t in all_tanks]
        return render(request, 'monitoring/tank_list.html', {
            'tank_data': tank_data,
            'tanks': all_tanks  # 대안으로 사용할 수 있도록 직접 쿼리셋도 전달
        })
    except Exception as e:
        return render(request, 'monitoring/tank_list.html', {'error': str(e)})

@login_required
def logs_view(request):
    """전체 로그 보기"""
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})

@login_required
def camera_view(request):
    """실시간 카메라 보기"""
    tanks = Tank.objects.filter(user=request.user)
    return render(request, 'monitoring/camera.html', {'tanks': tanks})