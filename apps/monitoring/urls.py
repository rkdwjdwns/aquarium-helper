from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    # [수정] 메인 페이지(로고 클릭 시 이동)를 대시보드로 설정
    path('', views.dashboard, name='dashboard'), 
    
    # 어항 관리 센터 (편집/삭제용)
    path('tanks/', views.tank_list, name='tank_list'),
    
    # 어항 설정 (추가/수정/삭제)
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'),
    path('delete-tanks/', views.delete_tanks, name='delete_tanks'),
    
    # 부가 기능
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    
    # 하드웨어/AI API
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
    path('apply-recommendation/', views.apply_recommendation, name='apply_recommendation'),
]