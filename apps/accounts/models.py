from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    nickname = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        app_label = 'accounts'
        db_table = 'auth_user'  # 기존 장고 유저 테이블과 호환성 유지

    def __str__(self):
        return self.username