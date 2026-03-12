from django.db import models
from django.conf import settings

class Tank(models.Model):
    """어항 정보 및 제어 설정"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='tanks'
    )
    name = models.CharField(max_length=100)
    capacity = models.FloatField(help_text="Liters", default=0.0, null=True, blank=True)
    fish_species = models.CharField(max_length=200, blank=True, null=True)
    
    target_temp = models.FloatField(default=25.0, help_text="권장 온도")
    target_ph = models.FloatField(default=7.0, help_text="권장 pH")
    
    last_water_change = models.DateField(null=True, blank=True, help_text="마지막 환수 날짜")
    water_change_period = models.IntegerField(default=7, help_text="환수 주기(일)")
    
    FILTER_MODES = [('MANUAL', '수동'), ('AUTO', '자동')]
    filter_mode = models.CharField(max_length=10, choices=FILTER_MODES, default='MANUAL')
    filter_is_on = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'

    def __str__(self):
        return self.name

class SensorReading(models.Model):
    """센서 측정 데이터"""
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='readings')
    temperature = models.FloatField()
    ph = models.FloatField()
    water_level = models.FloatField(default=100)
    turbidity = models.FloatField(default=0.0)      
    water_quality_score = models.IntegerField(default=100) 
    created_at = models.DateTimeField(auto_now_add=True) 

    class Meta:
        app_label = 'monitoring'

    def __str__(self):
        return f"{self.tank.name} - {self.created_at}"

# 하위 호환 별칭
Reading = SensorReading 

class EventLog(models.Model):
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='logs')
    level = models.CharField(max_length=10, choices=(('INFO', '정보'), ('WARNING', '경고'), ('DANGER', '위험')), default='INFO')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'

class DeviceControl(models.Model):
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='devices')
    type = models.CharField(max_length=20, choices=(('LIGHT', '조명'), ('FILTER', '여과기'), ('HEATER', '히터')))
    is_on = models.BooleanField(default=False)
    last_action_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'monitoring'