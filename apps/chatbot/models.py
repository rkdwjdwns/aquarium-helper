from django.db import models
from django.conf import settings

class ChatMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField()      # 사용자의 질문
    response = models.TextField()     # AI의 답변
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at'] # 최신 대화 순정렬