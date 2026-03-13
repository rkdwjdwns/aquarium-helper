from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    # 메인 및 대시보드
    path('', views.index, name='index'), 
    path('dashboard/', views.dashboard, name='dashboard_default'), 
    path('dashboard/<int:tank_id>/', views.dashboard, name='dashboard'), 
    
    # 어항 관리 (CRUD)
    path('tanks/', views.tank_list, name='tank_list'),
    path('tanks/delete-multiple/', views.delete_tanks, name='delete_tanks'),
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'), 
    
    # 로그 및 카메라
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    
    # 장치 제어 및 활동 기록
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
    
    # AI 챗봇 API
    path('chat/', views.chat_api, name='chat_api'),
    
    # AI 리포트 (기능 확장)
    path('reports/', views.ai_report_list, name='ai_report_list'),
    # [추가] 특정 어항의 리포트를 다운로드하기 위한 경로
    path('reports/download/<int:tank_id>/', views.download_report, name='download_report'),
]