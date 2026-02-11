from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # 리포트 목록 페이지 (일간/주간/월간 리포트 리스트 확인)
    path('', views.report_list, name='report_list'),
    
    # 데이터 기반 통계 리포트 생성 (period 파라미터를 통해 일/주/월 구분)
    path('create-stat/<int:tank_id>/', views.create_stat_report, name='create_stat_report'),
    
    # 특정 리포트 다운로드 (텍스트 파일 등)
    path('download/<int:report_id>/', views.download_report, name='download_report'),

    path('download-csv/<int:report_id>/', views.download_report_csv, name='download_report_csv'),
]