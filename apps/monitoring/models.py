from django.db import models
from django.conf import settings


# ──────────────────────────────────────────────
# 어항
# ──────────────────────────────────────────────

class Tank(models.Model):
    """어항 기본 정보 및 제어 설정"""

    FILTER_MODES = [
        ('MANUAL', '수동'),
        ('AUTO',   '자동'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tanks',
    )
    name         = models.CharField(max_length=100)
    capacity     = models.FloatField(help_text="용량(L)", default=0.0, null=True, blank=True)
    fish_species = models.CharField(max_length=200, blank=True, null=True)

    # 목표 수질
    target_temp = models.FloatField(default=25.0, help_text="권장 수온(°C)")
    target_ph   = models.FloatField(default=7.0,  help_text="권장 pH")

    # 환수 관리
    last_water_change    = models.DateField(null=True, blank=True, help_text="마지막 환수일")
    water_change_period  = models.IntegerField(default=7, help_text="환수 주기(일)")

    # 여과기 설정
    filter_mode  = models.CharField(max_length=10, choices=FILTER_MODES, default='MANUAL')
    filter_is_on = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return self.name


# ──────────────────────────────────────────────
# 센서 데이터
# ──────────────────────────────────────────────

class SensorReading(models.Model):
    """ESP32 → Raspberry Pi → 서버로 전송되는 수질 센서 데이터"""

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='readings')

    temperature         = models.FloatField(help_text="수온(°C)")
    ph                  = models.FloatField(help_text="pH")
    dissolved_oxygen    = models.FloatField(default=0.0, help_text="용존산소량(mg/L)")  # DO 센서 추가
    turbidity           = models.FloatField(default=0.0, help_text="탁도(NTU)")
    water_level         = models.FloatField(default=100.0, help_text="수위(%)")
    water_quality_score = models.IntegerField(default=100, help_text="수질 종합 점수(0~100)")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return f"[{self.tank.name}] {self.created_at:%Y-%m-%d %H:%M}"


# 하위 호환 별칭
Reading = SensorReading


# ──────────────────────────────────────────────
# AI 어류 행동 분석
# ──────────────────────────────────────────────

class FishBehavior(models.Model):
    """YOLOv11 + ByteTrack 분석 결과 — Raspberry Pi에서 전송"""

    ZONE_CHOICES = [
        ('TOP', '상층'),
        ('MID', '중층'),
        ('BOT', '하층'),
    ]

    STATUS_CHOICES = [
        ('EXCELLENT', '매우 좋음'),
        ('GOOD',      '좋음'),
        ('NORMAL',    '보통'),
        ('WARNING',   '주의'),
        ('POOR',      '나쁨'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='behaviors')

    # 탐지 기본 정보
    fish_count     = models.IntegerField(default=0, help_text="탐지된 개체 수")
    overlap_frames = models.IntegerField(default=0, help_text="겹침 발생 프레임 수")

    # 행동 지표
    activity_level  = models.FloatField(default=0.0, help_text="활동량(px/frame 이동평균)")
    dominant_zone   = models.CharField(max_length=3, choices=ZONE_CHOICES, default='MID', help_text="주 체류 구역")
    zone_top_ratio  = models.FloatField(default=0.0, help_text="상층 체류 비율(0~1)")
    zone_mid_ratio  = models.FloatField(default=0.0, help_text="중층 체류 비율(0~1)")
    zone_bot_ratio  = models.FloatField(default=0.0, help_text="하층 체류 비율(0~1)")
    size_index      = models.FloatField(default=0.0, help_text="상대 크기 지표(%)")

    # 급이 반응
    feeding_score   = models.IntegerField(default=0, help_text="급이 반응 점수(0~100)")

    # 상태 판정
    status    = models.CharField(max_length=10, choices=STATUS_CHOICES, default='NORMAL')
    is_anomaly = models.BooleanField(default=False, help_text="이상 행동 감지 여부")
    note      = models.TextField(blank=True, help_text="AI 권장사항 또는 이상 내용")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        flag = " ⚠️" if self.is_anomaly else ""
        return f"[{self.tank.name}] {self.status}{flag} — {self.created_at:%Y-%m-%d %H:%M}"


# ──────────────────────────────────────────────
# 장치 제어
# ──────────────────────────────────────────────

class DeviceControl(models.Model):
    """릴레이로 제어되는 하드웨어 장치 상태"""

    DEVICE_TYPES = [
        ('HEATER',   '히터'),
        ('COOLING',  '냉각팬'),
        ('FILTER',   '여과기'),
        ('AIR_PUMP', '에어펌프'),
        ('FEEDER',   '급이기'),
        ('LIGHT',    '조명'),
    ]

    tank        = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='devices')
    type        = models.CharField(max_length=20, choices=DEVICE_TYPES)
    is_on       = models.BooleanField(default=False)
    is_auto     = models.BooleanField(default=True, help_text="True: 자동 제어 / False: 수동 제어")
    last_action_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'monitoring'
        unique_together = ('tank', 'type')   # 어항당 장치 종류 하나씩

    def __str__(self):
        state = "ON" if self.is_on else "OFF"
        mode  = "자동" if self.is_auto else "수동"
        return f"[{self.tank.name}] {self.get_type_display()} — {state} ({mode})"


# ──────────────────────────────────────────────
# 이벤트 로그
# ──────────────────────────────────────────────

class EventLog(models.Model):
    """시스템 이벤트 및 알림 기록"""

    LEVEL_CHOICES = [
        ('INFO',    '정보'),
        ('WARNING', '경고'),
        ('DANGER',  '위험'),
    ]

    tank    = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='logs')
    level   = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='INFO')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return f"[{self.level}] {self.tank.name} — {self.created_at:%Y-%m-%d %H:%M}"