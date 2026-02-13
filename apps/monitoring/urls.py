from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    path('', views.index, name='index'), 
    path('dashboard/', views.dashboard, name='dashboard_default'), 
    path('dashboard/<int:tank_id>/', views.dashboard, name='dashboard'), 
    path('tanks/', views.tank_list, name='tank_list'),
    path('add/', views.add_tank, name='add_tank'),
    path('edit/<int:tank_id>/', views.edit_tank, name='edit_tank'),
    
    # ⚠️ 에러 지점 수정: views.delete_tank가 없으면 아래처럼 이름을 맞춤
    path('delete/<int:tank_id>/', views.delete_tank_action, name='delete_tank'), 
    path('delete-tanks/', views.delete_tanks, name='delete_tanks'),
    
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
]