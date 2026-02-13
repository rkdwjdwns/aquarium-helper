from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    # 메인 페이지 (대시보드)
    path('', views.dashboard, name='dashboard'), 
    
    # 어항 관리 센터 (편집 리스트)
    path('tanks/', views.tank_list, name='tank_list'),
    
    # 어항 개별 설정
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'),
    
    # 부가 서비스
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    
    # 제어 API (AJAX 호출용)
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
    path('apply-recommendation/', views.apply_recommendation, name='apply_recommendation'),
]