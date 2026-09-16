from django.db import models
from django.conf import settings

class Report(models.Model):
    REPORT_TYPES = [
        ('DAILY', '일간 리포트'),
        ('WEEKLY', '주간 리포트'),
        ('MONTHLY', '월간 리포트'),
    ]

    # [수정] 문자열로 참조하면 앱 로딩 순서 문제를 피할 수 있습니다.
    tank = models.ForeignKey('monitoring.Tank', on_delete=models.CASCADE, related_name='reports')
    report_type = models.CharField(max_length=10, choices=REPORT_TYPES, default='DAILY')
    
    content = models.TextField(help_text="AI가 생성한 리포트 상세 내용")
    summary = models.CharField(max_length=255, blank=True, null=True)
    
    avg_ph = models.FloatField(null=True, blank=True)
    avg_temp = models.FloatField(null=True, blank=True)
    water_score = models.IntegerField(default=100)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'reports'
        verbose_name = "AI 리포트"
        verbose_name_plural = "AI 리포트 목록"

    def __str__(self):
        tank_name = self.tank.name if self.tank else "삭제된 어항"
        return f"{tank_name} - {self.get_report_type_display()} ({self.created_at.strftime('%Y-%m-%d')})"