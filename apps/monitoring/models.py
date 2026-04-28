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
    target_temp = models.FloatField(default=22.0, help_text="권장 수온(°C)")
    target_ph   = models.FloatField(default=7.4,  help_text="권장 pH")

    # 환수 관리
    last_water_change   = models.DateField(null=True, blank=True, help_text="마지막 환수일")
    water_change_period = models.IntegerField(default=7, help_text="환수 주기(일)")

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
    dissolved_oxygen    = models.FloatField(default=0.0, help_text="용존산소량(mg/L)")
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
    activity_level = models.FloatField(default=0.0, help_text="활동량(px/s 이동평균)")
    dominant_zone  = models.CharField(max_length=3, choices=ZONE_CHOICES, default='MID', help_text="주 체류 구역")
    zone_top_ratio = models.FloatField(default=0.0, help_text="상층 체류 비율(0~1)")
    zone_mid_ratio = models.FloatField(default=0.0, help_text="중층 체류 비율(0~1)")
    zone_bot_ratio = models.FloatField(default=0.0, help_text="하층 체류 비율(0~1)")
    size_index     = models.FloatField(default=0.0, help_text="상대 크기 지표(%)")

    # 이상 행동율 (ABR)
    abr_score      = models.FloatField(default=0.0, help_text="이상 행동율(0~1), |speed-μ|>2σ 비율")

    # 급이 반응
    feeding_score  = models.IntegerField(default=0, help_text="급이 반응 점수(0~100)")

    # 상태 판정
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default='NORMAL')
    is_anomaly = models.BooleanField(default=False, help_text="이상 행동 감지 여부")
    note       = models.TextField(blank=True, help_text="AI 권장사항 또는 이상 내용")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        flag = " ⚠️" if self.is_anomaly else ""
        return f"[{self.tank.name}] {self.status}{flag} — {self.created_at:%Y-%m-%d %H:%M}"


# ──────────────────────────────────────────────
# 급이 이벤트
# ──────────────────────────────────────────────

class FeedingEvent(models.Model):
    """급이 발생 이벤트 기록 — feeding_events.csv 대응"""

    TRIGGER_CHOICES = [
        ('AUTO',   '자동'),
        ('MANUAL', '수동'),
    ]

    STAGE_CHOICES = [
        ('FRY',    '치어 (1~3cm)'),
        ('YOUNG',  '유어 (3~7cm)'),
        ('ADULT',  '성어 (7cm+)'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='feeding_events')

    # 급이 정보
    trigger        = models.CharField(max_length=10, choices=TRIGGER_CHOICES, default='AUTO', help_text="급이 트리거")
    amount_g       = models.FloatField(default=0.0, help_text="급이량(g)")
    growth_stage   = models.CharField(max_length=10, choices=STAGE_CHOICES, default='FRY', help_text="성장 단계")

    # 탁도 피드백
    turbidity_before = models.FloatField(default=0.0, help_text="급이 전 탁도(NTU)")
    turbidity_after  = models.FloatField(default=0.0, help_text="급이 후 탁도(NTU)")
    delta_ntu        = models.FloatField(default=0.0, help_text="탁도 변화량(NTU)")
    is_overfeeding   = models.BooleanField(default=False, help_text="과급여 플래그")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        flag = " ⚠️과급여" if self.is_overfeeding else ""
        return f"[{self.tank.name}] {self.amount_g}g {self.get_trigger_display()}{flag} — {self.created_at:%Y-%m-%d %H:%M}"


# ──────────────────────────────────────────────
# 급이 반응 분석
# ──────────────────────────────────────────────

class FeedingResponse(models.Model):
    """FRS(Feeding Response Score) 분석 결과 — feeding_response.csv 대응"""

    tank          = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='feeding_responses')
    feeding_event = models.OneToOneField(FeedingEvent, on_delete=models.CASCADE, related_name='response', null=True, blank=True)

    # FRS 구성 지표
    rt_seconds      = models.FloatField(default=0.0, help_text="반응시간(초): 급이→수면 첫 접근까지")
    ar_ratio        = models.FloatField(default=0.0, help_text="활동증가율: 급이중/급이전 avg_speed 비율")
    sf_ratio        = models.FloatField(default=0.0, help_text="수면접근빈도: 급이구간 TOP zone 체류 비율")

    # FRS 최종 점수
    frs_score       = models.IntegerField(default=0, help_text="급이 반응 점수(0~100)")

    # 구간별 활동량
    activity_before = models.FloatField(default=0.0, help_text="급이 전 평균 활동량(px/s)")
    activity_during = models.FloatField(default=0.0, help_text="급이 중 평균 활동량(px/s)")
    activity_after  = models.FloatField(default=0.0, help_text="급이 후 평균 활동량(px/s)")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return f"[{self.tank.name}] FRS={self.frs_score} — {self.created_at:%Y-%m-%d %H:%M}"


