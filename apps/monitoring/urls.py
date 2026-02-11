# apps/monitoring/urls.py

from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('logs/', views.logs_view, name='logs'),  # <--- 여기서 name을 'logs'로 확정!
    path('add/', views.add_tank, name='add_tank'),
    path('camera/', views.camera_view, name='camera_view'),
    path('toggle-device/<int:tank_id>/', views.toggle_device, name='toggle_device'),
]