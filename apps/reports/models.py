from django.db import models
from django.conf import settings
from apps.monitoring.models import Tank

class Report(models.Model):
    REPORT_TYPES = [
        ('DAILY', '일간 리포트'),
        ('WEEKLY', '주간 리포트'),
        ('MONTHLY', '월간 리포트'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='reports')
    report_type = models.CharField(max_length=10, choices=REPORT_TYPES, default='DAILY')
    
    # AI가 생성한 분석 본문
    content = models.TextField(help_text="AI가 생성한 리포트 상세 내용")
    
    # 대시보드에서 바로 보여줄 요약문
    summary = models.CharField(max_length=255, blank=True, null=True)
    
    # 해당 시점의 평균 수치 데이터 (나중에 그래프 그릴 때 활용)
    avg_ph = models.FloatField(null=True, blank=True)
    avg_temp = models.FloatField(null=True, blank=True)
    water_score = models.IntegerField(default=100)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tank.name} - {self.get_report_type_display()} ({self.created_at.strftime('%Y-%m-%d')})"

    class Meta:
        verbose_name = "AI 리포트"
        verbose_name_plural = "AI 리포트 목록"