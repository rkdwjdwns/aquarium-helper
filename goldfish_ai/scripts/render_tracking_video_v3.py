"""
render_tracking_video_v3.py
Goldfish AI 발표용 트래킹 오버레이 영상 생성 스크립트

v3 변경점:
- ByteTrack raw ID를 화면에 직접 표시하지 않음
- 위치 기반 재연결 로직으로 발표용 안정 표시 ID(Fish #1~#3) 표시
- 좌상단 HUD는 frame / fps / tracked만 표시

표시 내용:
- YOLO bbox
- 발표용 안정 표시 ID: Fish #1, Fish #2
- TOP / MID / BOT zone 라인
- 개체별 speed_px_s
- 개체별 activity
- frame / fps / tracked

실행 예:
  python scripts/render_tracking_video_v3.py ^
    --source "demo_videos/realtracktest.mp4" ^
    --output "demo_videos/realtracktest_overlay_v3.mp4" ^
    --config "config.yaml" ^
    --show
"""

from __future__ import annotations

import argparse
import math
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

import cv2
import yaml
from ultralytics import YOLO


ZONE_COLOR = {
    "TOP": (0, 165, 255),
    "MID": (0, 255, 0),
    "BOT": (255, 120, 0),
}


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return {
        "model_path": raw.get("model", {}).get("path", "models/goldfish_finetuned_best.pt"),
        "imgsz": int(raw.get("model", {}).get("imgsz", 416)),
        "conf": float(raw.get("model", {}).get("conf", 0.4)),
        "iou": float(raw.get("model", {}).get("iou", 0.45)),
        "tracker": raw.get("model", {}).get("tracker", "bytetrack.yaml"),
        "fps_ref": float(raw.get("pipeline", {}).get("fps_ref", 14.0)),
        "activity_window": int(raw.get("pipeline", {}).get("activity_window", 28)),
        "speed_min_px_s": float(raw.get("pipeline", {}).get("speed_min_px_s", 0.0)),
        "speed_max_px_s": float(raw.get("pipeline", {}).get("speed_max_px_s", 700.0)),
        "expected_fish_count": int(raw.get("pipeline", {}).get("expected_fish_count", 2)),
        "zone_top_ratio": float(raw.get("zone", {}).get("top_ratio", 0.3)),
        "zone_bottom_ratio": float(raw.get("zone", {}).get("bottom_ratio", 0.7)),
    }


def zone_of(cy: float, h: int, top_ratio: float, bottom_ratio: float) -> str:
    if cy < h * top_ratio:
        return "TOP"
    if cy < h * bottom_ratio:
        return "MID"
    return "BOT"


