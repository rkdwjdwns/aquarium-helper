import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.http import HttpResponse

from apps.monitoring.models import Tank, SensorReading
from .models import Report

# 한 페이지에 가져올 센서 데이터 최대 개수 (OOM 방지)
MAX_READINGS = 200


@login_required
def report_list(request):
    """모든 어항 목록과 해당 어항의 리포트/센서 데이터를 동기화하여 전달합니다."""
    tanks     = Tank.objects.filter(user=request.user).order_by('-id')
    has_tanks = tanks.exists()

    tank_id       = request.GET.get('tank_id')
    selected_tank = None
    if has_tanks:
        if tank_id:
            selected_tank = tanks.filter(id=tank_id).first()
        if not selected_tank:
            selected_tank = tanks.first()

    sort_order = request.GET.get('sort', 'desc')
    order_by   = '-created_at' if sort_order == 'desc' else 'created_at'

    report_data = []
    reports     = []

    if selected_tank:
        # ✅ 최근 MAX_READINGS개만 조회 — 전체 조회 시 OOM 발생
        report_data = selected_tank.readings.all().order_by(order_by)[:MAX_READINGS]
        reports     = Report.objects.filter(tank=selected_tank).order_by('-created_at')

    context = {
        'tanks':         tanks,
        'selected_tank': selected_tank,
        'has_tanks':     has_tanks,
        'report_data':   report_data,
        'reports':       reports,
        'sort':          sort_order,
        'max_readings':  MAX_READINGS,
    }
    return render(request, 'reports/report_list.html', context)


@login_required
def create_stat_report(request, tank_id):
    """데이터를 분석하여 통계 리포트 객체를 생성합니다."""
    tank   = get_object_or_404(Tank, id=tank_id, user=request.user)
    period = request.GET.get('period', 'daily')
    days   = {'weekly': 7, 'monthly': 30}.get(period, 1)

    start_date = timezone.now() - timedelta(days=days)
    readings   = SensorReading.objects.filter(tank=tank, created_at__gte=start_date)

    content  = f"[{period.upper()} 리포트] {tank.name}\n"
    content += f"분석 기준일: {start_date.strftime('%Y-%m-%d')} 이후\n"
    content += "-" * 30 + "\n"

    if readings.exists():
        # aggregate 사용 — 전체 객체 로드 없이 DB에서 계산
        from django.db.models import Avg, Min, Max
        stats = readings.aggregate(
            avg_temp=Avg('temperature'),
            min_temp=Min('temperature'),
            max_temp=Max('temperature'),
            avg_ph=Avg('ph'),
            avg_do=Avg('dissolved_oxygen'),
            avg_turb=Avg('turbidity'),
        )
        count = readings.count()

        content += f"🌡️ 평균 수온: {stats['avg_temp']:.2f}°C "
        content += f"(최저 {stats['min_temp']:.1f} / 최고 {stats['max_temp']:.1f})\n"
        content += f"💧 평균 pH: {stats['avg_ph']:.2f}\n"
        content += f"🫧 평균 DO: {stats['avg_do']:.2f} mg/L\n"
        content += f"🌫️ 평균 탁도: {stats['avg_turb']:.1f} NTU\n"
        content += f"📊 분석 데이터 수: {count}개\n"
        content += f"🕒 생성 일시: {timezone.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        content += "수질 데이터 기반 분석이 완료되었습니다."
    else:
        content += "선택하신 기간 내에 기록된 센서 데이터가 부족하여 상세 분석이 어렵습니다."

    Report.objects.create(tank=tank, report_type=period.upper(), content=content)
    messages.success(request, f"{tank.name}의 {period} 분석 리포트가 생성되었습니다.")
    return redirect(f'/reports/?tank_id={tank.id}')


@login_required
def download_report(request, report_id):
    """생성된 리포트를 .txt 파일로 다운로드"""
    report   = get_object_or_404(Report, id=report_id, tank__user=request.user)
    response = HttpResponse(report.content, content_type='text/plain; charset=utf-8')
    filename = f"report_{report.tank.name}_{report.created_at.strftime('%Y%m%d')}.txt"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def download_report_csv(request, report_id):
    """생성된 리포트를 .csv 파일로 다운로드"""
    report   = get_object_or_404(Report, id=report_id, tank__user=request.user)
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="report_{report.id}.csv"'

    writer = csv.writer(response)
    writer.writerow(['어항명', '리포트 타입', '생성일시', '상세내용'])
    writer.writerow([
        report.tank.name,
        report.report_type,
        report.created_at.strftime('%Y-%m-%d %H:%M'),
        report.content.replace('\n', ' '),
    ])
    return response