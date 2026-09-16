"""AI supervisory control policy for the aquarium light.

The policy intentionally controls only LIGHT and only as a temporary REST override.
Temperature safety/comfort control (HEATER, COOLING) remains sensor/rule based.
AIR_PUMP is always-on and FEEDER is outside external control.

Control rule (project v4):
- Use calibrated ABR v2 as the primary AI signal.
- Only evaluate data whose dashboard_ready is true and whose analysis quality is allowed.
- First consecutive ABR alert -> WATCH, no physical action.
- N consecutive alerts while the schedule wants the light ON -> REST and force LIGHT OFF.
- Keep REST for a fixed minimum duration, then release the override and return to schedule control.
- Apply a cooldown after REST to prevent repeated light toggling.

This is a supervisory policy, not a health/disease diagnosis.
"""
from __future__ import annotations

import csv
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class AIControlDecision:
    timestamp: float
    state: str                  # NORMAL | WATCH | REST
    force_light_off: bool
    action: str                 # NONE | LIGHT_OFF | RELEASE_TO_SCHEDULE
    reason: str
    abr_5min_pct: Optional[float]
    activity_state: str
    analysis_quality: str
    dashboard_ready: bool
    consecutive_alerts: int
    rest_until: Optional[float]
    cooldown_until: Optional[float]
    cooldown_active: bool

    def to_dict(self) -> dict:
        return asdict(self)