def draw_zones(frame, top_ratio: float, bottom_ratio: float) -> None:
    h, w = frame.shape[:2]
    y_top = int(h * top_ratio)
    y_bottom = int(h * bottom_ratio)

    overlay = frame.copy()

    cv2.rectangle(overlay, (0, 0), (w, y_top), (0, 165, 255), -1)
    cv2.rectangle(overlay, (0, y_top), (w, y_bottom), (0, 255, 0), -1)
    cv2.rectangle(overlay, (0, y_bottom), (w, h), (255, 120, 0), -1)
    cv2.addWeighted(overlay, 0.08, frame, 0.92, 0, frame)

    cv2.line(frame, (0, y_top), (w, y_top), (0, 165, 255), 2)
    cv2.line(frame, (0, y_bottom), (w, y_bottom), (255, 120, 0), 2)

    cv2.putText(frame, "TOP", (12, max(24, y_top // 2)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
    cv2.putText(frame, "MID", (12, y_top + max(28, (y_bottom - y_top) // 2)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 0), 2)
    cv2.putText(frame, "BOT", (12, y_bottom + max(28, (h - y_bottom) // 2)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 120, 0), 2)


def put_hud(frame, frame_idx: int, fps_display: float, tracked_count: int) -> None:
    lines = [
        f"frame: {frame_idx}",
        f"fps: {fps_display:.1f}",
        f"tracked: {tracked_count}",
    ]

    x, y = 14, 28
    box_w, box_h = 210, 88
    cv2.rectangle(frame, (x - 8, y - 24), (x + box_w, y - 24 + box_h), (0, 0, 0), -1)

    for i, line in enumerate(lines):
        cv2.putText(frame, line, (x, y + i * 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)


class StableFishIDMapper:
    """
    ByteTrack raw ID를 발표용 Fish #1~#N으로 안정화해서 표시하는 매퍼.

    원리:
      1. raw_id가 계속 유지되면 같은 Fish 번호 유지
      2. raw_id가 끊겼다가 새 raw_id로 다시 나타나면,
         이전 Fish 위치와 가까운 새 box를 같은 Fish 번호로 재연결
      3. 처음 보는 개체는 비어 있는 Fish 번호에 할당

    주의:
      이 표시 ID는 발표용 안정 라벨이다.
      금붕어 생체 고유 식별 ID가 아니며, 완전한 re-identification은 아니다.
    """

    def __init__(
        self,
        max_fish: int = 3,
        max_lost_frames: int = 45,
        max_match_distance: float = 180.0,
    ):
        self.max_fish = max(1, int(max_fish))
        self.max_lost_frames = max(1, int(max_lost_frames))
        self.max_match_distance = float(max_match_distance)

        self.raw_to_display: dict[int, int] = {}
        self.slots: dict[int, dict] = {
            display_id: {
                "center": None,
                "last_seen": -10**9,
                "raw_id": None,
            }
            for display_id in range(1, self.max_fish + 1)
        }

    @staticmethod
    def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def assign(self, detections: list[dict], frame_idx: int) -> dict[int, int]:
        """
        Args:
            detections:
                [
                  {"raw_id": int, "center": (cx, cy), ...},
                  ...
                ]
            frame_idx: 현재 프레임 번호

        Returns:
            {raw_id: display_id}
        """
        assignments: dict[int, int] = {}
        used_display_ids: set[int] = set()

        # 1단계: 기존 raw_id 매핑 유지
        for det in detections:
            raw_id = int(det["raw_id"])
            display_id = self.raw_to_display.get(raw_id)

            if display_id is None:
                continue

            if display_id in used_display_ids:
                continue

            assignments[raw_id] = display_id
            used_display_ids.add(display_id)

        # 2단계: 새 raw_id를 기존 lost slot 또는 빈 slot에 매칭
        for det in detections:
            raw_id = int(det["raw_id"])
            center = det["center"]

            if raw_id in assignments:
                continue

            display_id = self._find_best_display_slot(
                center=center,
                frame_idx=frame_idx,
                used_display_ids=used_display_ids,
            )

            if display_id is None:
                continue

            assignments[raw_id] = display_id
            used_display_ids.add(display_id)

        # 3단계: slot 상태 갱신 + 충돌 raw mapping 정리
        for raw_id, display_id in assignments.items():
            center = next(d["center"] for d in detections if int(d["raw_id"]) == raw_id)

            old_raw = self.slots[display_id].get("raw_id")
            if old_raw is not None and old_raw != raw_id:
                self.raw_to_display.pop(int(old_raw), None)

            # 같은 display_id를 가리키던 다른 raw_id 제거
            for r, d in list(self.raw_to_display.items()):
                if d == display_id and r != raw_id:
                    self.raw_to_display.pop(r, None)

            self.raw_to_display[raw_id] = display_id
            self.slots[display_id]["center"] = center
            self.slots[display_id]["last_seen"] = frame_idx
            self.slots[display_id]["raw_id"] = raw_id

        return assignments

    def _find_best_display_slot(
        self,
        center: tuple[float, float],
        frame_idx: int,
        used_display_ids: set[int],
    ) -> Optional[int]:
        # A. 최근 lost slot 중 가장 가까운 Fish 번호에 재연결
        best_id = None
        best_dist = float("inf")

        for display_id, slot in self.slots.items():
            if display_id in used_display_ids:
                continue

            last_center = slot.get("center")
            last_seen = int(slot.get("last_seen", -10**9))

            if last_center is None:
                continue

            if frame_idx - last_seen > self.max_lost_frames:
                continue

            dist = self._dist(center, last_center)

            if dist < best_dist:
                best_dist = dist
                best_id = display_id

        if best_id is not None and best_dist <= self.max_match_distance:
            return best_id

        # B. 한 번도 사용하지 않은 Fish 번호 우선 할당
        for display_id, slot in self.slots.items():
            if display_id in used_display_ids:
                continue
            if slot.get("center") is None:
                return display_id

        # C. 오래전에 사라진 slot 재사용
        stale_candidates = [
            (int(slot.get("last_seen", -10**9)), display_id)
            for display_id, slot in self.slots.items()
            if display_id not in used_display_ids
        ]

        if not stale_candidates:
            return None

        stale_candidates.sort()
        return stale_candidates[0][1]


def render_video(args) -> None:
    cfg = load_config(args.config)

    source = Path(args.source)
    if not source.exists():
        raise FileNotFoundError(f"source video not found: {source}")

    model_path = Path(cfg["model_path"])
    if not model_path.exists():
        raise FileNotFoundError(f"model not found: {model_path}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(model_path))

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {source}")

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if not src_fps or src_fps <= 1:
        src_fps = cfg["fps_ref"]

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if args.resize_width and args.resize_width > 0 and width > args.resize_width:
        out_w = int(args.resize_width)
        out_h = int(round(height * out_w / width))
    else:
        out_w, out_h = width, height

    stable_match_distance = (
        float(args.stable_id_max_distance)
        if args.stable_id_max_distance and args.stable_id_max_distance > 0
        else max(120.0, out_w * 0.16)
    )

    display_id_mapper = StableFishIDMapper(
        max_fish=cfg["expected_fish_count"],
        max_lost_frames=args.stable_id_max_lost,
        max_match_distance=stable_match_distance,
    )

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output), fourcc, src_fps, (out_w, out_h))
    if not writer.isOpened():
        raise RuntimeError(f"cannot create output video: {output}")

    prev_pos: dict[int, tuple[float, float]] = {}
    activity_buf: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=cfg["activity_window"]))

    fps_times = deque(maxlen=30)
    fps_display = 0.0
    frame_idx = 0

    print("=" * 70)
    print("Goldfish AI tracking overlay render v3")
    print(f"source              : {source}")
    print(f"output              : {output}")
    print(f"model               : {model_path}")
    print(f"imgsz               : {cfg['imgsz']}")
    print(f"conf                : {cfg['conf']}")
    print(f"tracker             : {cfg['tracker']}")
    print(f"stable max lost     : {args.stable_id_max_lost} frames")
    print(f"stable max distance : {stable_match_distance:.1f} px")
    print("=" * 70)

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if args.max_frames and frame_idx >= args.max_frames:
            break

        t0 = time.perf_counter()

        if (out_w, out_h) != (width, height):
            frame = cv2.resize(frame, (out_w, out_h))

        h, w = frame.shape[:2]
        draw_zones(frame, cfg["zone_top_ratio"], cfg["zone_bottom_ratio"])

        results = model.track(
            frame,
            persist=True,
            verbose=False,
            imgsz=cfg["imgsz"],
            conf=cfg["conf"],
            iou=cfg["iou"],
            tracker=cfg["tracker"],
        )

        detections: list[dict] = []

        if results and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes
            xyxy = boxes.xyxy.cpu().tolist()
            ids = boxes.id.cpu().tolist()
            confs = boxes.conf.cpu().tolist() if boxes.conf is not None else [0.0] * len(xyxy)

            # 발표용: 실제 물고기 수보다 많이 잡히면 confidence 상위 N개만 표시
            if len(xyxy) > cfg["expected_fish_count"]:
                keep_idx = sorted(
                    range(len(confs)),
                    key=lambda i: confs[i],
                    reverse=True,
                )[: cfg["expected_fish_count"]]

                xyxy = [xyxy[i] for i in keep_idx]
                ids = [ids[i] for i in keep_idx]
                confs = [confs[i] for i in keep_idx]

            for box, raw_id, conf in zip(xyxy, ids, confs):
                x1, y1, x2, y2 = map(int, box)
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                detections.append({
                    "raw_id": int(raw_id),
                    "box": (x1, y1, x2, y2),
                    "center": (cx, cy),
                    "conf": float(conf),
                })

        raw_to_display = display_id_mapper.assign(detections, frame_idx)
        active_display_ids: set[int] = set()

        for det in detections:
            raw_id = int(det["raw_id"])
            display_id = raw_to_display.get(raw_id)

            if display_id is None:
                continue

            x1, y1, x2, y2 = det["box"]
            cx, cy = det["center"]
            conf = det["conf"]

            z = zone_of(cy, h, cfg["zone_top_ratio"], cfg["zone_bottom_ratio"])
            color = ZONE_COLOR.get(z, (255, 255, 255))

            if display_id in prev_pos:
                px, py = prev_pos[display_id]
                speed = math.hypot(cx - px, cy - py) * src_fps
            else:
                speed = 0.0

            prev_pos[display_id] = (cx, cy)
            active_display_ids.add(display_id)

            speed_valid = cfg["speed_min_px_s"] < speed <= cfg["speed_max_px_s"]
            if speed_valid:
                activity_buf[display_id].append(speed)

            activity = (
                sum(activity_buf[display_id]) / len(activity_buf[display_id])
                if activity_buf[display_id]
                else 0.0
            )

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)

            label = f"Fish #{display_id} | {z} | spd {speed:.1f}px/s | act {activity:.1f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)
            ly = max(y1 - 8, th + 8)
            cv2.rectangle(frame, (x1, ly - th - 8), (x1 + tw + 8, ly + 4), color, -1)
            cv2.putText(frame, label, (x1 + 4, ly - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)

            cv2.circle(frame, (int(cx), int(cy)), 4, color, -1)

            if args.show_conf:
                cv2.putText(frame, f"{conf:.2f}", (x2 - 48, y2 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

            if args.show_raw_id:
                cv2.putText(frame, f"raw:{raw_id}", (x1, y2 + 16),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        # 오랫동안 안 보이는 표시 ID는 속도 계산용 prev_pos에서 제거
        for display_id in list(prev_pos.keys()):
            if display_id not in active_display_ids:
                slot = display_id_mapper.slots.get(display_id, {})
                last_seen = int(slot.get("last_seen", -10**9))
                if frame_idx - last_seen > args.stable_id_max_lost:
                    prev_pos.pop(display_id, None)

        t1 = time.perf_counter()
        fps_times.append(t1 - t0)

        if len(fps_times) >= 3:
            fps_display = len(fps_times) / sum(fps_times)

        put_hud(frame, frame_idx, fps_display, tracked_count=len(active_display_ids))
        writer.write(frame)

        if args.show:
            cv2.imshow("Goldfish AI Tracking Overlay", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

        if frame_idx % 30 == 0:
            print(f"frame={frame_idx:5d} tracked={len(active_display_ids)} fps={fps_display:.1f}")

        frame_idx += 1

    cap.release()
    writer.release()

    if args.show:
        cv2.destroyAllWindows()

    print("=" * 70)
    print(f"done: {output}")
    print(f"frames: {frame_idx}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render tracking overlay video with stable Fish #1~#3 labels"
    )
    parser.add_argument("--source", required=True, help="input video path")
    parser.add_argument("--output", required=True, help="output mp4 path")
    parser.add_argument("--config", default="config.yaml", help="config.yaml path")
    parser.add_argument("--show", action="store_true", help="show preview window while rendering")
    parser.add_argument("--max-frames", type=int, default=None, help="optional frame limit")
    parser.add_argument("--resize-width", type=int, default=1280, help="resize output width. 0 keeps original size")

    parser.add_argument(
        "--stable-id-max-lost",
        type=int,
        default=45,
        help="frames to keep a missing Fish label before reusing it",
    )
    parser.add_argument(
        "--stable-id-max-distance",
        type=float,
        default=0.0,
        help="max pixel distance for reconnecting a new raw ID to an old Fish label. 0=auto",
    )
    parser.add_argument(
        "--show-raw-id",
        action="store_true",
        help="debug only: show internal ByteTrack raw ID under bbox",
    )
    parser.add_argument(
        "--show-conf",
        action="store_true",
        help="debug only: show YOLO confidence near bbox",
    )

    args = parser.parse_args()
    render_video(args)


if __name__ == "__main__":
    main()
