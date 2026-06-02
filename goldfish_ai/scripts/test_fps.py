# scripts/test_fps.py
"""
Raspberry Pi 5 YOLO FPS 테스트 스크립트

측정 단계:
1. YOLO 단독
2. YOLO + ByteTrack
3. YOLO + ByteTrack + Feature 계산

사용 예:
python scripts/test_fps.py --model yolo11n.pt --source 0
python scripts/test_fps.py --model yolo11n.pt --source demo_videos/test.mp4
"""

import argparse
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        type=str,
        default="yolo11n.pt",
        help="YOLO 모델 경로"
    )

    parser.add_argument(
        "--source",
        type=str,
        default="0",
        help="카메라 번호 또는 영상 파일 경로. 예: 0 또는 demo_videos/test.mp4"
    )

    parser.add_argument(
        "--frames",
        type=int,
        default=300,
        help="측정할 프레임 수"
    )

    parser.add_argument(
        "--conf",
        type=float,
        default=0.4,
        help="confidence threshold"
    )

    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="YOLO 입력 이미지 크기. 예: 640, 416, 320"
    )

    parser.add_argument(
        "--width",
        type=int,
        default=640,
        help="카메라 캡처 width"
    )

    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="카메라 캡처 height"
    )

    return parser.parse_args()


