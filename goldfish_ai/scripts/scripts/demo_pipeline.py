"""
demo_pipeline.py — Step 4: Demo Pipeline
금붕어 자동 사육 AI 시스템 (v2.0)

버그 수정:
  [버그1] 속도 필터링 (700px/s 이상 / 0 제거)
  [버그2] CONFIG 하드코딩 → config.yaml 로드
  [버그3] 짧은 트랙 ID 필터링
  [버그4] fps_ref 실측 동기화

구조 보완:
  [5] feeding_events.py 연동 — 키보드 f로 급이 이벤트 기록
  [6] config.yaml → 모든 설정값 중앙화
  [7] Baseline 자동 적재 — activity_baseline.csv 있으면 시작 시 로드
  [8] 급이 트리거 — 키보드 f 입력 시 FRS 분석 자동 예약

사용법:
  python demo_pipeline.py                          # 카메라
  python demo_pipeline.py --source video.mp4       # 영상 파일
  python demo_pipeline.py --show                   # 화면 표시
  python demo_pipeline.py --config my_config.yaml  # 설정 파일 지정
  python demo_pipeline.py --mock-sensor            # 센서 없이 테스트

실행 중 키:
  f — 급이 이벤트 기록 (FRS 분석 자동 예약)
  q — 종료
"""

from __future__ import annotations

import argparse
import csv
import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2

try:
    from ultralytics import YOLO
except ImportError:
    raise SystemExit("[ERROR] pip install ultralytics")

try:
    import yaml
except ImportError:
    raise SystemExit("[ERROR] pip install pyyaml")

from scripts.sensor_reader import SensorReader, check_water_quality
from scripts.feeding_events import FeedingEventLogger
from scripts.server_tx import ServerTx
from scripts.behavior_bridge import get_bridge
# from scripts.auto_capture import set_shared_frame  # 파인튜닝 캡처 비활성화


