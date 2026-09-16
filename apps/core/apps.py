# apps/core/apps.py
from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    
    # ✅ settings.py의 'apps.core'와 반드시 일치해야 에러가 나지 않습니다.
    name = 'apps.core'