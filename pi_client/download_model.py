"""
download_model.py
YOLOv11 기본 모델 다운로드 스크립트

Pi에서 처음 실행 시 한 번만 실행하면 됩니다.
학습된 금붕어 모델이 없을 경우 YOLOv11n (nano) 기본 모델로 시작합니다.
"""

import os
from pathlib import Path
from ultralytics import YOLO

MODELS_DIR  = Path("models")
MODEL_PATH  = MODELS_DIR / "goldfish_yolo11.pt"
DEFAULT_PT  = "yolo11n.pt"   # nano — Pi 5에서 실시간 처리 가능


def download_default_model():
    """YOLOv11n 기본 모델 다운로드"""
    MODELS_DIR.mkdir(exist_ok=True)

    if MODEL_PATH.exists():
        print(f"[MODEL] 이미 존재: {MODEL_PATH}")
        return

    print(f"[MODEL] 기본 모델 다운로드 중: {DEFAULT_PT}")
    model = YOLO(DEFAULT_PT)   # 자동 다운로드
    model.save(str(MODEL_PATH))
    print(f"[MODEL] 저장 완료: {MODEL_PATH}")
    print()
    print("⚠️  현재는 기본 모델입니다.")
    print("   금붕어 전용 모델로 교체하려면 학습 후 models/goldfish_yolo11.pt 를 교체하세요.")


if __name__ == "__main__":
    download_default_model()
