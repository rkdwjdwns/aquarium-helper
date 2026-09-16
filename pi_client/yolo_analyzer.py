"""
yolo_analyzer.py
YOLOv11 + ByteTrack 기반 코메트 금붕어 행동 분석

카메라 → 프레임 → YOLOv11 탐지 → ByteTrack 추적 → 행동 지표 계산
"""

import cv2
import numpy as np
from ultralytics import YOLO
from collections import defaultdict, deque

# ── 설정 ──────────────────────────────────────
MODEL_PATH   = "models/goldfish_yolo11.pt"   # 학습된 모델 경로
CAMERA_INDEX = 0                              # Pi 카메라 인덱스
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480
ANALYZE_SEC  = 10    # 분석 구간 (초)
FPS          = 30

# 구역 경계 (상/중/하층 분할)
ZONE_TOP_Y = FRAME_HEIGHT * 0.33   # 상층: 0 ~ 33%
ZONE_BOT_Y = FRAME_HEIGHT * 0.67   # 하층: 67% ~ 100%

# ABR 이상 행동 판정 기준 (표준편차 배수)
ABR_SIGMA = 2.0


class FishAnalyzer:
    def __init__(self, model_path: str = MODEL_PATH):
        print(f"[YOLO] 모델 로드 중: {model_path}")
        self.model = YOLO(model_path)
        self.cap   = cv2.VideoCapture(CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

        # 트랙별 이전 위치 저장 (속도 계산용)
        self.prev_positions: dict[int, tuple] = {}
        # 트랙별 속도 히스토리
        self.speed_history:  dict[int, deque] = defaultdict(lambda: deque(maxlen=30))
        # 전체 프레임 속도 기록 (ABR 계산용)
        self.all_speeds: list[float] = []

    def _get_zone(self, cy: float) -> str:
        """물고기 중심 y좌표로 체류 구역 반환"""
        if cy < ZONE_TOP_Y:
            return "TOP"
        elif cy > ZONE_BOT_Y:
            return "BOT"
        return "MID"

    def _calc_abr(self, speeds: list[float]) -> float:
        """이상 행동율 계산 — |speed - μ| > 2σ 비율"""
        if len(speeds) < 10:
            return 0.0
        arr   = np.array(speeds)
        mu    = arr.mean()
        sigma = arr.std()
        if sigma == 0:
            return 0.0
        return float(np.mean(np.abs(arr - mu) > ABR_SIGMA * sigma))

    def analyze(self) -> dict | None:
        """
        ANALYZE_SEC 동안 카메라 프레임을 분석하고 행동 지표를 반환합니다.

        Returns:
            {
                fish_count, overlap_frames, activity_level, abr_score,
                dominant_zone, zone_top_ratio, zone_mid_ratio, zone_bot_ratio,
                size_index, feeding_score, status, is_anomaly, note
            }
        """
        frame_count    = 0
        overlap_frames = 0
        zone_counts    = {"TOP": 0, "MID": 0, "BOT": 0}
        all_speeds     = []
        all_sizes      = []
        fish_ids_seen  = set()

        total_frames = ANALYZE_SEC * FPS

        while frame_count < total_frames:
            ret, frame = self.cap.read()
            if not ret:
                break

            # YOLOv11 추적 (ByteTrack 내장)
            results = self.model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                verbose=False,
            )

            if results[0].boxes is None:
                frame_count += 1
                continue

            boxes  = results[0].boxes
            tracks = boxes.id.int().tolist() if boxes.id is not None else []
            xywhs  = boxes.xywh.tolist()

            # 겹침 감지 (IoU 기반 간이 체크)
            if len(xywhs) > 1:
                overlap_frames += 1

            for i, (track_id, xywh) in enumerate(zip(tracks, xywhs)):
                cx, cy, w, h = xywh
                fish_ids_seen.add(track_id)

                # 구역 기록
                zone = self._get_zone(cy)
                zone_counts[zone] += 1

                # 크기 지수
                size_idx = (w * h) / (FRAME_WIDTH * FRAME_HEIGHT) * 100
                all_sizes.append(size_idx)

                # 속도 계산
                if track_id in self.prev_positions:
                    px, py = self.prev_positions[track_id]
                    speed  = float(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
                    all_speeds.append(speed)
                    self.speed_history[track_id].append(speed)

                self.prev_positions[track_id] = (cx, cy)

            frame_count += 1

        # ── 지표 계산 ──────────────────────────
        fish_count     = len(fish_ids_seen)
        total_zones    = sum(zone_counts.values()) or 1
        zone_top_ratio = zone_counts["TOP"] / total_zones
        zone_mid_ratio = zone_counts["MID"] / total_zones
        zone_bot_ratio = zone_counts["BOT"] / total_zones
        dominant_zone  = max(zone_counts, key=zone_counts.get)

        activity_level = float(np.mean(all_speeds)) if all_speeds else 0.0
        abr_score      = self._calc_abr(all_speeds)
        size_index     = float(np.mean(all_sizes)) if all_sizes else 0.0

        # ── 상태 판정 ──────────────────────────
        is_anomaly = abr_score > 0.3 or zone_top_ratio > 0.7
        if abr_score < 0.05 and activity_level > 5:
            status = "EXCELLENT"
        elif abr_score < 0.1:
            status = "GOOD"
        elif abr_score < 0.2:
            status = "NORMAL"
        elif abr_score < 0.3:
            status = "WARNING"
        else:
            status = "POOR"

        note = ""
        if zone_top_ratio > 0.7:
            note = "상층 집중 체류 — 산소 부족 또는 먹이 요구 가능성"
        elif zone_bot_ratio > 0.7:
            note = "하층 집중 체류 — 스트레스 또는 수질 이상 가능성"
        elif abr_score > 0.3:
            note = "이상 행동 감지 — 수질 점검 권장"

        return {
            "fish_count":     fish_count,
            "overlap_frames": overlap_frames,
            "activity_level": round(activity_level, 2),
            "abr_score":      round(abr_score, 4),
            "dominant_zone":  dominant_zone,
            "zone_top_ratio": round(zone_top_ratio, 3),
            "zone_mid_ratio": round(zone_mid_ratio, 3),
            "zone_bot_ratio": round(zone_bot_ratio, 3),
            "size_index":     round(size_index, 3),
            "feeding_score":  0,
            "status":         status,
            "is_anomaly":     is_anomaly,
            "note":           note,
        }

    def release(self):
        self.cap.release()


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    analyzer = FishAnalyzer()
    print(f"[YOLO] {ANALYZE_SEC}초 분석 시작...")
    result = analyzer.analyze()
    print(result)
    analyzer.release()
