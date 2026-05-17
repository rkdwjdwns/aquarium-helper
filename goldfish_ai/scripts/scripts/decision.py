"""
scripts/decision.py — 상태 판단 + 액추에이터 제어
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    수질 센서값 + 행동 분석 결과를 종합해서
    히터/냉각팬/여과기/에어펌프/급이기/조명 ON/OFF 판단.

    실제 GPIO 제어는 command_poller.py (pi_client/)가 담당.
    이 파일은 판단 로직만 담당하고 GPIO에 직접 접근하지 않음.

하드웨어 설계 명세서 4항 — 릴레이 자동 제어 기준표:
    히터       : 수온 22.0℃ 미만 가동 / 23.5℃ 도달 시 중단
    냉각팬     : 수온 25.5℃ 초과 가동 / 24.0℃ 도달 시 중단
    기포기     : DO 5.5mg/L 이하 가동 / DO 7.0mg/L 도달 시 중단
    여과기     : 탁도 50NTU 초과 가동 / 20NTU 이하 시 중단
    조명       : 오전 08:00 점등 / 오후 20:00 소등
    자동 급이기: 하루 3회 정량 / 급이 후 10분간 여과기 정지

GPIO 핀 배치 (command_poller.py RELAY_PINS 기준):
    HEATER   → 17
    COOLING  → 18
    FILTER   → 27
    AIR_PUMP → 22
    FEEDER   → 23
    LIGHT    → 24
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.sensor_reader import SensorData

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# 제어 명령 구조
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ControlCommand:
    """단일 액추에이터 제어 명령"""
    device:    str    # "HEATER" | "COOLING" | "FILTER" | "AIR_PUMP" | "FEEDER" | "LIGHT"
    is_on:     bool
    reason:    str    # 판단 근거 (로그용)
    priority:  str    # "critical" | "normal" | "low"
    timestamp: float  = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecisionResult:
    """전체 판단 결과"""
    timestamp:    float
    commands:     list[ControlCommand]
    alerts:       list[str]    # 경고 메시지 목록
    water_score:  int          # 수질 종합 점수 (0~100)
    behavior_ok:  bool         # 행동 정상 여부


# ─────────────────────────────────────────────────────────────────────────
# 임계값 설정 (config.yaml water_quality / analytics 섹션과 동기화)
# ─────────────────────────────────────────────────────────────────────────
class Thresholds:
    """
    설계 문서 3.3 + config.yaml 기준값.
    config.yaml을 직접 읽어서 초기화하거나 기본값 사용.
    """

    def __init__(self, cfg: Optional[dict] = None):
        wq = (cfg or {}).get("water_quality", {})
        tc = wq.get("temperature_c", {})
        do = wq.get("do_mg_l", {})
        tb = wq.get("turbidity_ntu", {})

        # 수온 — 명세서 4항 기준
        self.heater_on:   float = tc.get("actuator_heat_on",  22.0)  # 22.0℃ 미만 가동
        self.heater_off:  float = tc.get("actuator_heat_off", 23.5)  # 23.5℃ 도달 중단
        self.cooling_on:  float = tc.get("actuator_cool_on",  25.5)  # 25.5℃ 초과 가동
        self.cooling_off: float = tc.get("actuator_cool_off", 24.0)  # 24.0℃ 도달 중단

        # DO (용존산소) — 명세서 4항 기준
        self.airpump_on:  float = do.get("actuator_on",  5.5)  # 5.5mg/L 이하 가동
        self.airpump_off: float = do.get("actuator_off", 7.0)  # 7.0mg/L 도달 중단

        # 탁도
        self.filter_on:  float = tb.get("actuator_filter_on",  50.0)
        self.filter_off: float = tb.get("actuator_filter_off", 20.0)

        # pH 경고 범위
        ph_cfg = wq.get("ph", {})
        self.ph_min: float = ph_cfg.get("min", 6.5)
        self.ph_max: float = ph_cfg.get("max", 8.0)

        # 행동 이상 판정
        self.abr_critical:   float = 0.5   # POOR 상태
        self.abr_warning:    float = 0.3   # WARNING 상태
        self.top_ratio_warn: float = 0.7   # 수면 과다 집군

    @classmethod
    def from_yaml(cls, yaml_path: str = "config.yaml") -> "Thresholds":
        """config.yaml에서 임계값 로드."""
        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            return cls(cfg)
        except Exception as e:
            logger.warning(f"[Decision] config.yaml 로드 실패 → 기본값 사용: {e}")
            return cls()


# ─────────────────────────────────────────────────────────────────────────
# DecisionEngine
# ─────────────────────────────────────────────────────────────────────────
class DecisionEngine:
    """
    수질 센서 + 행동 분석 결과 → 액추에이터 제어 명령 생성.

    실제 GPIO 제어는 command_poller.py가 담당.
    이 클래스는 판단 로직만 담당.
    """

    def __init__(self, thresholds: Optional[Thresholds] = None):
        self.th = thresholds or Thresholds.from_yaml()

        # 이전 상태 (채터링 방지 — 상태가 바뀔 때만 명령 생성)
        self._prev: dict[str, bool] = {
            "HEATER":   False,
            "COOLING":  False,
            "FILTER":   False,
            "AIR_PUMP": False,
            "FEEDER":   False,
            "LIGHT":    False,
        }

    # ══════════════════════════════════════════════════════════════════════
    # 메인 판단
    # ══════════════════════════════════════════════════════════════════════

    def decide(
        self,
        sensor_data:     "SensorData",
        behavior_result: Optional[dict] = None,
    ) -> DecisionResult:
        """
        센서 + 행동 데이터 기반 제어 명령 생성.

        Args:
            sensor_data:     SensorData 인스턴스
            behavior_result: BehaviorBridge.get_latest() 반환값

        Returns:
            DecisionResult (commands, alerts, water_score, behavior_ok)
        """
        commands: list[ControlCommand] = []
        alerts:   list[str]            = []
        behavior = behavior_result or {}

        if sensor_data.valid:
            commands += self._decide_temperature(sensor_data, alerts)
            commands += self._decide_airpump(sensor_data, alerts)
            commands += self._decide_filter(sensor_data, alerts)
            self._check_ph(sensor_data, alerts)

        if behavior:
            commands += self._decide_from_behavior(behavior, alerts)

        water_score = self._calc_water_score(sensor_data)
        behavior_ok = not behavior.get("is_anomaly", False)

        # 로그
        if commands:
            for cmd in commands:
                logger.info(
                    f"[Decision] {cmd.device:<10} → {'ON ' if cmd.is_on else 'OFF'} "
                    f"[{cmd.priority}] {cmd.reason}"
                )
        if alerts:
            for alert in alerts:
                logger.warning(f"[Decision] ⚠️  {alert}")

        return DecisionResult(
            timestamp    = time.time(),
            commands     = commands,
            alerts       = alerts,
            water_score  = water_score,
            behavior_ok  = behavior_ok,
        )

    # ══════════════════════════════════════════════════════════════════════
    # 개별 판단 로직
    # ══════════════════════════════════════════════════════════════════════

    def _decide_temperature(
        self, s: "SensorData", alerts: list
    ) -> list[ControlCommand]:
        """
        수온 기반 히터/냉각팬 제어.

        명세서 4항:
            히터   : 22.0℃ 미만 가동 / 23.5℃ 도달 중단
            냉각팬 : 25.5℃ 초과 가동 / 24.0℃ 도달 중단
        """
        cmds = []
        t = s.temperature_c

        # 히터
        if t < self.th.heater_on:
            heater_on = True
            reason    = f"수온 {t:.1f}°C < 기준 {self.th.heater_on}°C"
            priority  = "critical" if t < 18.0 else "normal"
        elif t >= self.th.heater_off:   # 히스테리시스: heater_off(23.5℃) 도달 시 중단
            heater_on = False
            reason    = f"수온 {t:.1f}°C → {self.th.heater_off}°C 도달, 중단"
            priority  = "normal"
        else:
            heater_on = self._prev["HEATER"]   # 유지
            reason    = "유지"
            priority  = "low"

        if heater_on != self._prev["HEATER"]:
            cmds.append(ControlCommand("HEATER", heater_on, reason, priority))
            self._prev["HEATER"] = heater_on

        # 냉각팬
        if t > self.th.cooling_on:
            cooling_on = True
            reason     = f"수온 {t:.1f}°C > 기준 {self.th.cooling_on}°C"
            priority   = "critical" if t > 28.0 else "normal"
            alerts.append(f"수온 과열: {t:.1f}°C")
        elif t <= self.th.cooling_off:
            cooling_on = False
            reason     = f"수온 {t:.1f}°C 정상화"
            priority   = "normal"
        else:
            cooling_on = self._prev["COOLING"]
            reason     = "유지"
            priority   = "low"

        if cooling_on != self._prev["COOLING"]:
            cmds.append(ControlCommand("COOLING", cooling_on, reason, priority))
            self._prev["COOLING"] = cooling_on

        return cmds

    def _decide_airpump(
        self, s: "SensorData", alerts: list
    ) -> list[ControlCommand]:
        """
        DO 기반 기포기(에어펌프) 제어.

        명세서 4항:
            기포기 : DO 5.5mg/L 이하 가동 / DO 7.0mg/L 도달 중단
            (밀집으로 인한 돌연사 방지 — 최우선순위)
        """
        do = s.do_mg_l

        if do <= self.th.airpump_on:
            is_on    = True
            reason   = f"DO {do:.1f}mg/L ≤ 임계값 {self.th.airpump_on}"
            priority = "critical"
            alerts.append(f"DO 위험 수준: {do:.1f}mg/L (즉각 에어펌프 가동)")
        elif do >= self.th.airpump_off:
            is_on    = False
            reason   = f"DO {do:.1f}mg/L ≥ 정상 {self.th.airpump_off}"
            priority = "normal"
        else:
            is_on    = self._prev["AIR_PUMP"]
            reason   = "유지"
            priority = "low"

        if is_on != self._prev["AIR_PUMP"]:
            self._prev["AIR_PUMP"] = is_on
            return [ControlCommand("AIR_PUMP", is_on, reason, priority)]
        return []

    def _decide_filter(
        self, s: "SensorData", alerts: list
    ) -> list[ControlCommand]:
        """
        탁도 기반 여과기 제어.

        설계 문서 3.3:
            여과기: 탁도 50 NTU 초과 시 가동 / 20 NTU 이하 시 중단
        """
        ntu = s.turbidity_ntu

        if ntu > self.th.filter_on:
            is_on    = True
            reason   = f"탁도 {ntu:.1f}NTU > {self.th.filter_on}"
            priority = "normal"
            if ntu > 100:
                alerts.append(f"탁도 스트레스 수준: {ntu:.1f}NTU")
        elif ntu <= self.th.filter_off:
            is_on    = False
            reason   = f"탁도 {ntu:.1f}NTU ≤ {self.th.filter_off}"
            priority = "low"
        else:
            is_on    = self._prev["FILTER"]
            reason   = "유지"
            priority = "low"

        if is_on != self._prev["FILTER"]:
            self._prev["FILTER"] = is_on
            return [ControlCommand("FILTER", is_on, reason, priority)]
        return []

    def _check_ph(self, s: "SensorData", alerts: list):
        """pH 경고만 생성 (직접 제어 장치 없음)."""
        if s.ph < self.th.ph_min:
            alerts.append(f"pH 낮음: {s.ph:.2f} (기준 {self.th.ph_min} 이상)")
        elif s.ph > self.th.ph_max:
            alerts.append(f"pH 높음: {s.ph:.2f} (기준 {self.th.ph_max} 이하)")

    def _decide_from_behavior(
        self, behavior: dict, alerts: list
    ) -> list[ControlCommand]:
        """
        행동 분석 결과 기반 추가 판단.

        현재 구현:
            - 수면 과다 집군(top_ratio > 0.7) → 에어펌프 강제 가동 경고
            - 이상 행동(is_anomaly) → 경고 생성
        """
        cmds = []
        top_ratio  = behavior.get("zone_top_ratio", 0.0)
        is_anomaly = behavior.get("is_anomaly", False)
        abr_score  = behavior.get("abr_score", 0.0)
        status     = behavior.get("status", "NORMAL")

        # 수면 과다 집군 → 에어펌프 추가 가동
        if top_ratio > self.th.top_ratio_warn:
            if not self._prev["AIR_PUMP"]:
                cmds.append(ControlCommand(
                    "AIR_PUMP", True,
                    f"수면 집군 {top_ratio:.0%} — 산소 부족 의심",
                    "normal",
                ))
                self._prev["AIR_PUMP"] = True
            alerts.append(f"수면 과다 집군: {top_ratio:.0%} — DO 확인 필요")

        if is_anomaly:
            alerts.append(f"이상 행동 감지 | ABR={abr_score:.3f} | 상태={status}")

        return cmds

    # ══════════════════════════════════════════════════════════════════════
    # 수질 점수
    # ══════════════════════════════════════════════════════════════════════

    def _calc_water_score(self, s: "SensorData") -> int:
        """
        수질 항목별 점수 합산 → 0~100.
        백엔드 sensor_sender.py 응답의 water_quality_score와 유사.
        """
        if not s.valid:
            return 0

        score = 100

        # 수온 (±2°C 벗어날 때마다 -10)
        t_diff = abs(s.temperature_c - 22.0)
        score -= min(int(t_diff * 5), 30)

        # pH (기준 밖 -20)
        if not (self.th.ph_min <= s.ph <= self.th.ph_max):
            score -= 20

        # DO (5.5mg/L 이하 -15, 4.0mg/L 이하 추가 -15)
        if s.do_mg_l < 4.0:    score -= 30
        elif s.do_mg_l < 5.5:  score -= 15

        # 탁도 (50NTU 이상 -10, 100NTU 이상 추가 -10)
        if s.turbidity_ntu > 100: score -= 20
        elif s.turbidity_ntu > 50: score -= 10

        return max(score, 0)

    # ══════════════════════════════════════════════════════════════════════
    # 상태 조회
    # ══════════════════════════════════════════════════════════════════════

    def get_device_states(self) -> dict[str, bool]:
        """현재 모든 장치의 ON/OFF 상태 반환."""
        return self._prev.copy()


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import logging
    logging.basicConfig(level=logging.INFO)

    from scripts.sensor_reader import SensorData

    engine = DecisionEngine()

    # 정상 수질 테스트
    print("\n[테스트 1] 정상 수질")
    normal = SensorData(
        timestamp=0, temperature_c=22.5, ph=7.2,
        do_mg_l=6.8, turbidity_ntu=12.3, valid=True
    )
    result = engine.decide(normal)
    print(f"  수질점수: {result.water_score} | 명령: {len(result.commands)}개 | 경고: {result.alerts}")

    # DO 위험 테스트
    print("\n[테스트 2] DO 위험 (3.5mg/L)")
    danger = SensorData(
        timestamp=0, temperature_c=22.5, ph=7.2,
        do_mg_l=3.5, turbidity_ntu=12.3, valid=True
    )
    result = engine.decide(danger)
    print(f"  수질점수: {result.water_score} | 명령: {len(result.commands)}개 | 경고: {result.alerts}")
    for cmd in result.commands:
        print(f"  → {cmd.device} {'ON' if cmd.is_on else 'OFF'} [{cmd.priority}] {cmd.reason}")

    # 고온 테스트
    print("\n[테스트 3] 고온 (27°C)")
    hot = SensorData(
        timestamp=0, temperature_c=27.0, ph=7.2,
        do_mg_l=6.0, turbidity_ntu=15.0, valid=True
    )
    result = engine.decide(hot)
    print(f"  수질점수: {result.water_score} | 명령: {len(result.commands)}개 | 경고: {result.alerts}")
    for cmd in result.commands:
        print(f"  → {cmd.device} {'ON' if cmd.is_on else 'OFF'} [{cmd.priority}] {cmd.reason}")

    # 행동 이상 테스트
    print("\n[테스트 4] 행동 이상 (수면 집군)")
    behavior = {
        "zone_top_ratio": 0.75, "is_anomaly": True,
        "abr_score": 0.35, "status": "WARNING"
    }
    result = engine.decide(normal, behavior)
    print(f"  behavior_ok: {result.behavior_ok} | 경고: {result.alerts}")
    for cmd in result.commands:
        print(f"  → {cmd.device} {'ON' if cmd.is_on else 'OFF'} [{cmd.priority}] {cmd.reason}")

    print(f"\n  현재 장치 상태: {engine.get_device_states()}")
