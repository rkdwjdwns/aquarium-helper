from django.db import models
from django.conf import settings

class Tank(models.Model):
    """어항 정보"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='tanks'
    )
    name = models.CharField(max_length=100)
    capacity = models.FloatField(help_text="Liters", default=0.0, null=True, blank=True)
    fish_species = models.CharField(max_length=200, blank=True, null=True)
    
    # --- [수정] 어종별 권장 환경 기준치 ---
    # 가이드라인 및 위험 알림의 기준이 됩니다.
    target_temp = models.FloatField(default=25.0, help_text="권장 온도")
    target_ph = models.FloatField(default=7.0, help_text="권장 pH")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class SensorReading(models.Model):
    """센서 측정 데이터 (수온, pH, 수위)"""
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='readings')
    temperature = models.FloatField()
    ph = models.FloatField()
    water_level = models.FloatField(default=100)
    created_at = models.DateTimeField(auto_now_add=True) 

    def __str__(self):
        return f"{self.tank.name} - {self.created_at}"

# 다른 앱(reports 등)과의 호환성을 위한 별칭
Reading = SensorReading

class EventLog(models.Model):
    """중요 이벤트 및 위험 알림 로그"""
    LOG_LEVELS = (
        ('INFO', '정보'),
        ('WARNING', '경고'),
        ('DANGER', '위험'),
    )
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='logs')
    level = models.CharField(max_length=10, choices=LOG_LEVELS, default='INFO')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.level}] {self.message}"

class DeviceControl(models.Model):
    """[추가] 장비 원격 제어 시뮬레이션용 모델"""
    DEVICE_TYPES = (
        ('LIGHT', '조명'),
        ('FILTER', '여과기'),
        ('HEATER', '히터'),
    )
    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='devices')
    type = models.CharField(max_length=20, choices=DEVICE_TYPES)
    is_on = models.BooleanField(default=False)
    last_action_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.tank.name} - {self.get_type_display()} ({'ON' if self.is_on else 'OFF'})"