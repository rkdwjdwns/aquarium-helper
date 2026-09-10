"""
scripts/decision.py — 상태 판단 + 제한된 하드웨어 제어 정책 (project v4)

현재 실제 제어 대상은 3개로 한정한다.
- HEATER  : 수온 기반 히스테리시스 제어
- COOLING : 수온 기반 히스테리시스 제어
- LIGHT   : pi_client/light_timer.py의 시간 스케줄 제어

pH / DO / TDS는 모니터링 및 경고 입력이다.
- 실제 탁도 센서는 연결되어 있지 않으며 4번째 센서값은 TDS(ppm)이다.
- FILTER / AIR_PUMP / FEEDER 제어 명령은 생성하지 않는다.
- Activity / ABR / FRS 등 AI 행동 분석은 상태 판단에 사용한다.
- 조명은 별도 ai_control_policy.py가 ABR v2 기반 REST override를 수행한다.
- HEATER/COOLING은 AI가 아니라 수온 기반 rule control을 유지한다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.sensor_reader import SensorData

logger = logging.getLogger(__name__)


@dataclass
class ControlCommand:
    device: str  # HEATER | COOLING (LIGHT는 light_timer가 담당)
    is_on: bool
    reason: str
    priority: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecisionResult:
    timestamp: float
    commands: list[ControlCommand]
    alerts: list[str]
    water_score: int
    behavior_ok: bool


class Thresholds:
    """config.yaml의 현재 운영 기준을 읽는다."""

    def __init__(self, cfg: Optional[dict] = None):
        cfg = cfg or {}
        wq = cfg.get("water_quality", {})
        tc = wq.get("temperature_c", {})
        ph = wq.get("ph", {})
        do = wq.get("do_mg_l", {})

        self.heater_on = float(tc.get("actuator_heat_on", 21.5))
        self.heater_off = float(tc.get("actuator_heat_off", 24.0))
        self.cooling_on = float(tc.get("actuator_cool_on", 24.0))
        self.cooling_off = float(tc.get("actuator_cool_off", 23.0))

        self.temp_min = float(tc.get("min", 21.0))
        self.temp_max = float(tc.get("max", 24.0))
        self.ph_min = float(ph.get("min", 6.5))
        self.ph_max = float(ph.get("max", 8.0))
        self.do_min = float(do.get("min", 5.0))
        self.do_critical = float(do.get("critical_min", 4.0))

        self.abr_warning_pct = float(
            cfg.get("analytics", {}).get("abr", {}).get("warning_pct", 13.0)
        )

    @classmethod
    def from_yaml(cls, yaml_path: str = "config.yaml") -> "Thresholds":
        try:
            import yaml

            with open(yaml_path, encoding="utf-8") as f:
                return cls(yaml.safe_load(f) or {})
        except Exception as e:
            logger.warning("[Decision] config.yaml 로드 실패 -> 기본값 사용: %s", e)
            return cls()


class DecisionEngine:
    """센서/행동 상태를 평가한다.

    실제 하드웨어 제어 명령은 HEATER와 COOLING만 생성한다.
    조명은 light_timer.py가 시간 정책에 따라 별도로 제어한다.
    """

    def __init__(self, thresholds: Optional[Thresholds] = None):
        self.th = thresholds or Thresholds.from_yaml()
        self._prev: dict[str, bool] = {
            "HEATER": False,
            "COOLING": False,
        }

    def decide(
        self,
        sensor_data: "SensorData",
        behavior_result: Optional[dict] = None,
    ) -> DecisionResult:
        commands: list[ControlCommand] = []
        alerts: list[str] = []
        behavior = behavior_result or {}

        if sensor_data.valid:
            commands.extend(self._decide_temperature(sensor_data))
            self._check_sensor_alerts(sensor_data, alerts)

        self._check_behavior(behavior, alerts)

        water_score = self._calc_water_score(sensor_data)
        behavior_ok = not bool(behavior.get("is_anomaly", False))
        return DecisionResult(
            timestamp=time.time(),
            commands=commands,
            alerts=alerts,
            water_score=water_score,
            behavior_ok=behavior_ok,
        )

    def _decide_temperature(self, s: "SensorData") -> list[ControlCommand]:
        cmds: list[ControlCommand] = []
        t = float(s.temperature_c)

        # HEATER hysteresis
        if t < self.th.heater_on:
            target = True
            reason = f"수온 {t:.1f}C < {self.th.heater_on:.1f}C"
            priority = "critical" if t < 18.0 else "normal"
        elif t >= self.th.heater_off:
            target = False
            reason = f"수온 {t:.1f}C >= {self.th.heater_off:.1f}C"
            priority = "normal"
        else:
            target = self._prev["HEATER"]
            reason = "히터 상태 유지"
            priority = "low"
        if target != self._prev["HEATER"]:
            self._prev["HEATER"] = target
            cmds.append(ControlCommand("HEATER", target, reason, priority))

        # COOLING hysteresis
        if t > self.th.cooling_on:
            target = True
            reason = f"수온 {t:.1f}C > {self.th.cooling_on:.1f}C"
            priority = "normal"
        elif t <= self.th.cooling_off:
            target = False
            reason = f"수온 {t:.1f}C <= {self.th.cooling_off:.1f}C"
            priority = "normal"
        else:
            target = self._prev["COOLING"]
            reason = "냉각팬 상태 유지"
            priority = "low"
        if target != self._prev["COOLING"]:
            self._prev["COOLING"] = target
            cmds.append(ControlCommand("COOLING", target, reason, priority))

        return cmds

    def _check_sensor_alerts(self, s: "SensorData", alerts: list[str]) -> None:
        if s.ph < self.th.ph_min:
            alerts.append(f"pH 낮음: {s.ph:.2f} (기준 {self.th.ph_min:.1f} 이상)")
        elif s.ph > self.th.ph_max:
            alerts.append(f"pH 높음: {s.ph:.2f} (기준 {self.th.ph_max:.1f} 이하)")

        if s.do_mg_l < self.th.do_critical:
            alerts.append(f"DO 위험: {s.do_mg_l:.2f}mg/L")
        elif s.do_mg_l < self.th.do_min:
            alerts.append(f"DO 낮음: {s.do_mg_l:.2f}mg/L")

        # TDS는 표시/추세 관찰만 수행. NTU 임계값을 적용하지 않는다.
        if getattr(s, "tds_ppm", 0.0) <= 0:
            alerts.append("TDS 데이터 확인 필요")

    def _check_behavior(self, behavior: dict, alerts: list[str]) -> None:
        if not behavior or not behavior.get("dashboard_ready", False):
            return
        abr = behavior.get("abr_5min_pct")
        if abr is not None and float(abr) >= self.th.abr_warning_pct:
            alerts.append(
                "AI 행동 이상 확인 | "
                f"ABR5m={float(abr):.1f}% | "
                f"Activity={behavior.get('activity_state', 'UNKNOWN')} | "
                f"Quality={behavior.get('analysis_quality', 'UNKNOWN')}"
            )

    def _calc_water_score(self, s: "SensorData") -> int:
        if not s.valid:
            return 0
        score = 100
        t = float(s.temperature_c)
        if t < self.th.temp_min or t > self.th.temp_max:
            score -= 30
        else:
            score -= min(int(abs(t - 22.0) * 5), 15)

        if s.ph < 6.0 or s.ph > 8.5:
            score -= 30
        elif s.ph < self.th.ph_min or s.ph > self.th.ph_max:
            score -= 15

        if s.do_mg_l < self.th.do_critical:
            score -= 30
        elif s.do_mg_l < self.th.do_min:
            score -= 15

        # TDS는 아직 운영 임계값을 정의하지 않았으므로 점수에 반영하지 않는다.
        return max(0, int(score))

    def get_device_states(self) -> dict[str, bool]:
        return self._prev.copy()


if __name__ == "__main__":
    from scripts.sensor_reader import SensorData

    engine = DecisionEngine()
    for temp in (20.5, 22.5, 25.0, 22.5):
        sample = SensorData(
            timestamp=time.time(),
            temperature_c=temp,
            ph=7.2,
            do_mg_l=6.5,
            tds_ppm=340.0,
            valid=True,
        )
        result = engine.decide(sample)
        print(temp, [c.to_dict() for c in result.commands], result.alerts)