# ─────────────────────────────────────────────────────────────────────────
# [6] config.yaml 로드
# ─────────────────────────────────────────────────────────────────────────
def load_config(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        print(f"[CONFIG] 경고: {path} 없음 → 기본값 사용")
        return _default_config()

    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    cfg = {
        "model": raw["model"]["path"],
        "imgsz": raw["model"]["imgsz"],
        "conf": raw["model"]["conf"],
        "tracker": raw["model"]["tracker"],
        "fps_ref": raw["pipeline"]["fps_ref"],
        "activity_window": raw["pipeline"]["activity_window"],
        "speed_max_px_s": raw["pipeline"].get("speed_max_px_s", 700.0),
        "speed_min_px_s": raw["pipeline"].get("speed_min_px_s", 0.0),
        "min_track_frames": raw["pipeline"].get("min_track_frames", 10),
        "zone_top_ratio": raw["zone"]["top_ratio"],
        "zone_bottom_ratio": raw["zone"]["bottom_ratio"],
        "mqtt_broker": "localhost",
        "mqtt_topic": "goldfish/sensors",
        "output_dir": raw["storage"]["output_dir"],
        "flush_every": raw["storage"]["flush_every"],
        "iou_threshold": raw["analytics"]["detection"]["iou_overlap_threshold"],
        "expected_fish_count": raw["pipeline"].get("expected_fish_count", 3),
        # [7] Baseline 경로
        "baseline_csv": raw.get("storage", {}).get(
            "baseline_csv", "data/activity_baseline.csv"
        ),
        # [8] FRS 분석 구간
        "frs_before_sec": raw.get("analytics", {})
        .get("frs", {})
        .get("before_sec", 60.0),
        "frs_during_sec": raw.get("analytics", {})
        .get("frs", {})
        .get("during_sec", 300.0),
        # 급이 이벤트
        "feeding_events_csv": raw.get("storage", {}).get(
            "feeding_events_csv", "data/feeding_events.csv"
        ),
        "max_daily_meals": raw.get("feeding", {}).get("max_daily_meals", 5),
    }
    print(f"[CONFIG] 로드: {path}")
    return cfg


def _default_config() -> dict:
    return {
        "model": "models/goldfish_finetuned_best.pt",
        "imgsz": 416,
        "conf": 0.4,
        "tracker": "bytetrack.yaml",
        "fps_ref": 14.0,
        "activity_window": 28,
        "speed_max_px_s": 700.0,
        "speed_min_px_s": 0.0,
        "min_track_frames": 10,
        "zone_top_ratio": 0.3,
        "zone_bottom_ratio": 0.7,
        "mqtt_broker": "localhost",
        "mqtt_topic": "goldfish/sensors",
        "output_dir": "data",
        "flush_every": 30,
        "iou_threshold": 0.0,
        "baseline_csv": "data/activity_baseline.csv",
        "frs_before_sec": 60.0,
        "frs_during_sec": 300.0,
        "feeding_events_csv": "data/feeding_events.csv",
        "max_daily_meals": 5,
        "server_enabled": False,
        "server_mock": True,
    }


# ─────────────────────────────────────────────────────────────────────────
# [3] 짧은 트랙 ID 필터
# ─────────────────────────────────────────────────────────────────────────
class TrackFilter:
    """
    ID별 등장 프레임 수 누적 → min_frames 미만 노이즈 제거.
    expected_fish_count 기준 상위 N개 ID를 대표 ID로 추출.
    (논문 코드 EXPECTED_FISH_COUNT 로직 반영)
    """

    def __init__(self, min_frames: int, expected_fish_count: int = 3):
        self.min_frames = min_frames
        self.expected_fish_count = expected_fish_count
        self._count: dict[int, int] = defaultdict(int)
        self._valid: set[int] = set()
        self._repr_ids: set[int] = set()  # 대표 ID
        self._first_seen: dict[int, float] = {}  # fish_id → 첫 등장 timestamp
        self._last_seen: dict[int, float] = {}  # fish_id → 마지막 등장 timestamp

    def update(self, fish_ids: list[int], timestamp: float = 0.0):
        for fid in fish_ids:
            self._count[fid] += 1
            if fid not in self._first_seen:
                self._first_seen[fid] = timestamp
            self._last_seen[fid] = timestamp
            if self._count[fid] >= self.min_frames:
                self._valid.add(fid)

        # 대표 ID가 아직 expected_fish_count 미만일 때만 갱신
        # 한 번 3개 확정되면 이후 교체 없음
        if len(self._repr_ids) < self.expected_fish_count and self._valid:
            sorted_valid = sorted(
                self._valid,
                key=lambda fid: self._count[fid],
                reverse=True,
            )
            self._repr_ids = set(sorted_valid[:self.expected_fish_count])

    def is_valid(self, fid: int) -> bool:
        return fid in self._valid

    def is_representative(self, fid: int) -> bool:
        """대표 ID 여부 (expected_fish_count 상위 N개)."""
        return fid in self._repr_ids

    def tracked_duration_sec(self, fid: int) -> float:
        """fish_id의 실제 추적 지속 시간 (초)."""
        if fid not in self._first_seen or fid not in self._last_seen:
            return 0.0
        return round(self._last_seen[fid] - self._first_seen[fid], 2)

    def stats(self) -> dict:
        return {
            "total_ids": len(self._count),
            "valid_ids": len(self._valid),
            "repr_ids": sorted(self._repr_ids),
            "filtered": len(self._count) - len(self._valid),
        }


# ─────────────────────────────────────────────────────────────────────────
# Feature 추출기
# ─────────────────────────────────────────────────────────────────────────
class FeatureExtractor:
    def __init__(self, cfg: dict):
        self.fps_ref = cfg["fps_ref"]  # [4] config에서 로드
        self.zone_top = cfg["zone_top_ratio"]
        self.zone_bot = cfg["zone_bottom_ratio"]
        self.activity_window = cfg["activity_window"]
        self.iou_thresh = cfg["iou_threshold"]
        self.speed_max = cfg["speed_max_px_s"]  # [1] 속도 필터
        self.speed_min = cfg["speed_min_px_s"]

        self.prev_pos: dict[int, tuple] = {}
        self.speed_buf: dict[int, deque] = {}

    def update_fps(self, measured_fps: float):
        """[4] 실측 FPS로 동기화"""
        self.fps_ref = measured_fps
        self.activity_window = max(10, int(measured_fps * 2))

    def _zone(self, cy: float, frame_h: int) -> str:
        if cy < frame_h * self.zone_top:
            return "TOP"
        elif cy < frame_h * self.zone_bot:
            return "MID"
        return "BOT"

    @staticmethod
    def _iou(a: list, b: list) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        ih = max(0.0, min(ay2, by2) - max(ay1, by1))
        inter = iw * ih
        if inter == 0:
            return 0.0
        union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
        return inter / union if union > 0 else 0.0

    def compute(
        self, fish_id: int, box: list, all_boxes: list, frame_w: int, frame_h: int
    ) -> tuple[dict, bool]:
        x1, y1, x2, y2 = box
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        zone = self._zone(cy, frame_h)

        if fish_id in self.prev_pos:
            px, py = self.prev_pos[fish_id]
            speed = math.sqrt((cx - px) ** 2 + (cy - py) ** 2) * self.fps_ref
        else:
            speed = 0.0
        self.prev_pos[fish_id] = (cx, cy)

        # [1] 속도 유효성
        speed_valid = self.speed_min < speed <= self.speed_max

        if fish_id not in self.speed_buf:
            self.speed_buf[fish_id] = deque(maxlen=self.activity_window)
        if speed_valid:
            self.speed_buf[fish_id].append(speed)
        activity = (
            sum(self.speed_buf[fish_id]) / len(self.speed_buf[fish_id])
            if self.speed_buf[fish_id]
            else 0.0
        )

        frame_area = frame_w * frame_h
        size_index = (
            ((x2 - x1) * (y2 - y1) / frame_area * 100) if frame_area > 0 else 0.0
        )

        other = [b for b in all_boxes if b is not box]
        ious = [self._iou(box, ob) for ob in other]

        return {
            "center_x": round(cx, 2),
            "center_y": round(cy, 2),
            "zone": zone,
            "speed_px_s": round(speed, 3),
            "activity": round(activity, 3),
            "size_index": round(size_index, 4),
            "overlap_iou": round(max(ious) if ious else 0.0, 4),
            "overlap_count": sum(1 for v in ious if v > self.iou_thresh),
        }, speed_valid

    def cleanup_lost(self, active_ids: set):
        for fid in set(self.prev_pos) - active_ids:
            self.prev_pos.pop(fid, None)
            self.speed_buf.pop(fid, None)


# ─────────────────────────────────────────────────────────────────────────
# CSV writer
# ─────────────────────────────────────────────────────────────────────────
FISH_METRICS_COLS = [
    "timestamp",
    "frame_idx",
    "fish_id",
    "center_x",
    "center_y",
    "zone",
    "speed_px_s",
    "activity",
    "size_index",
    "overlap_iou",
    "overlap_count",
    "tracked_duration_sec",
    "is_representative",  # 논문 코드 반영
    "temperature_c",
    "ph",
    "do_mg_l",
    "turbidity_ntu",
    "sensor_valid",
]


class MetricsWriter:
    def __init__(self, path: Path, flush_every: int = 30):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "w", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._f, fieldnames=FISH_METRICS_COLS)
        self._w.writeheader()
        self._buf = []
        self._flush_every = flush_every
        self.total = 0
        self.filtered_speed = 0
        self.filtered_track = 0
        # [8] FRS용 메모리 버퍼 (최근 10분치 행 보관)
        self.recent_rows: deque = deque(maxlen=14 * 600)  # 14fps × 600초

    def write(self, row: dict):
        self._buf.append(row)
        self.recent_rows.append(row)
        self.total += 1
        if len(self._buf) >= self._flush_every:
            self._w.writerows(self._buf)
            self._f.flush()
            self._buf.clear()

    def close(self):
        if self._buf:
            self._w.writerows(self._buf)
        self._f.close()
        print(
            f"  저장: {self.path}  ({self.total}행 / "
            f"속도필터 {self.filtered_speed}건 / "
            f"트랙필터 {self.filtered_track}건 제거)"
        )


