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
    path('delete/<int:tank_id>/', views.delete_tank, name='delete_tank'), 
    path('logs/', views.logs_view, name='logs'),
    path('camera/', views.camera_view, name='camera_view'),
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
    path('water-change/<int:tank_id>/', views.perform_water_change, name='perform_water_change'),
    path('chat/', views.chat_api, name='chat_api'),
    path('reports/', views.ai_report_list, name='ai_report_list'),
]