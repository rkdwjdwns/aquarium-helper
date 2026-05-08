"""
feeding_events.py — 급이 이벤트 기록 모듈
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    - 급이 발생 시각을 CSV에 기록
    - demo_pipeline.py에서 키입력(f) 또는 외부 트리거로 이벤트 등록
    - analytics/feeding_response.py, analytics/abr.py가 이 CSV를 참조해
      급이 전후 구간 분할 및 ABR Baseline 제외 구간 계산에 사용

CSV 컬럼:
    event_id      : 자동 증가 정수
    timestamp     : 이벤트 시각 (Unix float, time.time())
    datetime_str  : 사람이 읽기 쉬운 시각 문자열
    trigger       : 이벤트 발생 원인 ("manual" / "scheduled" / "auto")
    meal_no       : 당일 몇 번째 급이 (1, 2, 3...)
    amount_g      : 급이량(g) — 미확정 시 None
    note          : 자유 메모

사용 예 (demo_pipeline.py 내부):
    from feeding_events import FeedingEventLogger
    feeder = FeedingEventLogger()
    feeder.log(trigger="manual", note="키보드 f 입력")
    ts = feeder.get_last_timestamp()   # FRS 분석에 넘길 timestamp
"""

from __future__ import annotations

import csv
import time
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────
# 데이터 구조
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class FeedingEvent:
    event_id:    int
    timestamp:   float
    datetime_str: str
    trigger:     str             # "manual" / "scheduled" / "auto"
    meal_no:     int             # 당일 몇 번째 급이
    amount_g:    Optional[float] # 급이량(g) — 미확정 시 None
    note:        str = ""


# ─────────────────────────────────────────────────────────────────────────
# 급이 이벤트 로거
# ─────────────────────────────────────────────────────────────────────────
class FeedingEventLogger:
    """
    급이 이벤트를 CSV에 기록하고 최근 이벤트를 메모리에 보관.

    Thread-safe: demo_pipeline.py 메인 루프와 키입력 스레드가
    동시에 접근해도 안전하도록 Lock 사용.
    """

    CSV_FIELDS = [
        "event_id", "timestamp", "datetime_str",
        "trigger", "meal_no", "amount_g", "note",
    ]

    def __init__(
        self,
        csv_path:  str = "data/feeding_events.csv",
        max_daily: int = 5,   # 하루 최대 급이 횟수 (초과 시 경고)
    ):
        self.csv_path  = Path(csv_path)
        self.max_daily = max_daily
        self._lock     = threading.Lock()
        self._events:  list[FeedingEvent] = []
        self._today_count: int = 0
        self._today_date:  date = date.today()

        # 기존 CSV 로드 (재시작 시 event_id 이어받기)
        self._next_id = self._load_existing()
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

    # ══════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════

    def log(
        self,
        trigger:   str            = "manual",
        amount_g:  Optional[float] = None,
        note:      str            = "",
        timestamp: Optional[float] = None,
    ) -> FeedingEvent:
        """
        급이 이벤트 기록.

        Args:
            trigger:   "manual"    — 키보드 입력
                       "scheduled" — 예약 급이
                       "auto"      — 행동 기반 자동 급이
            amount_g:  급이량(g). 급이기 캘리브레이션 전까지는 None.
            note:      자유 메모
            timestamp: 지정하지 않으면 현재 시각 사용

        Returns:
            기록된 FeedingEvent
        """
        with self._lock:
            ts  = timestamp or time.time()
            now = datetime.fromtimestamp(ts)

            # 날짜 바뀌면 당일 카운터 리셋
            today = now.date()
            if today != self._today_date:
                self._today_date  = today
                self._today_count = 0

            self._today_count += 1

            if self._today_count > self.max_daily:
                print(f"[FeedingEvent] ⚠️  당일 급이 {self._today_count}회 "
                      f"(최대 {self.max_daily}회 초과) — 기록은 계속합니다.")

            event = FeedingEvent(
                event_id     = self._next_id,
                timestamp    = round(ts, 4),
                datetime_str = now.strftime("%Y-%m-%d %H:%M:%S"),
                trigger      = trigger,
                meal_no      = self._today_count,
                amount_g     = amount_g,
                note         = note,
            )
            self._next_id += 1
            self._events.append(event)
            self._append_csv(event)

            print(f"[FeedingEvent] 급이 #{event.event_id} 기록 "
                  f"({event.datetime_str}, {trigger}, 당일 {event.meal_no}회차)")
            return event

    def get_last_timestamp(self) -> Optional[float]:
        """가장 최근 급이 이벤트 timestamp 반환. 없으면 None."""
        with self._lock:
            return self._events[-1].timestamp if self._events else None

    def get_last_event(self) -> Optional[FeedingEvent]:
        """가장 최근 FeedingEvent 반환. 없으면 None."""
        with self._lock:
            return self._events[-1] if self._events else None

    def get_events_in_range(
        self, start_ts: float, end_ts: float
    ) -> list[FeedingEvent]:
        """주어진 시간 범위 내 이벤트 리스트 반환."""
        with self._lock:
            return [e for e in self._events
                    if start_ts <= e.timestamp <= end_ts]

    def get_today_count(self) -> int:
        """당일 급이 횟수 반환."""
        with self._lock:
            today = date.today()
            if today != self._today_date:
                return 0
            return self._today_count

    def load_all_from_csv(self) -> list[FeedingEvent]:
        """CSV 전체를 읽어 FeedingEvent 리스트로 반환 (분석 모듈용)."""
        if not self.csv_path.exists():
            return []
        events = []
        with open(self.csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                events.append(FeedingEvent(
                    event_id     = int(row["event_id"]),
                    timestamp    = float(row["timestamp"]),
                    datetime_str = row["datetime_str"],
                    trigger      = row["trigger"],
                    meal_no      = int(row["meal_no"]),
                    amount_g     = float(row["amount_g"]) if row["amount_g"] else None,
                    note         = row.get("note", ""),
                ))
        return events

    # ══════════════════════════════════════════════════════════════════════
    # Private
    # ══════════════════════════════════════════════════════════════════════

    def _append_csv(self, event: FeedingEvent):
        """이벤트 1건을 CSV에 append. 파일 없으면 헤더 포함 생성."""
        write_header = not self.csv_path.exists()
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            if write_header:
                writer.writeheader()
            row = asdict(event)
            row["amount_g"] = event.amount_g if event.amount_g is not None else ""
            writer.writerow(row)

    def _load_existing(self) -> int:
        """기존 CSV에서 마지막 event_id를 읽어 다음 ID 반환."""
        if not self.csv_path.exists():
            return 1
        last_id = 0
        with open(self.csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    last_id = max(last_id, int(row["event_id"]))
                except (ValueError, KeyError):
                    pass
        return last_id + 1


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger = FeedingEventLogger(csv_path="data/feeding_events_test.csv")

    # 수동 급이 테스트
    e1 = logger.log(trigger="manual", note="테스트 급이 1")
    e2 = logger.log(trigger="scheduled", amount_g=0.15, note="예약 급이")
    e3 = logger.log(trigger="manual", note="테스트 급이 3")

    print(f"\n마지막 timestamp : {logger.get_last_timestamp()}")
    print(f"당일 급이 횟수   : {logger.get_today_count()}")
    print(f"\nCSV 재로드 확인:")
    for e in logger.load_all_from_csv():
        print(f"  #{e.event_id} {e.datetime_str} [{e.trigger}] "
              f"meal_no={e.meal_no} amount={e.amount_g}g")
