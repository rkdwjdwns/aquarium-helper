# apps/monitoring/apps.py
from django.apps import AppConfig

class MonitoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.monitoring'  # 👈 기존 'monitoring'에서 'apps.monitoring'으로 수정