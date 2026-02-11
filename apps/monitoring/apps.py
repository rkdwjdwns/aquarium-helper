from django.apps import AppConfig

class MonitoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # [수정] INSTALLED_APPS에 등록된 이름과 일치시킵니다.
    name = 'monitoring'