# ─────────────────────────────────────────────────────────────────────────
# [7] Baseline 자동 적재
# ─────────────────────────────────────────────────────────────────────────
def try_load_baseline(baseline_csv: str):
    """
    activity_baseline.csv가 존재하면 로드해서 반환.
    없으면 None 반환 (경고만 출력, 오류 아님).
    """
    import pandas as pd
    from scripts.analytics.activity_pattern import (
        MultiDayActivityAnalyzer,
        AnalyzerConfig,
    )

    p = Path(baseline_csv)
    if not p.exists():
        print(f"[Baseline] 파일 없음: {baseline_csv}")
        print(f"[Baseline] → 물고기 투입 후 3일치 데이터 수집 시 자동 생성됩니다.")
        return None

    try:
        config = AnalyzerConfig(baseline_csv=baseline_csv)
        analyzer = MultiDayActivityAnalyzer(config)
        baseline = analyzer.load_baseline_from_csv(baseline_csv)
        if baseline.empty:
            print(f"[Baseline] 파일은 있지만 비어 있음: {baseline_csv}")
            return None
        print(f"[Baseline] ✔ 로드 완료: {len(baseline)}시간대 ({baseline_csv})")
        return baseline
    except Exception as e:
        print(f"[Baseline] 로드 실패: {e}")
        return None


