"""
feeding_events.py — 급이 이벤트 기록 모듈
금붕어 자동 사육 AI 시스템 (v2.0)

역할:
    - 급이 발생 시각을 CSV에 기록
    - ScheduledFeedingWatcher: config.yaml feeding.times 기반 자동 감지
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
    from feeding_events import FeedingEventLogger, ScheduledFeedingWatcher
    feeder  = FeedingEventLogger()
    watcher = ScheduledFeedingWatcher(cfg["feeding"], feeder)

    # 메인 루프 안에서 매 프레임 호출
    event = watcher.tick()   # 급이 시각 도달 시 FeedingEvent 반환, 아니면 None
    if event:
        last_feeding_ts = event.timestamp
"""

from __future__ import annotations

import csv
import time
import threading
import re
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
        """기존 CSV에서 마지막 event_id와 당일 급이 횟수를 복원."""
        if not self.csv_path.exists():
            return 1

        last_id = 0
        today_count = 0
        today = date.today()

        with open(self.csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    event_id = int(row["event_id"])
                    last_id = max(last_id, event_id)

                    amount_raw = row.get("amount_g", "")
                    event = FeedingEvent(
                        event_id=event_id,
                        timestamp=float(row["timestamp"]),
                        datetime_str=row["datetime_str"],
                        trigger=row.get("trigger", "scheduled"),
                        meal_no=int(row.get("meal_no", 0) or 0),
                        amount_g=float(amount_raw) if amount_raw else None,
                        note=row.get("note", ""),
                    )
                    self._events.append(event)

                    dt = datetime.strptime(row["datetime_str"], "%Y-%m-%d %H:%M:%S")
                    if dt.date() == today:
                        today_count += 1
                except (ValueError, KeyError, TypeError):
                    pass

        self._today_count = today_count
        return last_id + 1



# ─────────────────────────────────────────────────────────────────────────
# 예약 급이 감시자
# ─────────────────────────────────────────────────────────────────────────
class ScheduledFeedingWatcher:
    """
    config.yaml feeding.times 기반으로 급이 시각을 자동 감지.

    메인 루프에서 tick()을 매 프레임 호출하면,
    현재 시각이 feeding_times ± tolerance_sec 범위에 진입할 때
    FeedingEventLogger.log()를 자동 호출하고 FeedingEvent를 반환.

    중복 방지:
        같은 시각 슬롯은 당일 1회만 발동.
        _fired_today: set에 "HH:MM" 문자열로 기록.
    """

    def __init__(
        self,
        feeding_cfg: dict,
        logger: FeedingEventLogger,
    ):
        """
        Args:
            feeding_cfg: config.yaml feeding 섹션 dict
                {
                  "times": ["08:00", "18:00"],
                  "tolerance_sec": 30,
                  ...
                }
            logger: FeedingEventLogger 인스턴스
        """
        self._times: list[str] = [str(v) for v in feeding_cfg.get("times", ["08:00", "18:00"])]
        self._tolerance: int = max(0, int(feeding_cfg.get("tolerance_sec", 30)))
        self._allow_early_trigger = bool(feeding_cfg.get("allow_early_trigger", False))
        self._logger = logger
        self._fired_today: set[str] = set()   # "HH:MM" → 당일 발동 여부
        self._last_reset_date  = date.today()

        # 재시작 직후 같은 급이 슬롯이 tolerance 범위에 있으면 중복 기록될 수 있으므로
        # 오늘 이미 기록된 scheduled 이벤트의 HH:MM 슬롯을 복원한다.
        today = date.today()
        for event in logger.load_all_from_csv():
            try:
                event_dt = datetime.fromtimestamp(event.timestamp)
                if event_dt.date() != today or event.trigger != "scheduled":
                    continue

                # tolerance 이전에 기록된 구버전 이벤트도 정확한 예약 슬롯으로 복원한다.
                match = re.search(r"예약 급이\s+(\d{2}:\d{2})", event.note or "")
                slot = match.group(1) if match else event_dt.strftime("%H:%M")
                if slot in self._times:
                    self._fired_today.add(slot)
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────────
    def tick(self) -> Optional[FeedingEvent]:
        """
        매 프레임 호출. 급이 시각 도달 시 이벤트 기록 후 반환, 아니면 None.

        Returns:
            FeedingEvent or None
        """
        now = datetime.now()
        today = now.date()

        # 자정 넘어가면 발동 기록 초기화
        if today != self._last_reset_date:
            self._fired_today.clear()
            self._last_reset_date = today

        for slot in self._times:
            if slot in self._fired_today:
                continue

            # 슬롯 시각 파싱
            try:
                slot_h, slot_m = map(int, slot.split(":"))
            except ValueError:
                continue

            slot_dt = now.replace(
                hour=slot_h, minute=slot_m, second=0, microsecond=0
            )
            diff_sec = (now - slot_dt).total_seconds()

            # 기본은 예약 시각 이후 tolerance 안에서만 발동한다.
            # 조기 발동을 허용하면 실제 급이 전 데이터가 post 구간에 섞일 수 있다.
            in_window = (
                abs(diff_sec) <= self._tolerance
                if self._allow_early_trigger
                else 0.0 <= diff_sec <= self._tolerance
            )
            if in_window:
                self._fired_today.add(slot)
                event = self._logger.log(
                    trigger="scheduled",
                    timestamp=slot_dt.timestamp(),
                    note=f"예약 급이 {slot} (감지 오차 {diff_sec:+.1f}초)",
                )
                return event

        return None

    def reset_for_test(self):
        """단위 테스트용 — 발동 기록 초기화."""
        self._fired_today.clear()


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

    # ScheduledFeedingWatcher 테스트
    print("\n--- ScheduledFeedingWatcher 테스트 ---")
    now_str = datetime.now().strftime("%H:%M")
    watcher = ScheduledFeedingWatcher(
        feeding_cfg={"times": [now_str], "tolerance_sec": 60},
        logger=logger,
    )
    result = watcher.tick()
    if result:
        print(f"자동 감지 성공: #{result.event_id} {result.datetime_str}")
    else:
        print("현재 시각이 급이 슬롯 범위 밖 (정상)")

