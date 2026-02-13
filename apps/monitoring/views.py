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
            period = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day = (next_change - date.today()).days
        
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
    
    light, _ = DeviceControl.objects.get_or_create(tank=tank, type='LIGHT')
    filter_dev, _ = DeviceControl.objects.get_or_create(tank=tank, type='FILTER')
    
    is_water_changed_today = (tank.last_water_change == date.today())

    d_day = 7
    if tank.last_water_change:
        try:
            period = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day = (next_change - date.today()).days
        except: pass

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
            return redirect('monitoring:index')
        except Exception as e:
            return render(request, 'monitoring/tank_form.html', {'error': str(e)})
    return render(request, 'monitoring/tank_form.html')

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
        
        # 실제 AI 연동 전 기본 분석 로직
        if "온도" in user_message:
            reply = "현재 수온을 체크 중입니다. 설정하신 목표 온도와 비교해 적정 수준을 유지하고 있는지 확인해 보세요!"
        elif "환수" in user_message:
            reply = "환수는 물고기들의 건강에 직결됩니다. 주기에 맞춰 20-30% 정도 갈아주시는 것을 추천해요."
        else:
            reply = f"질문하신 '{user_message}'에 대해 분석한 결과, 현재 어항 수질과 환경은 전반적으로 안정적입니다!"
            
        return JsonResponse({'reply': reply})
    except:
        return JsonResponse({'reply': '오류가 발생했습니다. 잠시 후 다시 시도해주세요.'}, status=400)

@login_required
def ai_report_list(request):
    """AI 리포트 목록"""
    tanks = Tank.objects.filter(user=request.user)
    # 실제 Report 모델 쿼리 필요 시 추가
    return render(request, 'reports/report_list.html', {
        'first_tank': tanks.first(),
        'tanks': tanks
    })

@login_required
def tank_list(request):
    """어항 편집 센터"""
    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    return render(request, 'monitoring/tank_list.html', {'tank_data': [{'tank': t} for t in all_tanks]})

@login_required
def logs_view(request):
    logs = EventLog.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'monitoring/logs.html', {'logs': logs})