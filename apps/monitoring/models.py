from django.db import models
from django.conf import settings


# ──────────────────────────────────────────────
# 어항
# ──────────────────────────────────────────────

class Tank(models.Model):
    """어항 기본 정보 및 제어 설정"""

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

    # ✅ 추가: 수질 기준값 (사용자 설정)
    temp_min       = models.FloatField(default=21.0, help_text="수온 최솟값(°C)")
    temp_max       = models.FloatField(default=24.0, help_text="수온 최댓값(°C)")
    ph_min         = models.FloatField(default=6.5,  help_text="pH 최솟값")
    ph_max         = models.FloatField(default=8.0,  help_text="pH 최댓값")
    do_min         = models.FloatField(default=5.0,  help_text="DO 최솟값(mg/L)")
    turbidity_max  = models.FloatField(default=50.0, help_text="탁도 최댓값(NTU)")

    # ✅ 추가: 장치 자동제어 히스테리시스 기준
    heater_on_temp   = models.FloatField(default=21.0, help_text="히터 ON 기준(°C)")
    heater_off_temp  = models.FloatField(default=22.0, help_text="히터 OFF 기준(°C)")
    cooling_on_temp  = models.FloatField(default=24.0, help_text="냉각팬 ON 기준(°C)")
    cooling_off_temp = models.FloatField(default=23.0, help_text="냉각팬 OFF 기준(°C)")
    filter_on_ntu    = models.FloatField(default=50.0, help_text="여과기 ON 기준(NTU)")
    filter_off_ntu   = models.FloatField(default=20.0, help_text="여과기 OFF 기준(NTU)")
    airpump_on_do    = models.FloatField(default=4.0,  help_text="에어펌프 ON 기준(mg/L)")
    airpump_off_do   = models.FloatField(default=6.0,  help_text="에어펌프 OFF 기준(mg/L)")

    # ✅ 추가: 급이 설정
    feeding_times      = models.CharField(max_length=200, default="08:00,12:00,18:00", help_text="급이 시간 (콤마 구분)")
    feeding_amount_g   = models.FloatField(default=0.1, help_text="1회 급이량(g)")
    feeding_auto       = models.BooleanField(default=True, help_text="자동 급이 사용")

    # ✅ 추가: 조명 타이머
    light_on_hour  = models.IntegerField(default=8,  help_text="조명 점등 시각(시)")
    light_off_hour = models.IntegerField(default=20, help_text="조명 소등 시각(시)")
    light_auto     = models.BooleanField(default=True, help_text="조명 자동 제어")

    # 환수 관리
    last_water_change   = models.DateField(null=True, blank=True, help_text="마지막 환수일")
    water_change_period = models.IntegerField(default=7, help_text="환수 주기(일)")

    # ✅ 추가: Pi 카메라 연결 정보 (Pi가 자동 등록)
    pi_ip = models.CharField(max_length=200, null=True, blank=True, help_text="Raspberry Pi IP 또는 카메라 URL")
    pi_stream_port = models.IntegerField(default=8080, help_text="카메라 스트림 포트")
    pi_last_seen   = models.DateTimeField(null=True, blank=True, help_text="Pi 마지막 접속 시각")

    # ✅ 수정: filter_mode, filter_is_on 제거
    # → 장치 상태는 DeviceControl 모델로 통일 관리
    # → Tank.devices.get(type='FILTER') 로 조회

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return self.name

    # ✅ 추가: DeviceControl 편의 프로퍼티
    @property
    def filter_is_on(self):
        """여과기 ON/OFF 상태 — DeviceControl에서 읽어옴"""
        device = self.devices.filter(type='FILTER').first()
        return device.is_on if device else False

    @property
    def filter_is_auto(self):
        """여과기 자동/수동 모드 — DeviceControl에서 읽어옴"""
        device = self.devices.filter(type='FILTER').first()
        return device.is_auto if device else True

    @property
    def camera_stream_url(self):
        """실제 MJPEG 스트림 URL — pi_ip에 URL(https://...)이 저장된 경우와
        순수 IP만 저장된 경우(register_pi) 둘 다 대응"""
        if not self.pi_ip:
            return None
        if self.pi_ip.startswith('http://') or self.pi_ip.startswith('https://'):
            return f"{self.pi_ip}/stream.mjpg"
        return f"http://{self.pi_ip}:{self.pi_stream_port}/stream.mjpg"

    @property
    def is_camera_online(self):
        """마지막 접속이 2분 이내면 온라인으로 간주"""
        if not self.pi_last_seen:
            return False
        from django.utils import timezone
        return (timezone.now() - self.pi_last_seen).total_seconds() < 120


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
        ('FRY',   '치어 (1~3cm)'),
        ('YOUNG', '유어 (3~7cm)'),
        ('ADULT', '성어 (7cm+)'),
    ]

    tank = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='feeding_events')

    # 급이 정보
    trigger      = models.CharField(max_length=10, choices=TRIGGER_CHOICES, default='AUTO', help_text="급이 트리거")
    amount_g     = models.FloatField(default=0.0, help_text="급이량(g)")
    growth_stage = models.CharField(max_length=10, choices=STAGE_CHOICES, default='FRY', help_text="성장 단계")

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
    feeding_event = models.OneToOneField(
        FeedingEvent,
        on_delete=models.CASCADE,
        related_name='response',
        null=True,
        blank=True,
    )

    # FRS 구성 지표
    rt_seconds = models.FloatField(default=0.0, help_text="반응시간(초): 급이→수면 첫 접근까지")
    ar_ratio   = models.FloatField(default=0.0, help_text="활동증가율: 급이중/급이전 avg_speed 비율")
    sf_ratio   = models.FloatField(default=0.0, help_text="수면접근빈도: 급이구간 TOP zone 체류 비율")

    # FRS 최종 점수
    frs_score = models.IntegerField(default=0, help_text="급이 반응 점수(0~100)")

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
    size_index       = models.FloatField(help_text="size_index(%) = bbox면적/프레임면적×100")
    estimated_length = models.FloatField(default=0.0, help_text="추정 체장(cm)")
    estimated_weight = models.FloatField(default=0.0, help_text="추정 체중(g) — W=0.01049×TL^3.14")

    # 성장률
    growth_rate  = models.FloatField(default=0.0, help_text="성장률(cm/day)")
    growth_stage = models.CharField(max_length=10, choices=STAGE_CHOICES, default='FRY')

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
    baseline_mean   = models.FloatField(default=0.0, help_text="Baseline 평균 속도(px/s)")
    baseline_std    = models.FloatField(default=0.0, help_text="Baseline 속도 표준편차(px/s)")
    current_mean    = models.FloatField(default=0.0, help_text="현재 기간 평균 속도(px/s)")
    deviation_ratio = models.FloatField(default=0.0, help_text="Baseline 대비 편차 비율")

    # 주간/야간 비교
    daytime_activity   = models.FloatField(default=0.0, help_text="주간(6~22시) 평균 활동량")
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
        app_label    = 'monitoring'
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

    # ✅ 추가: 이벤트 종류 필드 — 나중에 로그 필터링/통계에 활용
    EVENT_TYPE_CHOICES = [
        ('SENSOR_ALERT',   '수질 경보'),
        ('DEVICE_CHANGE',  '장치 상태 변경'),
        ('ANOMALY',        '행동 이상 감지'),
        ('FEEDING',        '급이 이벤트'),
        ('OVERFEEDING',    '과급여 감지'),
        ('WATER_CHANGE',   '환수 알림'),
        ('SYSTEM',         '시스템'),
    ]

    tank       = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='logs')
    level      = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='INFO')
    event_type = models.CharField(             # ✅ 추가
        max_length=20,
        choices=EVENT_TYPE_CHOICES,
        default='SYSTEM',
        help_text="이벤트 종류",
    )
    message    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['-created_at']

    def __str__(self):
        return f"[{self.level}] {self.event_type} — {self.tank.name} {self.created_at:%Y-%m-%d %H:%M}"