# ──────────────────────────────────────────────
# 성장 기록
# ──────────────────────────────────────────────

class GrowthRecord(models.Model):
    """개체별 성장 추이 기록 — growth_records.csv 대응"""

    STAGE_CHOICES = [
        ('FRY',   '치어 (1~3cm)'),
        ('YOUNG', '유어 (3~7cm)'),
        ('ADULT', '성어 (7cm+)'),
    ]

    tank    = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='growth_records')
    fish_id = models.IntegerField(help_text="ByteTrack 개체 ID")

    # 크기 추정
    size_index        = models.FloatField(help_text="size_index(%) = bbox면적/프레임면적×100")
    estimated_length  = models.FloatField(default=0.0, help_text="추정 체장(cm)")
    estimated_weight  = models.FloatField(default=0.0, help_text="추정 체중(g) — W=0.01049×TL^3.14")

    # 성장률
    growth_rate       = models.FloatField(default=0.0, help_text="성장률(cm/day)")
    growth_stage      = models.CharField(max_length=10, choices=STAGE_CHOICES, default='FRY')

    # 급이량 자동 조정
    recommended_feed_g = models.FloatField(default=0.0, help_text="권장 1회 급이량(g)")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return f"[{self.tank.name}] ID:{self.fish_id} {self.estimated_length}cm — {self.created_at:%Y-%m-%d %H:%M}"


# ──────────────────────────────────────────────
# 활동 패턴 리포트
# ──────────────────────────────────────────────

class ActivityPattern(models.Model):
    """시간대별 활동 패턴 분석 결과 — activity_pattern_reports.csv 대응"""

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='activity_patterns')

    # 분석 기간
    period_start = models.DateTimeField(help_text="분석 시작 시각")
    period_end   = models.DateTimeField(help_text="분석 종료 시각")

    # 시간대별 평균 활동량 (0~23시)
    hourly_activity = models.JSONField(default=dict, help_text="시간대별 평균 활동량 {hour: avg_speed}")

    # Baseline 대비 편차
    baseline_mean    = models.FloatField(default=0.0, help_text="Baseline 평균 속도(px/s)")
    baseline_std     = models.FloatField(default=0.0, help_text="Baseline 속도 표준편차(px/s)")
    current_mean     = models.FloatField(default=0.0, help_text="현재 기간 평균 속도(px/s)")
    deviation_ratio  = models.FloatField(default=0.0, help_text="Baseline 대비 편차 비율")

    # 주간/야간 비교
    daytime_activity  = models.FloatField(default=0.0, help_text="주간(6~22시) 평균 활동량")
    nighttime_activity = models.FloatField(default=0.0, help_text="야간(22~6시) 평균 활동량")

    # 이상 패턴
    anomaly_hours = models.JSONField(default=list, help_text="이상 활동 감지 시간대 목록")
    has_anomaly   = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return f"[{self.tank.name}] 패턴분석 {self.period_start:%m/%d} — {self.created_at:%Y-%m-%d %H:%M}"


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

    tank           = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='devices')
    type           = models.CharField(max_length=20, choices=DEVICE_TYPES)
    is_on          = models.BooleanField(default=False)
    is_auto        = models.BooleanField(default=True, help_text="True: 자동 제어 / False: 수동 제어")
    last_action_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'monitoring'
        unique_together = ('tank', 'type')

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

    tank       = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='logs')
    level      = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='INFO')
    message    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return f"[{self.level}] {self.tank.name} — {self.created_at:%Y-%m-%d %H:%M}"