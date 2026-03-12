from django.apps import AppConfig

class AccountsConfig(AppConfig):  # 이름을 ReportsConfig에서 AccountsConfig로 수정
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'  # name도 accounts로 수정