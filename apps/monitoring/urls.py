from django.urls import path
from . import views, api_views

app_name = 'monitoring'

urlpatterns = [

    # ── [1. 메인 및 대시보드] ──────────────────────────────────────
    path('',                         views.index,           name='index'),
    path('dashboard/',               views.dashboard,       name='dashboard_default'),
    path('dashboard/<int:tank_id>/', views.dashboard,       name='dashboard'),

    # ── [2. 어항 관리 CRUD] ────────────────────────────────────────
    path('tanks/',                   views.tank_list,       name='tank_list'),
    path('tanks/delete-multiple/',   views.delete_tanks,    name='delete_tanks'),
    path('add/',                     views.add_tank,        name='add_tank'),
    path('edit/<int:tank_id>/',      views.edit_tank,       name='edit_tank'),
    path('delete/<int:tank_id>/',    views.delete_tank,     name='delete_tank'),

    # ── [3. 로그 및 카메라] ────────────────────────────────────────
    path('logs/',                    views.logs_view,       name='logs'),
    path('camera/',                  views.camera_view,     name='camera_view'),

    # ── [4. 장치 제어 및 환수] ─────────────────────────────────────
    path('toggle-device/<int:tank_id>/',  views.toggle_device,        name='toggle_device'),
    path('water-change/<int:tank_id>/',   views.perform_water_change, name='perform_water_change'),

    # ── [5. AI 챗봇] ───────────────────────────────────────────────
    path('chat/',                    views.chat_api,        name='chat_api'),

    # ── [6. 리포트] ────────────────────────────────────────────────
    path('reports/',                             views.ai_report_list,     name='ai_report_list'),
    path('reports/delete/<int:reading_id>/',     views.delete_report_data, name='delete_report_data'),
    path('reports/download/<int:tank_id>/',      views.download_report,    name='download_report'),

    # ── [7. Raspberry Pi REST API] ─────────────────────────────────
    path('api/sensor/',                     api_views.receive_sensor_data,    name='api_sensor'),
    path('api/behavior/',                   api_views.receive_fish_behavior,  name='api_behavior'),
    path('api/feeding/',                    api_views.receive_feeding_event,  name='api_feeding'),
    path('api/growth/',                     api_views.receive_growth_record,  name='api_growth'),
    path('api/pattern/',                    api_views.receive_activity_pattern, name='api_pattern'),
    path('api/commands/<int:tank_id>/',     api_views.get_pending_commands,   name='api_commands'),
    path('api/health/',                     api_views.health_check,           name='api_health'),
]