from django.urls import path
from . import views

# 앱 이름 설정 (템플릿에서 'monitoring:tank_list' 식으로 호출할 때 필요해요!)
app_name = 'monitoring'

urlpatterns = [
    # 1. 메인 대시보드 (어항들의 요약 상태 확인)
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # 2. 전체 어항 목록 (정렬 및 편집/삭제 가능 페이지) - [신규 추가]
    path('tanks/', views.tank_list, name='tank_list'),
    
    # 3. 어항 추가/삭제 관련
    path('add/', views.add_tank, name='add_tank'),
    path('delete-tanks/', views.delete_tanks, name='delete_tanks'),
    
    # 4. 실시간 로그 및 알림 확인
    path('logs/', views.logs_view, name='logs'),
    
    # 5. 카메라 및 AI 비전 기능
    path('camera/', views.camera_view, name='camera_view'),
    
    # 6. 하드웨어 제어 API (JSON 응답용)
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
    path('apply-recommendation/', views.apply_recommendation, name='apply_recommendation'),
]