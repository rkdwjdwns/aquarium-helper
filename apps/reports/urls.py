from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # 리포트 목록 페이지 (views.report_list 함수와 매칭)
    path('', views.report_list, name='report_list'),
    
    # 데이터 기반 통계 리포트 생성
    path('create-stat/<int:tank_id>/', views.create_stat_report, name='create_stat_report'),
    
    # 리포트 다운로드 (텍스트 형식)
    path('download/<int:report_id>/', views.download_report, name='download_report'),
    
    # 리포트 다운로드 (CSV 형식)
    path('download-csv/<int:report_id>/', views.download_report_csv, name='download_report_csv'),
]