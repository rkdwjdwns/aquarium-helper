import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.http import HttpResponse

# [보완] 다른 앱의 모델을 가져올 때 sys.path 설정 덕분에 바로 임포트 가능
from monitoring.models import Tank, SensorReading
from .models import Report

@login_required
def report_list(request):
    """생성된 모든 리포트 목록을 보여줍니다."""
    # 현재 로그인한 사용자의 어항과 연결된 리포트만 가져옵니다.
    reports = Report.objects.filter(tank__user=request.user).order_by('-created_at')
    return render(request, 'reports/report_list.html', {'reports': reports})

@login_required
def create_stat_report(request, tank_id):
    """데이터를 분석하여 통계 리포트를 생성합니다."""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    period = request.GET.get('period', 'daily')
    days = {'weekly': 7, 'monthly': 30}.get(period, 1)
    
    start_date = timezone.now() - timedelta(days=days)
    readings = SensorReading.objects.filter(tank=tank, created_at__gte=start_date)

    content = f"[{period.upper()} 리포트] {tank.name}\n"
    if readings.exists():
        avg_temp = sum(r.temperature for r in readings) / readings.count()
        content += f"🌡️ 평균 온도: {avg_temp:.2f}°C\n"
        content += f"📊 분석 데이터 수: {readings.count()}개\n"
        content += f"🕒 분석 기간: {start_date.date()} ~ {timezone.now().date()}"
    else:
        content += "데이터가 부족하여 리포트를 생성할 수 없습니다."

    Report.objects.create(tank=tank, report_type=period.upper(), content=content)
    messages.success(request, f"{tank.name}의 {period} 리포트가 생성되었습니다.")
    return redirect('reports:report_list')

@login_required
def download_report(request, report_id):
    """리포트 내용을 단순 텍스트 파일로 다운로드합니다."""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    response = HttpResponse(report.content, content_type='text/plain; charset=utf-8')
    filename = f"report_{report.id}_{report.created_at.strftime('%Y%m%d')}.txt"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@login_required
def download_report_csv(request, report_id):
    """리포트 정보를 CSV 형식으로 다운로드합니다."""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="report_{report.id}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['어항명', '리포트 타입', '생성일', '내용'])
    writer.writerow([
        report.tank.name, 
        report.report_type, 
        report.created_at.strftime('%Y-%m-%d %H:%M'), 
        report.content.replace('\n', ' ')
    ])
    return response