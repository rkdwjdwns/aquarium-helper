import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.http import HttpResponse

# 모델 임포트: monitoring 앱의 모델을 참조합니다.
from monitoring.models import Tank, SensorReading
from .models import Report

@login_required
def report_list(request):
    """모든 어항 목록과 해당 어항의 리포트/센서 데이터를 동기화하여 전달합니다."""
    # 1. 현재 사용자의 모든 어항 가져오기 (상단 탭 출력용)
    tanks = Tank.objects.filter(user=request.user).order_by('-id')
    has_tanks = tanks.exists()

    # 2. 현재 선택된 어항 결정
    tank_id = request.GET.get('tank_id')
    selected_tank = None
    if has_tanks:
        if tank_id:
            selected_tank = tanks.filter(id=tank_id).first()
        if not selected_tank:
            selected_tank = tanks.first()

    # 3. 정렬 및 데이터 가져오기
    sort_order = request.GET.get('sort', 'desc')
    order_by = '-created_at' if sort_order == 'desc' else 'created_at'
    
    # 템플릿 하단 카드 리스트용 (SensorReading)
    report_data = []
    # 생성된 분석 리포트 목록용 (Report)
    reports = []

    if selected_tank:
        report_data = selected_tank.readings.all().order_by(order_by)
        reports = Report.objects.filter(tank=selected_tank).order_by('-created_at')
    
    context = {
        'tanks': tanks,                 # 상단 어항 선택 탭용
        'selected_tank': selected_tank, # 현재 선택된 어항 객체
        'has_tanks': has_tanks,         # 어항 존재 여부 체크
        'report_data': report_data,     # [중요] 템플릿 하단 센서 카드용
        'reports': reports,             # 생성된 통계 리포트 목록용
        'sort': sort_order,             # 정렬 상태 유지
    }
    return render(request, 'reports/report_list.html', context)

@login_required
def create_stat_report(request, tank_id):
    """데이터를 분석하여 통계 리포트 객체를 생성합니다."""
    tank = get_object_or_404(Tank, id=tank_id, user=request.user)
    
    # 기간 설정
    period = request.GET.get('period', 'daily')
    days = {'weekly': 7, 'monthly': 30}.get(period, 1)
    
    # 분석 데이터 필터링
    start_date = timezone.now() - timedelta(days=days)
    readings = SensorReading.objects.filter(tank=tank, created_at__gte=start_date)

    # 리포트 내용 생성
    content = f"[{period.upper()} 리포트] {tank.name}\n"
    content += f"분석 기준일: {start_date.strftime('%Y-%m-%d')} 이후\n"
    content += "-"*30 + "\n"

    if readings.exists():
        avg_temp = sum(r.temperature for r in readings) / readings.count()
        content += f"🌡️ 평균 온도: {avg_temp:.2f}°C\n"
        content += f"📊 분석 데이터 수: {readings.count()}개\n"
        content += f"🕒 생성 일시: {timezone.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        content += "현재 수온 데이터 기반 분석이 완료되었습니다."
    else:
        content += "선택하신 기간 내에 기록된 센서 데이터가 부족하여 상세 분석이 어렵습니다."

    # DB에 리포트 저장 (Report 모델)
    Report.objects.create(
        tank=tank, 
        report_type=period.upper(), 
        content=content
    )
    
    messages.success(request, f"{tank.name}의 {period} 분석 리포트가 성공적으로 생성되었습니다.")
    # 생성 후 현재 어항 탭을 유지하며 리다이렉트
    return redirect(f'/reports/?tank_id={tank.id}')

@login_required
def download_report(request, report_id):
    """생성된 리포트를 .txt 파일로 다운로드"""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    response = HttpResponse(report.content, content_type='text/plain; charset=utf-8')
    filename = f"report_{report.tank.name}_{report.created_at.strftime('%Y%m%d')}.txt"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@login_required
def download_report_csv(request, report_id):
    """생성된 리포트를 .csv 파일로 다운로드"""
    report = get_object_or_404(Report, id=report_id, tank__user=request.user)
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="report_{report.id}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['어항명', '리포트 타입', '생성일시', '상세내용'])
    writer.writerow([
        report.tank.name, 
        report.report_type, 
        report.created_at.strftime('%Y-%m-%d %H:%M'), 
        report.content.replace('\n', ' ')
    ])
    return response