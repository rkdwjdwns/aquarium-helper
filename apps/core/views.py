from django.shortcuts import render
from datetime import date, timedelta
from django.core.paginator import Paginator

from apps.monitoring.models import Tank, SensorReading


def home(request):
    if request.user.is_authenticated:
        return index(request)
    return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})


def index(request):
    if not request.user.is_authenticated:
        return render(request, 'core/index.html', {'tank_data': [], 'is_guest': True})

    all_tanks = Tank.objects.filter(user=request.user).order_by('-id')
    paginator = Paginator(all_tanks, 10)
    page_obj  = paginator.get_page(request.GET.get('page'))

    tank_data = []
    for tank in page_obj:
        latest = tank.readings.order_by('-created_at').first()
        status = "NORMAL"
        try:
            if latest and latest.temperature is not None:
                if abs(float(latest.temperature) - float(tank.target_temp or 26.0)) >= 2.0:
                    status = "DANGER"
        except (ValueError, TypeError):
            status = "UNKNOWN"

        d_day = 7
        if tank.last_water_change:
            period      = int(tank.water_change_period or 7)
            next_change = tank.last_water_change + timedelta(days=period)
            d_day       = (next_change - date.today()).days

        tank_data.append({'tank': tank, 'latest': latest, 'status': status, 'd_day': d_day})

    return render(request, 'core/index.html', {
        'tank_data': tank_data,
        'page_obj':  page_obj,
        'is_guest':  False,
        'has_tanks': all_tanks.exists(),
    })