class AIControlPolicy:
    """Stateful ABR-based supervisory controller for aquarium lighting."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        abr_threshold_pct: float = 13.0,
        consecutive_alerts_required: int = 2,
        rest_minutes: float = 20.0,
        cooldown_minutes: float = 30.0,
        allowed_quality: Iterable[str] = ("GOOD", "FAIR"),
        require_schedule_on: bool = True,
        decision_log_csv: str = "data/presentation/ai_control_decisions.csv",
    ) -> None:
        self.enabled = bool(enabled)
        self.abr_threshold_pct = float(abr_threshold_pct)
        self.consecutive_alerts_required = max(1, int(consecutive_alerts_required))
        self.rest_sec = max(0.0, float(rest_minutes) * 60.0)
        self.cooldown_sec = max(0.0, float(cooldown_minutes) * 60.0)
        self.allowed_quality = {str(q).upper() for q in allowed_quality}
        self.require_schedule_on = bool(require_schedule_on)
        self.decision_log_csv = Path(decision_log_csv)

        self._consecutive_alerts = 0
        self._rest_until: Optional[float] = None
        self._cooldown_until: Optional[float] = None
        self._last_state = "NORMAL"
        self._last_force_light_off = False

    @classmethod
    def from_config(cls, cfg: Optional[dict] = None) -> "AIControlPolicy":
        cfg = cfg or {}
        root = cfg.get("ai_control", {}) or {}
        light = root.get("light_rest", {}) or {}
        return cls(
            enabled=root.get("enabled", True) and light.get("enabled", True),
            abr_threshold_pct=light.get("abr_threshold_pct", 13.0),
            consecutive_alerts_required=light.get("consecutive_alerts", 2),
            rest_minutes=light.get("rest_minutes", 20),
            cooldown_minutes=light.get("cooldown_minutes", 30),
            allowed_quality=light.get("allowed_quality", ["GOOD", "FAIR"]),
            require_schedule_on=light.get("require_schedule_on", True),
            decision_log_csv=light.get(
                "decision_log_csv",
                "data/presentation/ai_control_decisions.csv",
            ),
        )

    @property
    def is_rest_active(self) -> bool:
        now = time.time()
        return self._rest_until is not None and now < self._rest_until

    def evaluate(
        self,
        behavior: Optional[dict],
        *,
        schedule_light_on: bool,
        now: Optional[float] = None,
    ) -> AIControlDecision:
        now = float(time.time() if now is None else now)
        behavior = behavior or {}

        abr_raw = behavior.get("abr_5min_pct")
        try:
            abr = float(abr_raw) if abr_raw is not None else None
        except (TypeError, ValueError):
            abr = None
        activity_state = str(behavior.get("activity_state", "UNKNOWN") or "UNKNOWN")
        quality = str(behavior.get("analysis_quality", "POOR") or "POOR").upper()
        ready = bool(behavior.get("dashboard_ready", False))

        # REST has priority over all new analysis. Release only after the minimum
        # REST period has elapsed.
        if self._rest_until is not None and now < self._rest_until:
            return self._decision(
                now=now,
                state="REST",
                force_light_off=True,
                action="NONE",
                reason="AI REST 유지 중",
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        if self._rest_until is not None and now >= self._rest_until:
            self._rest_until = None
            self._cooldown_until = now + self.cooldown_sec if self.cooldown_sec > 0 else None
            self._consecutive_alerts = 0
            return self._decision(
                now=now,
                state="NORMAL",
                force_light_off=False,
                action="RELEASE_TO_SCHEDULE",
                reason="AI REST 종료 - 조명 스케줄 제어로 복귀",
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        cooldown_active = self._cooldown_until is not None and now < self._cooldown_until
        if self._cooldown_until is not None and now >= self._cooldown_until:
            self._cooldown_until = None
            cooldown_active = False

        if not self.enabled:
            self._consecutive_alerts = 0
            return self._decision(
                now=now,
                state="NORMAL",
                force_light_off=False,
                action="NONE",
                reason="AI 조명 제어 비활성화",
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        if not ready or quality not in self.allowed_quality or abr is None:
            self._consecutive_alerts = 0
            return self._decision(
                now=now,
                state="NORMAL",
                force_light_off=False,
                action="NONE",
                reason="AI 제어 판단 보류 - 분석 데이터 품질/준비 상태 부족",
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        is_alert = abr >= self.abr_threshold_pct
        if not is_alert:
            self._consecutive_alerts = 0
            return self._decision(
                now=now,
                state="NORMAL",
                force_light_off=False,
                action="NONE",
                reason=f"ABR 정상 범위 ({abr:.1f}% < {self.abr_threshold_pct:.1f}%)",
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        if cooldown_active:
            self._consecutive_alerts = 0
            return self._decision(
                now=now,
                state="WATCH",
                force_light_off=False,
                action="NONE",
                reason="ABR 이상 지속 - AI REST 재진입 쿨다운 중",
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        if self.require_schedule_on and not schedule_light_on:
            self._consecutive_alerts = 0
            return self._decision(
                now=now,
                state="WATCH",
                force_light_off=False,
                action="NONE",
                reason="ABR 이상 감지 - 현재 조명 스케줄이 OFF라 추가 제어 없음",
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        self._consecutive_alerts += 1
        if self._consecutive_alerts < self.consecutive_alerts_required:
            return self._decision(
                now=now,
                state="WATCH",
                force_light_off=False,
                action="NONE",
                reason=(
                    f"ABR 이상 1차 확인 ({self._consecutive_alerts}/"
                    f"{self.consecutive_alerts_required})"
                ),
                abr=abr,
                activity_state=activity_state,
                quality=quality,
                ready=ready,
            )

        self._rest_until = now + self.rest_sec
        self._consecutive_alerts = 0
        return self._decision(
            now=now,
            state="REST",
            force_light_off=True,
            action="LIGHT_OFF",
            reason=(
                f"ABR {abr:.1f}% 이상 지속 - AI REST {self.rest_sec / 60.0:.0f}분 진입"
            ),
            abr=abr,
            activity_state=activity_state,
            quality=quality,
            ready=ready,
        )

    def _decision(
        self,
        *,
        now: float,
        state: str,
        force_light_off: bool,
        action: str,
        reason: str,
        abr: Optional[float],
        activity_state: str,
        quality: str,
        ready: bool,
    ) -> AIControlDecision:
        cooldown_active = self._cooldown_until is not None and now < self._cooldown_until
        decision = AIControlDecision(
            timestamp=now,
            state=state,
            force_light_off=bool(force_light_off),
            action=action,
            reason=reason,
            abr_5min_pct=abr,
            activity_state=activity_state,
            analysis_quality=quality,
            dashboard_ready=ready,
            consecutive_alerts=self._consecutive_alerts,
            rest_until=self._rest_until,
            cooldown_until=self._cooldown_until,
            cooldown_active=cooldown_active,
        )

        # Log state/action transitions only. This keeps the presentation CSV
        # compact while still preserving the AI decision trail.
        if state != self._last_state or action != "NONE" or force_light_off != self._last_force_light_off:
            self._append_log(decision)
        self._last_state = state
        self._last_force_light_off = bool(force_light_off)
        return decision

    def _append_log(self, decision: AIControlDecision) -> None:
        try:
            path = self.decision_log_csv
            path.parent.mkdir(parents=True, exist_ok=True)
            exists = path.exists()
            row = {
                "timestamp": datetime.fromtimestamp(decision.timestamp).astimezone().isoformat(timespec="seconds"),
                "source_type": "RUNTIME_AI_DECISION",
                "ai_state": decision.state,
                "action": decision.action,
                "force_light_off": decision.force_light_off,
                "abr_5min_pct": "" if decision.abr_5min_pct is None else round(decision.abr_5min_pct, 3),
                "activity_state": decision.activity_state,
                "analysis_quality": decision.analysis_quality,
                "dashboard_ready": decision.dashboard_ready,
                "consecutive_alerts": decision.consecutive_alerts,
                "rest_until": (
                    "" if decision.rest_until is None
                    else datetime.fromtimestamp(decision.rest_until).astimezone().isoformat(timespec="seconds")
                ),
                "cooldown_until": (
                    "" if decision.cooldown_until is None
                    else datetime.fromtimestamp(decision.cooldown_until).astimezone().isoformat(timespec="seconds")
                ),
                "reason": decision.reason,
            }
            with path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                if not exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as exc:
            # Logging failure must never break the real-time AI loop.
            print(f"[AI-CONTROL] 의사결정 로그 저장 실패: {exc}")
