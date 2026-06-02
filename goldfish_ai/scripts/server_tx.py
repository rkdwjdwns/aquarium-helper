"""
scripts/server_tx.py — Pi → 백엔드 전송 브릿지
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    demo_pipeline.py의 분석 결과를 pi_client/ sender들이
    기대하는 페이로드 형식으로 변환해서 전송.

파일 구조:
    GOLDFISH_AI/
    ├── run.py
    ├── scripts/
    │   └── server_tx.py         ← 이 파일
    └── pi_client/               ← 백엔드 담당자 코드 (그대로 유지)
        ├── config.py
        ├── sensor_sender.py
        ├── behavior_sender.py
        ├── feeding_sender.py
        ├── growth_sender.py
        ├── pattern_sender.py
        └── register_pi.py

전송 항목:
    - 수질 센서        POST /api/sensor/       (10초 주기)
    - AI 행동 분석     POST /api/behavior/      (30초 주기)
    - 급이 이벤트+FRS  POST /api/feeding/       (급이 발생 시)
    - 성장 기록        POST /api/growth/        (1시간 주기)
    - 활동 패턴        POST /api/pattern/       (24시간 주기)
    - Pi IP 등록       POST /api/register-pi/   (시작 시 1회)
"""

from __future__ import annotations

import logging
import statistics
import sys
import time as _time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.sensor_reader import SensorData
    from scripts.analytics.abr import ABRResult

logger = logging.getLogger(__name__)

# ── pi_client 경로를 sys.path에 추가 ─────────────────────────────────────
_PI_CLIENT = Path(__file__).resolve().parent.parent / "pi_client"
if _PI_CLIENT.exists() and str(_PI_CLIENT) not in sys.path:
    sys.path.insert(0, str(_PI_CLIENT))
    logger.info(f"[ServerTx] pi_client 경로 추가: {_PI_CLIENT}")
else:
    logger.warning(f"[ServerTx] pi_client 폴더 없음: {_PI_CLIENT}")