def open_capture(source: str, width: int, height: int):
    if source.isdigit():
        cap = cv2.VideoCapture(int(source))
    else:
        source_path = Path(source)
        if not source_path.exists():
            raise FileNotFoundError(f"영상 파일을 찾을 수 없습니다: {source}")
        cap = cv2.VideoCapture(str(source_path))

    if not cap.isOpened():
        raise RuntimeError(f"영상 소스를 열 수 없습니다: {source}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    return cap


def read_frame_loop(cap, source: str):
    ret, frame = cap.read()

    # 영상 파일이면 끝났을 때 처음으로 되감기
    if not ret and not source.isdigit():
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, frame = cap.read()

    return ret, frame


def get_temperature():
    """
    Raspberry Pi 온도 측정.
    Pi가 아니거나 명령어 실패 시 None 반환.
    """
    try:
        import subprocess
        result = subprocess.check_output(["vcgencmd", "measure_temp"], text=True)
        return result.strip()
    except Exception:
        return None


def measure_yolo_only(model, source, width, height, frames, conf, imgsz):
    cap = open_capture(source, width, height)

    frame_count = 0
    start = time.time()

    while frame_count < frames:
        ret, frame = read_frame_loop(cap, source)
        if not ret:
            break

        _ = model.predict(
            frame,
            conf=conf,
            imgsz=imgsz,
            verbose=False
        )

        frame_count += 1

    elapsed = time.time() - start
    cap.release()

    fps = frame_count / elapsed if elapsed > 0 else 0.0
    return fps, frame_count, elapsed


def measure_yolo_tracking(model, source, width, height, frames, conf, imgsz):
    cap = open_capture(source, width, height)

    frame_count = 0
    start = time.time()

    while frame_count < frames:
        ret, frame = read_frame_loop(cap, source)
        if not ret:
            break

        _ = model.track(
            frame,
            conf=conf,
            imgsz=imgsz,
            tracker="bytetrack.yaml",
            persist=True,
            verbose=False
        )

        frame_count += 1

    elapsed = time.time() - start
    cap.release()

    fps = frame_count / elapsed if elapsed > 0 else 0.0
    return fps, frame_count, elapsed


def classify_zone(center_y: float, frame_height: int) -> str:
    if center_y < frame_height * 0.3:
        return "TOP"
    if center_y < frame_height * 0.7:
        return "MID"
    return "BOT"


def measure_yolo_tracking_feature(model, source, width, height, frames, conf, imgsz):
    cap = open_capture(source, width, height)

    prev_centers = {}
    feature_count = 0

    frame_count = 0
    start = time.time()

    while frame_count < frames:
        ret, frame = read_frame_loop(cap, source)
        if not ret:
            break

        frame_timestamp = time.time()

        results = model.track(
            frame,
            conf=conf,
            imgsz=imgsz,
            tracker="bytetrack.yaml",
            persist=True,
            verbose=False
        )

        frame_h, frame_w = frame.shape[:2]
        frame_area = frame_w * frame_h

        elapsed_so_far = max(frame_timestamp - start, 1e-6)
        current_fps_est = max(frame_count / elapsed_so_far, 1e-6)

        if results and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            ids = results[0].boxes.id.cpu().numpy().astype(int)
            confs = results[0].boxes.conf.cpu().numpy()

            for box, fish_id, det_conf in zip(boxes, ids, confs):
                x1, y1, x2, y2 = box

                bbox_w = x2 - x1
                bbox_h = y2 - y1
                bbox_area = bbox_w * bbox_h

                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2

                speed_px_s = 0.0
                if fish_id in prev_centers:
                    prev_x, prev_y = prev_centers[fish_id]
                    distance_px = np.sqrt((center_x - prev_x) ** 2 + (center_y - prev_y) ** 2)
                    speed_px_s = distance_px * current_fps_est

                prev_centers[fish_id] = (center_x, center_y)

                zone = classify_zone(center_y, frame_h)
                size_index = (bbox_area / frame_area) * 100 if frame_area > 0 else 0.0

                # 실제 저장은 하지 않지만, feature 계산 부하를 반영하기 위해 dict 생성
                _metric = {
                    "timestamp": frame_timestamp,
                    "frame_idx": frame_count,
                    "fish_id": int(fish_id),
                    "center_x": float(center_x),
                    "center_y": float(center_y),
                    "speed_px_s": float(speed_px_s),
                    "activity": float(speed_px_s),
                    "zone": zone,
                    "size_index": float(size_index),
                    "confidence": float(det_conf),
                }

                feature_count += 1

        frame_count += 1

    elapsed = time.time() - start
    cap.release()

    fps = frame_count / elapsed if elapsed > 0 else 0.0
    return fps, frame_count, elapsed, feature_count


def judge_fps(fps: float) -> str:
    if fps >= 15:
        return "사용 가능 / 안정"
    if fps >= 10:
        return "사용 가능 / 수용 가능"
    return "최적화 필요"


def main():
    args = parse_args()

    print("=" * 70)
    print("[Goldfish AI FPS Test]")
    print(f"model  : {args.model}")
    print(f"source : {args.source}")
    print(f"frames : {args.frames}")
    print(f"imgsz  : {args.imgsz}")
    print(f"camera : {args.width}x{args.height}")
    print(f"conf   : {args.conf}")
    print("=" * 70)

    model = YOLO(args.model)

    temp_before = get_temperature()
    if temp_before:
        print(f"[TEMP BEFORE] {temp_before}")

    print("\n[1] YOLO only...")
    fps1, count1, elapsed1 = measure_yolo_only(
        model, args.source, args.width, args.height, args.frames, args.conf, args.imgsz
    )
    print(f"YOLO only FPS: {fps1:.2f} | frames={count1} | elapsed={elapsed1:.2f}s | {judge_fps(fps1)}")

    temp_mid1 = get_temperature()
    if temp_mid1:
        print(f"[TEMP] {temp_mid1}")

    print("\n[2] YOLO + ByteTrack...")
    fps2, count2, elapsed2 = measure_yolo_tracking(
        model, args.source, args.width, args.height, args.frames, args.conf, args.imgsz
    )
    print(f"YOLO + ByteTrack FPS: {fps2:.2f} | frames={count2} | elapsed={elapsed2:.2f}s | {judge_fps(fps2)}")

    temp_mid2 = get_temperature()
    if temp_mid2:
        print(f"[TEMP] {temp_mid2}")

    print("\n[3] YOLO + ByteTrack + Feature...")
    fps3, count3, elapsed3, feature_count = measure_yolo_tracking_feature(
        model, args.source, args.width, args.height, args.frames, args.conf, args.imgsz
    )
    print(
        f"YOLO + ByteTrack + Feature FPS: {fps3:.2f} | "
        f"frames={count3} | features={feature_count} | elapsed={elapsed3:.2f}s | {judge_fps(fps3)}"
    )

    temp_after = get_temperature()
    if temp_after:
        print(f"[TEMP AFTER] {temp_after}")

    print("\n" + "=" * 70)
    print("[RESULT TABLE]")
    print(f"{'구성':35s} | {'FPS':>8s} | 판정")
    print("-" * 70)
    print(f"{'YOLO only':35s} | {fps1:8.2f} | {judge_fps(fps1)}")
    print(f"{'YOLO + ByteTrack':35s} | {fps2:8.2f} | {judge_fps(fps2)}")
    print(f"{'YOLO + ByteTrack + Feature':35s} | {fps3:8.2f} | {judge_fps(fps3)}")
    print("=" * 70)


if __name__ == "__main__":
    main()