def try_build_and_save_baseline(cfg: dict):
    """
    data/ 디렉토리의 fish_metrics_*.csv가 3일치 이상이면
    Baseline을 자동 생성해서 저장.
    """
    import pandas as pd
    from scripts.analytics.activity_pattern import (
        MultiDayActivityAnalyzer,
        AnalyzerConfig,
    )

    csv_files = sorted(Path(cfg["output_dir"]).glob("fish_metrics_*.csv"))
    if len(csv_files) < 3:
        print(f"[Baseline] CSV {len(csv_files)}개 — 3개 이상 필요, 건너뜀")
        return

    try:
        config = AnalyzerConfig(
            csv_dir=cfg["output_dir"],
            frame_height=cfg["imgsz"],
            zone_top_ratio=cfg["zone_top_ratio"],
            zone_bottom_ratio=cfg["zone_bottom_ratio"],
            baseline_csv=cfg["baseline_csv"],
        )
        analyzer = MultiDayActivityAnalyzer(config)
        raw_df = analyzer.load_data(csv_paths=[str(p) for p in csv_files])
        daily_hourly = analyzer.build_daily_hourly_summary(raw_df)
        baseline = analyzer.build_hourly_baseline(daily_hourly)

        if not baseline.empty:
            analyzer.save_baseline_to_csv(baseline, cfg["baseline_csv"])
            print(f"[Baseline] ✔ 자동 생성 및 저장: {cfg['baseline_csv']}")
    except Exception as e:
        print(f"[Baseline] 자동 생성 실패: {e}")


