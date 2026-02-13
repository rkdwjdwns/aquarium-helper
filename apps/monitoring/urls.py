from django.urls import path
from . import views

# 앱 이름 설정
app_name = 'monitoring'

urlpatterns = [
    # 1. 메인 대시보드 (로고 클릭 시 이동)
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # 2. 어항 목록 관리 센터 (체크박스 및 개별 관리)
    path('tanks/', views.tank_list, name='tank_list'),
    
    # 3. 어항 추가/수정/삭제 관련
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),      # 개별 수정
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'), # 개별 삭제
    path('delete-tanks/', views.delete_tanks, name='delete_tanks'),       # 일괄 삭제
    
    # 4. 실시간 로그 및 알림
    path('logs/', views.logs_view, name='logs'),
    
    # 5. 카메라 및 AI 비전
    path('camera/', views.camera_view, name='camera_view'),
    
    # 6. 하드웨어 제어 API
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
    path('apply-recommendation/', views.apply_recommendation, name='apply_recommendation'),
]