from django.db import models
from monitoring.models import Tank 

class Report(models.Model):
    REPORT_TYPES = [
        ('DAILY', '일간 리포트'),
        ('WEEKLY', '주간 리포트'),
        ('MONTHLY', '월간 리포트'),
        ('AI', 'AI 정밀 리포트'),
    ]
    
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='reports')
    report_type = models.CharField(max_length=10, choices=REPORT_TYPES)
    content = models.TextField() 
    recommended_temp = models.FloatField(null=True, blank=True)
    recommended_ph = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tank.name} - {self.get_report_type_display()} ({self.created_at.strftime('%Y-%m-%d')})"