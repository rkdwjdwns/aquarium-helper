import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.http import HttpResponse

# [수정] sys.path 등록으로 인해 apps.를 뺍니다.
from monitoring.models import Tank, SensorReading
from .models import Report

# 호환성을 위해 SensorReading을 Reading이라는 이름으로 사용
Reading = SensorReading

@login_required
def report_list(request):
    """생성된 리포트 목록을 보여주는 뷰"""
    reports = Report.objects.filter(tank__user=request.user).order_by('-created_at')
    first_tank = Tank.objects.filter(user=request.user).first()
    
    return render(request, 'reports/report_list.html', {
        'reports': reports,
        'first_tank': first_tank
    })

@login_required
def create_stat_report(request, tank_id):
    """데이터 기반 통계 리포트 생성 뷰"""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    period = request.GET.get('period', 'daily')
    now = timezone.now()

    if period == 'weekly':
        start_date = now - timedelta(days=7)
        title = "주간 데이터 리포트"
        report_type = 'WEEKLY'
    elif period == 'monthly':
        start_date = now - timedelta(days=30)
        title = "월간 데이터 리포트"
        report_type = 'MONTHLY'
    else:
        start_date = now - timedelta(days=1)
        title = "일간 데이터 리포트"
        report_type = 'DAILY'

    readings = Reading.objects.filter(tank=tank, created_at__gte=start_date)

    content = f"[{title}]\n"
    content += f"기간: {start_date.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}\n"
    content += f"총 기록 수: {readings.count()}건\n"
    content += "-" * 30 + "\n"
    
    if readings.exists():
        avg_temp = sum(r.temperature for r in readings) / readings.count()
        avg_ph = sum(r.ph for r in readings) / readings.count()
        max_temp = max(r.temperature for r in readings)
        min_temp = min(r.temperature for r in readings)
        
        content += f"🌡️ 평균 온도: {avg_temp:.2f}°C (최고: {max_temp:.1f} / 최저: {min_temp:.1f})\n"
        content += f"🧪 평균 pH: {avg_ph:.2f}\n"
        content += "\n데이터를 기반으로 수질이 안정적으로 유지되고 있는지 확인하세요."
    else:
        content += "⚠️ 해당 기간에 측정된 센서 데이터가 존재하지 않습니다.\n"
        content += "센서 연결 상태를 확인하거나 데이터가 쌓인 후 다시 시도해주세요."

    Report.objects.create(
        tank=tank,
        report_type=report_type,
        content=content
    )

    messages.success(request, f"새로운 {title}가 성공적으로 생성되었습니다!")
    return redirect('reports:report_list')

@login_required
def download_report(request, report_id):
    """리포트를 TXT 파일로 다운로드"""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    
    filename = f"report_{report.report_type}_{report.created_at.strftime('%Y%m%d')}.txt"
    response = HttpResponse(report.content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response

@login_required
def download_report_csv(request, report_id):
    """리포트를 CSV 파일로 다운로드 (엑셀 호환)"""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    
    # 엑셀에서 한글 깨짐 방지를 위해 BOM(utf-8-sig) 설정
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    filename = f"report_{report.id}_{report.created_at.strftime('%Y%m%d')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    writer = csv.writer(response)
    writer.writerow(['어항명', '리포트 유형', '생성일', '상세 내용'])
    writer.writerow([
        report.tank.name,
        report.get_report_type_display(),
        report.created_at.strftime('%Y-%m-%d'),
        report.content.replace('\n', ' ') # 줄바꿈을 공백으로 치환
    ])
    
    return response