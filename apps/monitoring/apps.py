# apps/monitoring/apps.py
from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.monitoring'  # 기존 'monitoring'에서 'apps.monitoring'으로 수정

    def ready(self):
        # signals.py 안의 @receiver 데코레이터가 실제로 등록되도록 import
        import apps.monitoring.signals  # noqa: F401