# apps/accounts/apps.py
from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    
    # ✅ 중복 모델 충돌(Conflicting models)을 막기 위해 'apps.' 경로를 명시합니다.
    name = 'apps.accounts'