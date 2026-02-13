from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    # 1. 메인 관리 센터 (주인님이 로고 누르면 바로 오는 곳!)
    # 만약 최상위 URL(fish/urls.py)에서 여기를 바로 보게 하고 싶다면 
    # 아래 name='tank_list' 경로를 프로젝트 메인으로 잡으면 됩니다.
    path('tanks/', views.tank_list, name='tank_list'),
    
    # 2. 실시간 상세 데이터 대시보드
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # 3. 어항 설정 (추가/수정/삭제)
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'),
    path('delete-tanks/', views.delete_tanks, name='delete_tanks'),
    
    # 4. 부가 기능
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    
    # 5. 하드웨어/AI API
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
    path('apply-recommendation/', views.apply_recommendation, name='apply_recommendation'),
]