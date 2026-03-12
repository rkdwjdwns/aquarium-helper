import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.http import HttpResponse

# [보완] 다른 앱의 모델을 가져올 때 settings의 sys.path 설정 덕분에 바로 임포트 가능
from monitoring.models import Tank, SensorReading
from .models import Report

@login_required
def report_list(request):
    """생성된 모든 리포트 목록과 분석용 어항 정보를 전달합니다."""
    # 1. 현재 로그인한 사용자의 리포트 목록 (최신순)
    reports = Report.objects.filter(tank__user=request.user).order_by('-created_at')
    
    # 2. [중요] 상단 분석 버튼 출력을 위해 사용자의 첫 번째 어항 정보를 가져옵니다.
    # 이 데이터가 있어야 템플릿의 {% if first_tank %} 조건이 활성화됩니다.
    first_tank = Tank.objects.filter(user=request.user).first()
    
    context = {
        'reports': reports,
        'first_tank': first_tank,
    }
    return render(request, 'reports/report_list.html', context)

@login_required
def create_stat_report(request, tank_id):
    """데이터를 분석하여 통계 리포트를 생성합니다."""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    
    # 기간 설정 (daily, weekly, monthly)
    period = request.GET.get('period', 'daily')
    days = {'weekly': 7, 'monthly': 30}.get(period, 1)
    
    # 분석 시작일 계산 및 데이터 필터링
    start_date = timezone.now() - timedelta(days=days)
    readings = SensorReading.objects.filter(tank=tank, created_at__gte=start_date)

    # 리포트 내용 생성
    content = f"[{period.upper()} 리포트] {tank.name}\n"
    content += f"분석 기준일: {start_date.strftime('%Y-%m-%d')} 이후\n\n"

    if readings.exists():
        avg_temp = sum(r.temperature for r in readings) / readings.count()
        content += f"🌡️ 평균 온도: {avg_temp:.2f}°C\n"
        content += f"📊 분석 데이터 수: {readings.count()}개\n"
        content += f"🕒 최종 업데이트: {timezone.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        content += "현재 수온이 안정적으로 유지되고 있습니다."
    else:
        content += "선택하신 기간 내에 기록된 센서 데이터가 부족하여 상세 분석이 어렵습니다."

    # DB에 리포트 저장
    Report.objects.create(
        tank=tank, 
        report_type=period.upper(), 
        content=content
    )
    
    messages.success(request, f"{tank.name}의 {period} 분석 리포트가 생성되었습니다.")
    return redirect('reports:report_list')

@login_required
def download_report(request, report_id):
    """리포트 내용을 텍스트(.txt) 파일로 다운로드합니다."""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    
    # 메모장 등에서 잘 열리도록 cp949 또는 utf-8-sig 권장 (여기서는 utf-8)
    response = HttpResponse(report.content, content_type='text/plain; charset=utf-8')
    filename = f"report_{report.tank.name}_{report.created_at.strftime('%Y%m%d')}.txt"
    
    # 파일명 한글 깨짐 방지를 위해 가급적 영문/숫자 조합 권장
    response['Content-Disposition'] = f'attachment; filename="tank_report_{report.id}.txt"'
    return response

@login_required
def download_report_csv(request, report_id):
    """리포트 정보를 Excel(CSV) 형식으로 다운로드합니다."""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    
    # 엑셀에서 한글이 깨지지 않도록 utf-8-sig 사용
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="report_{report.id}.csv"'
    
    writer = csv.writer(response)
    # 헤더 작성
    writer.writerow(['어항명', '리포트 타입', '생성일시', '상세내용'])
    # 데이터 작성 (내용의 줄바꿈은 엑셀 셀 보호를 위해 공백으로 치환)
    writer.writerow([
        report.tank.name, 
        report.report_type, 
        report.created_at.strftime('%Y-%m-%d %H:%M'), 
        report.content.replace('\n', ' ')
    ])
    return response