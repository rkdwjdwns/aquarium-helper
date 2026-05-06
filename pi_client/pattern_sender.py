"""
pattern_sender.py
시간대별 활동 패턴 분석 및 서버 전송
POST /api/pattern/

분석 주기: 1일 1회 (자정 이후 or 24시간 누적 후)
데이터: FishAnalyzer에서 수집한 시간대별 activity_level 기록
"""

import requests
import statistics
from datetime import datetime, timedelta
from collections import defaultdict
from config import BASE_URL, HEADERS, TANK_ID


class ActivityPatternAnalyzer:
    """
    24시간 동안 수집된 시간대별 활동량을 분석합니다.

    사용법:
        analyzer = ActivityPatternAnalyzer()

        # 행동 분석 결과가 나올 때마다 기록
        analyzer.record(activity_level=14.5)

        # 24시간 후 패턴 분석 및 전송
        analyzer.analyze_and_send()
    """

    def __init__(self):
        self.hourly_data: dict[int, list[float]] = defaultdict(list)
        self.period_start: datetime = datetime.now()

        # Baseline (이전 데이터 기반 — 없으면 None)
        self.baseline_mean: float | None = None
        self.baseline_std:  float | None = None

    def record(self, activity_level: float):
        """현재 시간대에 활동량을 기록합니다."""
        hour = datetime.now().hour
        self.hourly_data[hour].append(activity_level)

    def set_baseline(self, mean: float, std: float):
        """이전 분석 결과를 Baseline으로 설정합니다."""
        self.baseline_mean = mean
        self.baseline_std  = std

    def _calc_anomaly_hours(self, hourly_avg: dict[int, float],
                             mean: float, std: float) -> list[int]:
        """평균 대비 2σ 이상 벗어난 시간대를 반환합니다."""
        anomaly = []
        for hour, avg in hourly_avg.items():
            if std > 0 and abs(avg - mean) > 2.0 * std:
                anomaly.append(hour)
        return sorted(anomaly)

    def analyze(self) -> dict | None:
        """
        수집된 데이터를 분석하고 패턴 지표를 반환합니다.

        Returns:
            {
                period_start, period_end,
                hourly_activity, baseline_mean, baseline_std,
                current_mean, deviation_ratio,
                daytime_activity, nighttime_activity,
                anomaly_hours, has_anomaly
            }
            또는 None (데이터 부족 시)
        """
        if not self.hourly_data:
            print("[PATTERN] 데이터 없음 — 분석 건너뜀")
            return None

        period_end = datetime.now()

        # 시간대별 평균 계산
        hourly_avg: dict[int, float] = {
            h: round(statistics.mean(vals), 2)
            for h, vals in self.hourly_data.items()
        }

        # 전체 활동량 통계
        all_vals = [v for vals in self.hourly_data.values() for v in vals]
        current_mean = round(statistics.mean(all_vals), 2)
        current_std  = round(statistics.stdev(all_vals), 2) if len(all_vals) > 1 else 0.0

        # Baseline 대비 편차
        baseline_mean = self.baseline_mean if self.baseline_mean is not None else current_mean
        baseline_std  = self.baseline_std  if self.baseline_std  is not None else current_std
        deviation_ratio = round(
            abs(current_mean - baseline_mean) / baseline_mean, 3
        ) if baseline_mean > 0 else 0.0

        # 주간(6~22시) / 야간(22~6시) 활동량
        daytime_vals  = [v for h, vals in self.hourly_data.items()
                         for v in vals if 6 <= h < 22]
        nighttime_vals = [v for h, vals in self.hourly_data.items()
                          for v in vals if h >= 22 or h < 6]

        daytime_activity   = round(statistics.mean(daytime_vals),   2) if daytime_vals  else 0.0
        nighttime_activity = round(statistics.mean(nighttime_vals), 2) if nighttime_vals else 0.0

        # 이상 시간대
        anomaly_hours = self._calc_anomaly_hours(hourly_avg, baseline_mean, baseline_std)
        has_anomaly   = len(anomaly_hours) > 0

        return {
            "period_start":       self.period_start.isoformat(),
            "period_end":         period_end.isoformat(),
            "hourly_activity":    hourly_avg,
            "baseline_mean":      baseline_mean,
            "baseline_std":       baseline_std,
            "current_mean":       current_mean,
            "deviation_ratio":    deviation_ratio,
            "daytime_activity":   daytime_activity,
            "nighttime_activity": nighttime_activity,
            "anomaly_hours":      anomaly_hours,
            "has_anomaly":        has_anomaly,
        }

    def reset(self):
        """다음 분석 주기를 위해 초기화합니다."""
        # 현재 결과를 Baseline으로 저장
        result = self.analyze()
        if result:
            self.baseline_mean = result["current_mean"]
            self.baseline_std  = result.get("baseline_std", 0.0)

        self.hourly_data  = defaultdict(list)
        self.period_start = datetime.now()
        print("[PATTERN] 초기화 완료 — 새 분석 주기 시작")


def send_pattern(pattern: dict) -> dict | None:
    """
    활동 패턴 분석 결과를 서버로 전송합니다.

    Args:
        pattern: ActivityPatternAnalyzer.analyze() 반환값
    """
    payload = {
        "tank_id": TANK_ID,
        **pattern,
    }

    try:
        res = requests.post(
            f"{BASE_URL}/api/pattern/",
            json=payload,
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        anomaly_flag = " ⚠️ 이상 감지" if pattern.get("has_anomaly") else ""
        print(f"[PATTERN] 전송 완료 | 평균활동량={pattern.get('current_mean')} | "
              f"편차={pattern.get('deviation_ratio')}{anomaly_flag}")
        return data

    except requests.exceptions.Timeout:
        print("[PATTERN] 오류: 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[PATTERN] 오류: 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[PATTERN] HTTP 오류: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"[PATTERN] 알 수 없는 오류: {e}")

    return None


def analyze_and_send(analyzer: ActivityPatternAnalyzer) -> bool:
    """분석 후 전송하고 초기화합니다."""
    pattern = analyzer.analyze()
    if not pattern:
        return False

    result = send_pattern(pattern)
    if result:
        analyzer.reset()
        return True
    return False


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    import random

    analyzer = ActivityPatternAnalyzer()

    # 더미 데이터로 24시간 시뮬레이션
    print("[TEST] 더미 활동량 데이터 생성 중...")
    for hour in range(24):
        analyzer.hourly_data[hour] = [
            random.uniform(5, 25) if 6 <= hour < 22 else random.uniform(1, 8)
            for _ in range(6)
        ]

    pattern = analyzer.analyze()
    print(f"[TEST] 분석 결과: {pattern}")

    result = send_pattern(pattern)
    print(f"[TEST] 서버 응답: {result}")
