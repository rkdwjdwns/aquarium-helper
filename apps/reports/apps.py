# apps/reports/apps.py
from django.apps import AppConfig

class ReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # ❌ 'apps.reports'로 되어 있다면 반드시 'reports'로 수정하세요.
    name = 'reports'