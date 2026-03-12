from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    nickname = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        # [추가] Django App Registry가 경로를 찾지 못할 때를 대비한 명시적 선언
        app_label = 'accounts'

    def __str__(self):
        return self.username