# ─────────────────────────────────────────────────────────────────────────
# [8] FRS 분석 예약 실행기
# ─────────────────────────────────────────────────────────────────────────
class FRSScheduler:
    """
    급이 이벤트 기록 후 during_sec 경과 시 FRS 분석을 자동 실행.
    별도 Thread로 동작해 파이프라인 FPS에 영향 없음.
    """

    def __init__(self, cfg: dict, writer: MetricsWriter, feeder: FeedingEventLogger):
        self.cfg = cfg
        self.writer = writer
        self.feeder = feeder
        self._queue: list[float] = []  # 분석 예약된 feeding_ts 목록
        self._lock = threading.Lock()

    def schedule(self, feeding_ts: float):
        """급이 이벤트 발생 시 호출 — during_sec 후 분석 예약."""
        with self._lock:
            self._queue.append(feeding_ts)
        delay = self.cfg["frs_during_sec"]
        print(f"[FRS] {delay:.0f}초 후 분석 예약 (feeding_ts={feeding_ts:.1f})")
        t = threading.Timer(delay, self._run_analysis, args=[feeding_ts])
        t.daemon = True
        t.start()

    def _run_analysis(self, feeding_ts: float):
        """FRS 분석 실행 (별도 Thread)."""
        try:
            from scripts.analytics.feeding_response import FeedingResponseAnalyzer

            analyzer = FeedingResponseAnalyzer(
                before_sec=self.cfg["frs_before_sec"],
                during_sec=self.cfg["frs_during_sec"],
                csv_path=str(Path(self.cfg["output_dir"]) / "feeding_response.csv"),
            )
            rows = list(self.writer.recent_rows)
            before_frames, during_frames = analyzer.build_frames_from_pipeline(
                rows, feeding_ts
            )
            last_event = self.feeder.get_last_event()
            sensor_data = {}  # 센서값은 파이프라인에서 주입 불가 → 빈 dict

            result = analyzer.analyze(
                before_frames=before_frames,
                during_frames=during_frames,
                feeding_ts=feeding_ts,
                sensor_data=sensor_data,
            )
            analyzer.save_to_csv()

            print(f"\n[FRS] ━━━ 급이 반응 분석 결과 ━━━")
            print(f"  점수    : {result['score']} / 100  ({result['status']})")
            print(f"  반응시간: {result['response_time_sec']}초")
            print(f"  활동증가: {result['activity_increase_percent']}%")
            print(f"  수면접근: {result['surface_visits']}회")
            print(f"  평가    : {result['comment']}")
            for rec in result["recommendations"]:
                print(f"  → {rec}")
            print(f"[FRS] ━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

        except Exception as e:
            print(f"[FRS] 분석 오류: {e}")
        finally:
            with self._lock:
                if feeding_ts in self._queue:
                    self._queue.remove(feeding_ts)


# ─────────────────────────────────────────────────────────────────────────
# 시각화
# ─────────────────────────────────────────────────────────────────────────
ZONE_COLOR = {"TOP": (0, 165, 255), "MID": (0, 255, 0), "BOT": (255, 100, 0)}


def draw_overlay(
    frame,
    results,
    features: dict,
    valid_ids: set,
    frame_h: int,
    zone_top: float,
    zone_bot: float,
    fps_display: float,
    writer: MetricsWriter,
    last_feeding_ts: Optional[float],
):
    h, w = frame.shape[:2]

    for ratio, label in [(zone_top, "TOP"), (zone_bot, "MID")]:
        y = int(frame_h * ratio)
        cv2.line(frame, (0, y), (w, y), (200, 200, 200), 1)
        cv2.putText(
            frame, label, (4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1
        )
    cv2.putText(
        frame, "BOT", (4, h - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1
    )

    if results[0].boxes is not None:
        ids_t = results[0].boxes.id
        if ids_t is not None:
            for box_t, tid in zip(results[0].boxes.xyxy, ids_t):
                x1, y1, x2, y2 = map(int, box_t.tolist())
                fid = int(tid)
                feat = features.get(fid, {})
                zone = feat.get("zone", "MID")
                color = ZONE_COLOR.get(zone, (200, 200, 200))

                if fid not in valid_ids:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (120, 120, 120), 1)
                    cv2.putText(
                        frame,
                        f"#{fid}(필터중)",
                        (x1, max(y1 - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.33,
                        (120, 120, 120),
                        1,
                    )
                    continue

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    frame,
                    f"#{fid} {zone} spd:{feat.get('speed_px_s',0):.0f} "
                    f"act:{feat.get('activity',0):.0f}",
                    (x1, max(y1 - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    color,
                    1,
                )

    # 상단 HUD
    cv2.putText(
        frame,
        f"FPS:{fps_display:.1f}",
        (w - 90, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 255, 255),
        1,
    )
    cv2.putText(
        frame,
        f"rows:{writer.total}  "
        f"spd_drop:{writer.filtered_speed}  "
        f"trk_drop:{writer.filtered_track}",
        (4, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.33,
        (180, 180, 0),
        1,
    )

    # [8] 급이 후 경과시간 표시
    if last_feeding_ts:
        elapsed = time.time() - last_feeding_ts
        cv2.putText(
            frame,
            f"급이후: {elapsed:.0f}s",
            (4, h - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 200, 255),
            1,
        )
        cv2.putText(
            frame,
            "[f]급이 [q]종료",
            (4, h - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (180, 180, 180),
            1,
        )
    else:
        cv2.putText(
            frame,
            "[f]급이 [q]종료",
            (4, h - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (180, 180, 180),
            1,
        )

    return frame


# ─────────────────────────────────────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────────────────────────────────────
def run(args):
    # [6] config 로드
    cfg = load_config(args.config)

    out_dir = Path(cfg["output_dir"])
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    metrics_path = out_dir / f"fish_metrics_{ts_str}.csv"
    writer = MetricsWriter(metrics_path, flush_every=cfg["flush_every"])

    print(f"\n{'='*60}")
    print(f"  Goldfish AI — Demo Pipeline")
    print(f"{'='*60}")
    print(f"  모델      : {cfg['model']}")
    print(f"  해상도    : {cfg['imgsz']}px")
    print(f"  속도필터  : {cfg['speed_min_px_s']} ~ {cfg['speed_max_px_s']} px/s")
    print(f"  트랙필터  : {cfg['min_track_frames']}프레임 미만 제거")
    print(f"  출력      : {metrics_path}")

    # BehaviorBridge 초기화
    bridge = get_bridge(window_sec=30.0)

    # [7] Baseline 자동 적재
    baseline_df = try_load_baseline(cfg["baseline_csv"])

    model = YOLO(cfg["model"])
    src = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(src, cv2.CAP_V4L2 if isinstance(src, int) else 0)
    if not cap.isOpened():
        raise SystemExit(f"[ERROR] 영상 소스를 열 수 없습니다: {args.source}")

    # [4] 카메라 실측 FPS
    cam_fps = cap.get(cv2.CAP_PROP_FPS)
    if 5 < cam_fps < 60:
        cfg["fps_ref"] = cam_fps
        cfg["activity_window"] = max(10, int(cam_fps * 2))
        print(f"  카메라 FPS: {cam_fps:.1f} → activity_window={cfg['activity_window']}")
    else:
        print(f"  FPS 감지 실패 → config 기본값: {cfg['fps_ref']}fps")

    extractor = FeatureExtractor(cfg)
    track_filter = TrackFilter(
        min_frames=cfg["min_track_frames"],
        expected_fish_count=cfg["expected_fish_count"],
    )

    # [5] 급이 이벤트 로거 & FRS 스케줄러
    feeder = FeedingEventLogger(
        csv_path=cfg["feeding_events_csv"],
        max_daily=cfg["max_daily_meals"],
    )
    frs_sched = FRSScheduler(cfg, writer, feeder)

    # ServerTx 초기화
    tx = ServerTx(mock=cfg.get("server_mock", True))
    if cfg.get("server_enabled", False):
        tx.register_pi()

    # 전송 주기 타이머
    _last_sensor_tx = 0.0  # 10초마다
    _last_behavior_tx = 0.0  # 30초마다
    _last_pattern_tx = 0.0  # 24시간마다
    SENSOR_TX_INTERVAL = 10
    BEHAVIOR_TX_INTERVAL = 30
    PATTERN_TX_INTERVAL = 86400

    # 센서 Reader
    sensor = SensorReader(
        broker=getattr(args, "broker", None) or cfg["mqtt_broker"],
        topic=getattr(args, "topic", None) or cfg["mqtt_topic"],
        mock=args.mock_sensor,
    )
    sensor.start()

    print(f"\n  {'프레임':>7}  {'감지':>4}  {'유효':>4}  {'FPS':>6}  상태")
    print(f"  {'-'*50}")
    print(f"  [f] 급이 이벤트 기록  [q] 종료\n")

    frame_idx = 0
    fps_display = 0.0
    fps_times = deque(maxlen=30)
    last_feeding_ts: Optional[float] = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                if isinstance(src, str):
                    break
                continue
            if args.max_frames and frame_idx >= args.max_frames:
                break

            # set_shared_frame(frame)  # 파인튜닝 캡처 비활성화

            t0 = time.perf_counter()
            frame_resized = cv2.resize(frame, (cfg["imgsz"], cfg["imgsz"]))
            frame_h, frame_w = frame_resized.shape[:2]

            sensor_data = sensor.get_latest()
            water_alerts = check_water_quality(sensor_data)
            for a in water_alerts:
                print(f"  [수질 {a['level'].upper()}] {a['param']}={a['value']:.2f}")

            results = model.track(
                frame_resized,
                persist=True,
                verbose=False,
                conf=cfg["conf"],
                tracker=cfg["tracker"],
                iou=0.45,
            )

            ts_now = time.time()
            features = {}
            all_boxes = []
            valid_ids = set()

            if results[0].boxes is not None and results[0].boxes.id is not None:
                boxes = results[0].boxes
                raw = boxes.xyxy.tolist()
                ids = boxes.id.tolist()
                confs = boxes.conf.tolist()  # ← conf 추가

                # ── 2단계: conf 상위 3개만 남기기 ──────────────────────
                if len(raw) > cfg["expected_fish_count"]:
                    sorted_idx = sorted(
                        range(len(confs)), key=lambda i: confs[i], reverse=True
                    )
                    sorted_idx = sorted_idx[: cfg["expected_fish_count"]]
                    raw = [raw[i] for i in sorted_idx]
                    ids = [ids[i] for i in sorted_idx]
                    confs = [confs[i] for i in sorted_idx]
                # ────────────────────────────────────────────────────────
                all_boxes = raw

                track_filter.update([int(tid) for tid in ids], timestamp=ts_now)

                for box_coords, tid in zip(raw, ids):
                    fid = int(tid)
                    feat, speed_valid = extractor.compute(
                        fid, box_coords, all_boxes, frame_w, frame_h
                    )
                    features[fid] = feat

                    if not track_filter.is_valid(fid):
                        writer.filtered_track += 1
                        continue
                    valid_ids.add(fid)

                    if not speed_valid:
                        writer.filtered_speed += 1
                        continue

                    writer.write(
                        {
                            "timestamp": round(ts_now, 4),
                            "frame_idx": frame_idx,
                            "fish_id": fid,
                            **feat,
                            "tracked_duration_sec": track_filter.tracked_duration_sec(
                                fid
                            ),
                            "is_representative": track_filter.is_representative(fid),
                            "temperature_c": round(sensor_data.temperature_c, 2),
                            "ph": round(sensor_data.ph, 2),
                            "do_mg_l": round(sensor_data.do_mg_l, 2),
                            "turbidity_ntu": round(sensor_data.turbidity_ntu, 1),
                            "sensor_valid": sensor_data.valid,
                        }
                    )

                extractor.cleanup_lost(set(features.keys()))

            # FPS
            t1 = time.perf_counter()
            fps_times.append(t1 - t0)
            if len(fps_times) >= 5:
                fps_display = len(fps_times) / sum(fps_times)

            # [4] 100프레임마다 실측 FPS 동기화
            if frame_idx > 0 and frame_idx % 100 == 0 and fps_display > 5:
                extractor.update_fps(fps_display)

            # ── 서버 전송 주기 체크 ──────────────────────────────────────
            if cfg.get("server_enabled", False):
                # 10초마다 센서 전송
                if ts_now - _last_sensor_tx >= SENSOR_TX_INTERVAL:
                    tx.send_sensor(sensor_data)
                    _last_sensor_tx = ts_now

                # 30초마다 행동 분석 전송 + bridge 업데이트
                if ts_now - _last_behavior_tx >= BEHAVIOR_TX_INTERVAL:
                    recent = list(writer.recent_rows)
                    # BehaviorBridge 업데이트 (pi_client/main.py가 참조)
                    bridge.update(
                        metrics_rows=recent,
                        abr_rate=0.0,  # ABR Baseline 생성 후 연결
                        frs_score=0,
                    )
                    tx.send_behavior(
                        metrics_rows=recent,
                        abr_result=None,  # ABR Baseline 생성 후 연결
                        frs_score=0,
                        track_filter=track_filter,
                    )
                    _last_behavior_tx = ts_now

                # 24시간마다 활동 패턴 전송
                if ts_now - _last_pattern_tx >= PATTERN_TX_INTERVAL:
                    tx.send_pattern_from_analyzer()
                    _last_pattern_tx = ts_now

            # 진행 로그
            if frame_idx % 30 == 0:
                print(
                    f"  {frame_idx:>7}  {len(features):>4}마리  "
                    f"{len(valid_ids):>4}유효  "
                    f"{fps_display:>5.1f}fps  rows={writer.total}"
                )

            # 화면 표시 + 키입력
            if args.show:
                vis = draw_overlay(
                    frame_resized.copy(),
                    results,
                    features,
                    valid_ids,
                    frame_h,
                    cfg["zone_top_ratio"],
                    cfg["zone_bottom_ratio"],
                    fps_display,
                    writer,
                    last_feeding_ts,
                )
                cv2.imshow("Goldfish AI", vis)
                key = cv2.waitKey(1) & 0xFF

                # [8] f키 → 급이 이벤트 기록 + FRS 예약
                if key == ord("f"):
                    event = feeder.log(trigger="manual")
                    last_feeding_ts = event.timestamp
                    frs_sched.schedule(event.timestamp)

                elif key == ord("q"):
                    break

            frame_idx += 1

    except KeyboardInterrupt:
        print("\n  중단됨 (Ctrl+C)")

    finally:
        cap.release()
        sensor.stop()
        if args.show:
            cv2.destroyAllWindows()
        writer.close()

        tf = track_filter.stats()
        print(
            f"  트랙 통계: 전체 {tf['total_ids']}ID / "
            f"유효 {tf['valid_ids']} / 노이즈 {tf['filtered']} 제거"
        )
        print(f"  대표 ID ({cfg['expected_fish_count']}마리): {tf['repr_ids']}")
        for fid in tf["repr_ids"]:
            dur = track_filter.tracked_duration_sec(fid)
            cnt = track_filter._count[fid]
            print(f"    #{fid}: {cnt}프레임, {dur:.1f}초 추적")

        # [7] 종료 시 Baseline 자동 생성 시도
        print("\n[Baseline] 자동 생성 시도...")
        try_build_and_save_baseline(cfg)

        print(f"  완료: {frame_idx}프레임 / 출력: {metrics_path}")


# ─────────────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Goldfish AI Demo Pipeline")
    parser.add_argument("--source", default="0")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--broker", default=None)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--mock-sensor", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
