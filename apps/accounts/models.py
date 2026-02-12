from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    # 닉네임: 화면에 표시될 이름
    nickname = models.CharField(max_length=20, blank=True, null=True, verbose_name="닉네임")
    # 생일: DateField 사용
    birthday = models.DateField(blank=True, null=True, verbose_name="생일")
    # 이메일은 기본 AbstractUser에 있지만, 명시적으로 관리하고 싶다면 추가 가능합니다.
    
    def __str__(self):
        return self.nickname if self.nickname else self.username