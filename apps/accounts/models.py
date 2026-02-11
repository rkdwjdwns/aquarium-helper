from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    # 닉네임 필드 추가
    nickname = models.CharField(max_length=20, blank=True, null=True, verbose_name="닉네임")

    def __str__(self):
        return self.nickname if self.nickname else self.username