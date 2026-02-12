from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('logs/', views.logs_view, name='logs'),
    path('add/', views.add_tank, name='add_tank'),
    path('camera/', views.camera_view, name='camera_view'),
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    # --- [추가] 환수 완료 처리 경로 ---
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
]