from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    # 1. 메인 및 대시보드
    path('', views.index, name='index'), 
    path('dashboard/', views.dashboard, name='dashboard_default'), 
    path('dashboard/<int:tank_id>/', views.dashboard, name='dashboard'), 
    
    # 2. 어항 관리
    path('tanks/', views.tank_list, name='tank_list'),
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),
    
    # ⚠️ 중요: views.delete_tank 이름과 반드시 일치해야 함
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'), 
    path('delete-tanks/', views.delete_tanks, name='delete_tanks'),
    
    # 3. 부가 기능 및 API
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
]