# ─────────────────────────────────────────────────────────────────────────
# pi_client sender import (없으면 Mock으로 대체)
# ─────────────────────────────────────────────────────────────────────────
def _try_import() -> Optional[dict]:
    """
    pi_client sender들을 import 시도.
    실패 시 None 반환 → Mock 모드로 폴백.
    """
    try:
        from sensor_sender   import send_sensor      as _send_sensor
        from behavior_sender import send_behavior    as _send_behavior
        from feeding_sender  import send_feeding     as _send_feeding
        from growth_sender   import send_growth      as _send_growth
        from growth_sender   import estimate_weight  as _estimate_weight
        from pattern_sender  import send_pattern     as _send_pattern
        from pattern_sender  import ActivityPatternAnalyzer
        from register_pi     import register_pi_ip   as _register_pi

        return {
            "send_sensor":           _send_sensor,
            "send_behavior":         _send_behavior,
            "send_feeding":          _send_feeding,
            "send_growth":           _send_growth,
            "estimate_weight":       _estimate_weight,
            "send_pattern":          _send_pattern,
            "ActivityPatternAnalyzer": ActivityPatternAnalyzer,
            "register_pi":           _register_pi,
        }
    except ImportError as e:
        logger.warning(f"[ServerTx] pi_client import 실패 → Mock 모드: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────
# ServerTx
# ─────────────────────────────────────────────────────────────────────────
class ServerTx:
    """
    demo_pipeline.py 분석 결과 → pi_client sender 호환 페이로드 변환 후 전송.
    mock=True 또는 pi_client import 실패 시 실제 전송 없이 로그만 출력.
    """

    def __init__(self, mock: bool = False):
        self.mock     = mock
        self._senders = None if mock else _try_import()
        if self._senders is None:
            self.mock = True
            logger.warning("[ServerTx] Mock 모드로 실행 — 실제 전송 없음")
        else:
            logger.info("[ServerTx] 초기화 완료 — 실제 전송 모드")

        # ActivityPatternAnalyzer 인스턴스 (24시간 누적용)
        self._pattern_analyzer = None
        if not self.mock and self._senders:
            self._pattern_analyzer = self._senders["ActivityPatternAnalyzer"]()

        # 전송 통계
        self._stats = {
            k: {"ok": 0, "fail": 0}
            for k in ["sensor", "behavior", "feeding", "growth", "pattern", "event_log"]
        }

        # EventLog 중복 전송 방지 (같은 메시지 60초 내 재전송 억제)
        self._event_log_cache: dict[str, float] = {}

    # ══════════════════════════════════════════════════════════════════════
    # Pi IP 등록
    # ══════════════════════════════════════════════════════════════════════

    def register_pi(self) -> bool:
        """시작 시 Pi IP를 서버에 등록."""
        if self.mock:
            logger.info("[ServerTx][Mock] register_pi 호출")
            return True
        try:
            self._senders["register_pi"]()
            return True
        except Exception as e:
            logger.error(f"[ServerTx] Pi IP 등록 실패: {e}")
            return False

    # ══════════════════════════════════════════════════════════════════════
    # 수질 센서 전송
    # ══════════════════════════════════════════════════════════════════════

    def send_sensor(self, sensor_data: "SensorData") -> bool:
        """
        sensor_reader.SensorData → send_sensor() 전송.

        sensor_sender.py 파라미터:
            temperature, ph, dissolved_oxygen, turbidity, water_level
        """
        if not sensor_data.valid:
            logger.debug("[ServerTx] 센서 invalid — 건너뜀")
            return False

        if self.mock:
            logger.info(
                f"[ServerTx][Mock] send_sensor | "
                f"temp={sensor_data.temperature_c} ph={sensor_data.ph} "
                f"do={sensor_data.do_mg_l} ntu={sensor_data.turbidity_ntu}"
            )
            return True

        try:
            result = self._senders["send_sensor"](
                temperature      = sensor_data.temperature_c,
                ph               = sensor_data.ph,
                dissolved_oxygen = sensor_data.do_mg_l,
                turbidity        = sensor_data.turbidity_ntu,
                water_level      = 100.0,  # 수위 센서 미구현 — 추후 연동
            )
            ok = result is not None
            self._stats["sensor"]["ok" if ok else "fail"] += 1
            return ok
        except Exception as e:
            logger.error(f"[ServerTx] send_sensor 오류: {e}")
            self._stats["sensor"]["fail"] += 1
            return False

    # ══════════════════════════════════════════════════════════════════════
    # 행동 분석 전송
    # ══════════════════════════════════════════════════════════════════════

    def send_behavior(
        self,
        metrics_rows: list[dict],
        abr_result:   Optional["ABRResult"] = None,
        frs_score:    int                   = 0,
        track_filter  = None,
    ) -> bool:
        """
        fish_metrics 버퍼 + ABR 결과 → send_behavior() 전송.

        behavior_sender.py 파라미터:
            fish_count, overlap_frames, activity_level, abr_score,
            dominant_zone, zone_top_ratio, zone_mid_ratio, zone_bot_ratio,
            size_index, feeding_score, status, is_anomaly, note
        """
        if not metrics_rows:
            logger.debug("[ServerTx] metrics_rows 비어 있음 — 건너뜀")
            return False

        payload = self._build_behavior_payload(
            metrics_rows, abr_result, frs_score
        )

        # ActivityPatternAnalyzer에 활동량 기록 (24시간 패턴용)
        if self._pattern_analyzer:
            self._pattern_analyzer.record(payload["activity_level"])

        if self.mock:
            logger.info(
                f"[ServerTx][Mock] send_behavior | "
                f"fish={payload['fish_count']} "
                f"activity={payload['activity_level']:.1f} "
                f"status={payload['status']}"
            )
            return True

        try:
            result = self._senders["send_behavior"](**payload)
            ok = result is not None
            self._stats["behavior"]["ok" if ok else "fail"] += 1
            return ok
        except Exception as e:
            logger.error(f"[ServerTx] send_behavior 오류: {e}")
            self._stats["behavior"]["fail"] += 1
            return False

    def _build_behavior_payload(
        self,
        rows:       list[dict],
        abr_result: Optional["ABRResult"],
        frs_score:  int,
    ) -> dict:
        """fish_metrics 행 → behavior_sender 페이로드 변환."""

        # 대표 ID 행만 사용
        repr_rows = [r for r in rows if r.get("is_representative", True)]
        if not repr_rows:
            repr_rows = rows

        # fish_count
        fish_ids   = {r["fish_id"] for r in repr_rows if "fish_id" in r}
        fish_count = len(fish_ids)

        # activity_level: 유효 속도 평균
        speeds = [r["speed_px_s"] for r in repr_rows
                  if r.get("speed_px_s", 0) > 0]
        activity_level = round(statistics.mean(speeds), 2) if speeds else 0.0

        # overlap_frames
        overlap_frames = sum(
            1 for r in repr_rows if r.get("overlap_count", 0) > 0
        )

        # zone 비율
        zones     = [r.get("zone", "MID") for r in repr_rows]
        n         = max(len(zones), 1)
        top_ratio = round(zones.count("TOP") / n, 3)
        mid_ratio = round(zones.count("MID") / n, 3)
        bot_ratio = round(zones.count("BOT") / n, 3)
        dominant_zone = max(
            {"TOP": top_ratio, "MID": mid_ratio, "BOT": bot_ratio},
            key=lambda k: {"TOP": top_ratio, "MID": mid_ratio, "BOT": bot_ratio}[k]
        )

        # size_index 평균
        sizes      = [r["size_index"] for r in repr_rows if "size_index" in r]
        size_index = round(statistics.mean(sizes), 3) if sizes else 0.0

        # ABR
        abr_score  = round(abr_result.rate, 4) if abr_result and abr_result.valid else 0.0
        is_anomaly = abr_score > 0.3

        # 상태 판정
        status = self._evaluate_status(activity_level, abr_score, top_ratio)

        # note: ABR per_fish_stats 요약
        note = ""
        if abr_result and abr_result.valid and abr_result.per_fish_stats:
            top = abr_result.per_fish_stats[0]
            note = (
                f"최고활동 ID#{top['fish_id']} "
                f"평균{top['mean_speed_px_s']:.0f}px/s "
                f"CV={top['cv']:.2f}"
            )

        return {
            "fish_count":     fish_count,
            "overlap_frames": overlap_frames,
            "activity_level": activity_level,
            "abr_score":      abr_score,
            "dominant_zone":  dominant_zone,
            "zone_top_ratio": top_ratio,
            "zone_mid_ratio": mid_ratio,
            "zone_bot_ratio": bot_ratio,
            "size_index":     size_index,
            "feeding_score":  frs_score,
            "status":         status,
            "is_anomaly":     is_anomaly,
            "note":           note,
        }

    @staticmethod
    def _evaluate_status(activity: float, abr: float, top_ratio: float) -> str:
        """
        activity_level, abr_score, top_ratio 기반 상태 판정.
        백엔드 FishBehavior.status 필드값과 일치:
        'EXCELLENT' | 'GOOD' | 'NORMAL' | 'WARNING' | 'POOR'
        """
        if abr > 0.5:                        return "POOR"
        if abr > 0.3:                        return "WARNING"
        if activity < 2.0:                   return "WARNING"  # 거의 무기력
        if top_ratio > 0.6:                  return "WARNING"  # 수면 과다 집군
        if activity > 5.0 and abr < 0.1:    return "EXCELLENT"
        if activity > 2.0 and abr < 0.2:    return "GOOD"
        return "NORMAL"

    # ══════════════════════════════════════════════════════════════════════
    # 급이 이벤트 전송
    # ══════════════════════════════════════════════════════════════════════

    def send_feeding(
        self,
        feeding_event,
        frs_result:     Optional[dict] = None,
        sensor_before:  Optional["SensorData"] = None,
        sensor_after:   Optional["SensorData"] = None,
        metrics_before: Optional[list[dict]]   = None,
        metrics_during: Optional[list[dict]]   = None,
        metrics_after:  Optional[list[dict]]   = None,
        growth_stage:   str = "FRY",
    ) -> bool:
        """
        FeedingEvent + FRS 결과 → send_feeding() 전송.

        feeding_sender.py 파라미터 (전체):
            trigger, amount_g, growth_stage,
            turbidity_before, turbidity_after, is_overfeeding,
            rt_seconds, ar_ratio, sf_ratio, frs_score,
            activity_before, activity_during, activity_after

        Args:
            feeding_event  : FeedingEventLogger.get_last_event()
            frs_result     : FeedingResponseAnalyzer.analyze() 반환값
            sensor_before  : 급이 전 SensorData
            sensor_after   : 급이 후 SensorData
            metrics_before : 급이 전 fish_metrics 행 리스트
            metrics_during : 급이 중 fish_metrics 행 리스트
            metrics_after  : 급이 후 fish_metrics 행 리스트
            growth_stage   : 현재 성장 단계 ('FRY'|'YOUNG'|'ADULT')
        """
        # trigger 변환: feeding_events는 소문자, feeding_sender는 대문자
        trigger = feeding_event.trigger.upper()

        # 탁도
        turbidity_before = (
            sensor_before.turbidity_ntu
            if sensor_before and sensor_before.valid else 0.0
        )
        turbidity_after = (
            sensor_after.turbidity_ntu
            if sensor_after and sensor_after.valid else 0.0
        )

        # 과급여 판단: 탁도 상승이 config의 overfeeding_delta_ntu 초과
        # (미확정 — 실측 후 조정, 현재는 10 NTU 기준)
        is_overfeeding = (turbidity_after - turbidity_before) > 10.0

        # FRS 세부 지표
        frs = frs_result or {}
        frs_score  = frs.get("score", 0)
        rt_seconds = frs.get("response_time_sec", 0.0)
        sub_scores = frs.get("sub_scores", {})
        # ar_ratio: activity_increase_percent를 비율로 변환
        ar_ratio   = round(frs.get("activity_increase_percent", 0.0) / 100.0 + 1.0, 3)
        # sf_ratio: surface_score를 0~1로 정규화
        sf_ratio   = round(sub_scores.get("surface_score", 0) / 100.0, 3)

        # 구간별 활동량
        activity_before = self._mean_speed(metrics_before or [])
        activity_during = self._mean_speed(metrics_during or [])
        activity_after  = self._mean_speed(metrics_after  or [])

        if self.mock:
            logger.info(
                f"[ServerTx][Mock] send_feeding | "
                f"trigger={trigger} amount={feeding_event.amount_g}g "
                f"stage={growth_stage} frs={frs_score} "
                f"overfeeding={is_overfeeding}"
            )
            return True

        try:
            result = self._senders["send_feeding"](
                trigger          = trigger,
                amount_g         = feeding_event.amount_g or 0.0,
                growth_stage     = growth_stage,
                turbidity_before = turbidity_before,
                turbidity_after  = turbidity_after,
                is_overfeeding   = is_overfeeding,
                rt_seconds       = rt_seconds,
                ar_ratio         = ar_ratio,
                sf_ratio         = sf_ratio,
                frs_score        = frs_score,
                activity_before  = activity_before,
                activity_during  = activity_during,
                activity_after   = activity_after,
            )
            ok = result is not None
            self._stats["feeding"]["ok" if ok else "fail"] += 1
            return ok
        except Exception as e:
            logger.error(f"[ServerTx] send_feeding 오류: {e}")
            self._stats["feeding"]["fail"] += 1
            return False

    # ══════════════════════════════════════════════════════════════════════
    # 성장 기록 전송
    # ══════════════════════════════════════════════════════════════════════

    def send_growth(self, growth_result: dict) -> bool:
        """
        GrowthTracker.calculate_growth() 결과 → send_growth() 전송.

        growth_sender.py 파라미터:
            fish_id, size_index, estimated_length, estimated_weight,
            growth_rate, growth_stage, recommended_feed_g
        """
        estimated_length = growth_result.get("current_size_cm", 0.0)
        growth_stage     = growth_result.get("estimated_stage", "fry").upper()

        # growth_sender.py의 estimate_weight() 함수 사용
        if not self.mock and self._senders:
            estimated_weight = self._senders["estimate_weight"](estimated_length)
        else:
            # Mock 시 직접 계산 (W = 0.01049 × TL^3.14)
            estimated_weight = round(0.01049 * (estimated_length ** 3.14), 4)

        recommended_feed_g = self._calc_feed_g(
            estimated_weight, growth_stage
        )

        if self.mock:
            logger.info(
                f"[ServerTx][Mock] send_growth | "
                f"fish_id={growth_result.get('fish_id')} "
                f"{estimated_length}cm / {estimated_weight}g "
                f"stage={growth_stage} 권장={recommended_feed_g}g"
            )
            return True

        try:
            result = self._senders["send_growth"](
                fish_id            = growth_result.get("fish_id"),
                size_index         = growth_result.get("moving_avg_size", 0.0),
                estimated_length   = estimated_length,
                estimated_weight   = estimated_weight,
                growth_rate        = growth_result.get("growth_per_day", 0.0),
                growth_stage       = growth_stage,
                recommended_feed_g = recommended_feed_g,
            )
            ok = result is not None
            self._stats["growth"]["ok" if ok else "fail"] += 1
            return ok
        except Exception as e:
            logger.error(f"[ServerTx] send_growth 오류: {e}")
            self._stats["growth"]["fail"] += 1
            return False

    # ══════════════════════════════════════════════════════════════════════
    # 활동 패턴 전송
    # ══════════════════════════════════════════════════════════════════════

    def send_pattern_from_analyzer(self) -> bool:
        """
        내부 ActivityPatternAnalyzer 24시간 누적 데이터를 분석 후 전송.
        demo_pipeline.py의 24시간 주기 타이머에서 호출.

        pattern_sender.py의 send_pattern(pattern_dict) 그대로 사용.
        전송 후 analyzer를 자동 초기화해서 다음 주기 준비.
        """
        if self.mock:
            logger.info("[ServerTx][Mock] send_pattern 호출")
            return True

        if not self._pattern_analyzer:
            logger.warning("[ServerTx] pattern_analyzer 없음 — 건너뜀")
            return False

        try:
            pattern = self._pattern_analyzer.analyze()
            if not pattern:
                logger.warning("[ServerTx] 패턴 분석 결과 없음 — 건너뜀")
                return False

            result = self._senders["send_pattern"](pattern)
            ok     = result is not None

            if ok:
                self._pattern_analyzer.reset()   # 다음 24시간 주기 초기화
                self._stats["pattern"]["ok"] += 1
            else:
                self._stats["pattern"]["fail"] += 1

            return ok
        except Exception as e:
            logger.error(f"[ServerTx] send_pattern 오류: {e}")
            self._stats["pattern"]["fail"] += 1
            return False

    def record_activity_for_pattern(self, activity_level: float):
        """
        send_behavior() 호출 시 패턴 분석기에 활동량 자동 기록.
        send_behavior() 내부에서 호출되므로 외부 호출 불필요.
        """
        if self._pattern_analyzer:
            self._pattern_analyzer.record(activity_level)

    # ══════════════════════════════════════════════════════════════════════
    # EventLog 전송 (AI 행동 이상 / 수질 위험 경고)
    # ══════════════════════════════════════════════════════════════════════

    def send_event_log(
        self,
        level:   str,   # "INFO" | "WARNING" | "DANGER"
        message: str,
        throttle_sec: float = 60.0,   # 같은 메시지 재전송 억제 시간(초)
    ) -> bool:
        """
        AI 행동 분석 기반 경고를 서버 EventLog에 기록.
        POST /monitoring/api/event-log/

        [A 방식 역할]
        센서 기반 제어는 서버가 auto_actions으로 처리하므로,
        여기서는 AI 시각 분석으로만 감지 가능한 이상 이벤트만 전송:
            - 수면 집군 (zone_top_ratio > 0.7) → 산소/먹이 요구 가능성
            - 이상 행동 감지 (abr_score > 0.3)
            - 수질 점수 위험 (< 50)

        Args:
            level        : "INFO" | "WARNING" | "DANGER"
            message      : 경고 메시지
            throttle_sec : 동일 메시지 재전송 억제 시간 (기본 60초)
        """
        # 중복 전송 억제 (같은 메시지가 throttle_sec 내에 재전송되면 스킵)
        now = _time.time()
        last_sent = self._event_log_cache.get(message, 0.0)
        if now - last_sent < throttle_sec:
            logger.debug(f"[ServerTx] EventLog 억제 ({throttle_sec}s): {message}")
            return True
        self._event_log_cache[message] = now

        if self.mock:
            logger.info(f"[ServerTx][Mock] send_event_log | [{level}] {message}")
            return True

        try:
            import requests
            from config import BASE_URL, HEADERS, TANK_ID

            payload = {
                "tank_id": TANK_ID,
                "level":   level.upper(),
                "message": message,
            }
            res = requests.post(
                f"{BASE_URL}/api/event-log/",
                json    = payload,
                headers = HEADERS,
                timeout = 5,
            )
            res.raise_for_status()
            ok = True
            logger.info(f"[ServerTx] EventLog 전송 | [{level}] {message}")

        except Exception as e:
            logger.error(f"[ServerTx] send_event_log 오류: {e}")
            ok = False

        self._stats["event_log"]["ok" if ok else "fail"] += 1
        return ok

    # ══════════════════════════════════════════════════════════════════════
    # 통계 조회
    # ══════════════════════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        return {
            k: {**v, "total": v["ok"] + v["fail"]}
            for k, v in self._stats.items()
        }

    def print_stats(self):
        print("\n[ServerTx] 전송 통계")
        print(f"  {'항목':<12} {'성공':>6} {'실패':>6} {'합계':>6}")
        print(f"  {'-'*34}")
        for k, v in self._stats.items():
            total = v["ok"] + v["fail"]
            if total > 0:
                print(f"  {k:<12} {v['ok']:>6} {v['fail']:>6} {total:>6}")

    # ══════════════════════════════════════════════════════════════════════
    # Private 유틸
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _mean_speed(rows: list[dict]) -> float:
        """fish_metrics 행 리스트의 평균 속도 반환."""
        speeds = [r["speed_px_s"] for r in rows
                  if r.get("speed_px_s", 0) > 0]
        return round(statistics.mean(speeds), 2) if speeds else 0.0

    @staticmethod
    def _calc_feed_g(weight_g: float, growth_stage: str) -> float:
        """
        성장 단계별 권장 1회 급이량(g) 계산.
        설계 문서 2.4 급이 기준 반영.
        급이기 캘리브레이션 전까지는 추정값.

        하루 급이 횟수:
            FRY   → 3회 / day (체중의 10%)
            YOUNG → 3회 / day (체중의 3%)
            ADULT → 2회 / day (체중의 1%)
        """
        stage = growth_stage.upper()
        ratio_meals = {
            "FRY":   (0.10, 3),
            "YOUNG": (0.03, 3),
            "ADULT": (0.01, 2),
        }.get(stage, (0.03, 3))
        ratio, meals = ratio_meals
        return round(weight_g * ratio / meals, 4)


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트 (Mock 모드)
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import logging
    logging.basicConfig(level=logging.INFO)

    from scripts.sensor_reader import SensorData

    tx = ServerTx(mock=True)
    tx.register_pi()

    # 센서 전송 테스트
    tx.send_sensor(SensorData(
        timestamp=time.time(),
        temperature_c=22.5, ph=7.2,
        do_mg_l=6.8, turbidity_ntu=12.3,
        valid=True,
    ))

    # 행동 분석 전송 테스트
    dummy_rows = [
        {"fish_id": i, "speed_px_s": 10.0 + i*5, "activity": 12.0,
         "zone": "MID", "size_index": 1.2, "overlap_count": 0,
         "is_representative": True}
        for i in range(1, 4)
    ]
    tx.send_behavior(dummy_rows, frs_score=78)

    # 성장 전송 테스트
    tx.send_growth({
        "fish_id": 1, "current_size_cm": 2.1,
        "growth_per_day": 0.05, "estimated_stage": "fry",
        "moving_avg_size": 1.2,
    })

    # 패턴 전송 테스트
    tx.send_pattern_from_analyzer()

    tx.print_stats()