# ──────────────────────────────────────────────
# 어항 상태 진단 코드 백과사전
# ──────────────────────────────────────────────

class StateCode(models.Model):
    """수온/DO/pH/탁도 등 어항 상태를 설명하는 진단 코드"""

    CATEGORY_CHOICES = [
        ('TEMP', '수온'),
        ('PH', 'pH'),
        ('DO', '용존산소'),
        ('TURBIDITY', '탁도'),
        ('BEHAVIOR', '행동'),
        ('SYSTEM', '시스템'),
    ]

    LEVEL_CHOICES = [
        ('INFO', '정보'),
        ('WARNING', '주의'),
        ('DANGER', '위험'),
    ]

    code = models.CharField(max_length=30, unique=True)
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES
    )

    level = models.CharField(
        max_length=10,
        choices=LEVEL_CHOICES,
        default='WARNING'
    )

    title = models.CharField(max_length=100)

    description = models.TextField(blank=True)

    causes = models.JSONField(
        default=list,
        blank=True,
        help_text="발생 가능한 원인 목록"
    )

    effects = models.JSONField(
        default=list,
        blank=True,
        help_text="물고기에게 미칠 수 있는 영향 목록"
    )

    actions = models.JSONField(
        default=list,
        blank=True,
        help_text="사용자 조치 방법 목록"
    )

    prevention = models.JSONField(
        default=list,
        blank=True,
        help_text="예방 방법 목록"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'monitoring'
        ordering = ['category', 'code']

    def __str__(self):
        return f"{self.code} - {self.title}"


class TankStateEvent(models.Model):
    """특정 어항에서 실제 발생한 상태 코드 기록"""

    tank = models.ForeignKey(
        Tank,
        on_delete=models.CASCADE,
        related_name='state_events'
    )

    state_code = models.ForeignKey(
        StateCode,
        on_delete=models.PROTECT,
        related_name='events'
    )

    current_value = models.FloatField(
        null=True,
        blank=True
    )

    evidence = models.JSONField(
        default=dict,
        blank=True
    )

    is_resolved = models.BooleanField(default=False)

    detected_at = models.DateTimeField(auto_now_add=True)

    resolved_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        app_label = 'monitoring'
        ordering = ['-detected_at']

        indexes = [
            models.Index(
                fields=['tank', 'is_resolved']
            ),
            models.Index(
                fields=['tank', 'state_code', 'is_resolved']
            ),
        ]

    def __str__(self):
        status = "해결" if self.is_resolved else "발생중"

        return (
            f"[{self.tank.name}] "
            f"{self.state_code.code} - {status}"
        )


class FishActivityDetail(models.Model):
    """개체별 활동/이상행동 지표 — FishBehavior 스냅샷에 딸린 개체별 상세값"""

    ZONE_CHOICES = FishBehavior.ZONE_CHOICES

    behavior = models.ForeignKey(
        FishBehavior,
        on_delete=models.CASCADE,
        related_name='fish_details',
    )
    tank    = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='fish_activity_details')
    fish_id = models.IntegerField(help_text="ByteTrack 개체 ID")

    activity_level = models.FloatField(default=0.0, help_text="개체 활동량(px/s)")
    dominant_zone  = models.CharField(max_length=3, choices=ZONE_CHOICES, default='MID')
    abr_score      = models.FloatField(default=0.0, help_text="개체 이상행동율(0~1)")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'monitoring'
        ordering  = ['fish_id']

    def __str__(self):
        return f"[{self.tank.name}] Fish#{self.fish_id} act={self.activity_level} abr={self.abr_score}"