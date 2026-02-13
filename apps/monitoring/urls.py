from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    # 1. 메인 페이지 (실시간 내 어항 리스트)
    path('', views.index, name='index'), 
    
    # 2. 상세 대시보드
    path('dashboard/', views.dashboard, name='dashboard_default'), 
    path('dashboard/<int:tank_id>/', views.dashboard, name='dashboard'), 
    
    # 3. 어항 관리 센터
    path('tanks/', views.tank_list, name='tank_list'),
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'),
    path('delete-tanks/', views.delete_tanks, name='delete_tanks'),
    
    # 부가 서비스
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    
    # API (비동기 제어용)
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
]