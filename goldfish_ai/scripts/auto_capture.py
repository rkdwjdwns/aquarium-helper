# scripts/auto_capture.py
"""
파인튜닝용 자동 이미지 캡처 스크립트
- run.py(자동 사육)와 동시 실행 가능: 카메라를 직접 열지 않고
  demo_pipeline.py의 최신 프레임을 공유 버퍼에서 읽어 저장
- 공유 버퍼가 없을 경우(단독 실행) 카메라를 직접 열어 촬영

기본 설정: 60분마다 50장씩, 4일간 → 약 4,800장
저장 경로: data/captures/YYYYMMDD_HHMMSS_NNN.jpg

실행 방법:
  python scripts/auto_capture.py              # 기본 (60분, 50장, 4일)
  python scripts/auto_capture.py --once       # 지금 50장만 찍고 종료
  python scripts/auto_capture.py --interval 30 --count 20 --days 2
"""

import cv2
import time
import argparse
import threading
import numpy as np
from pathlib import Path
from datetime import datetime


# ──────────────────────────────────────────────
# 공유 프레임 버퍼 (run.py와 동시 실행 시 사용)
# demo_pipeline.py에서 아래 변수에 프레임을 넣어주면
# auto_capture.py가 카메라를 따로 열지 않고 읽어감.
# ──────────────────────────────────────────────
_shared_lock = threading.Lock()
_shared_frame: np.ndarray | None = None


def set_shared_frame(frame: np.ndarray) -> None:
    """demo_pipeline.py에서 호출: 최신 프레임 등록"""
    global _shared_frame
    with _shared_lock:
        _shared_frame = frame.copy()


def _get_shared_frame() -> np.ndarray | None:
    with _shared_lock:
        return _shared_frame.copy() if _shared_frame is not None else None


# ──────────────────────────────────────────────
# 핵심 함수
# ──────────────────────────────────────────────
def capture_batch_shared(save_dir: Path, count: int) -> int:
    """공유 버퍼에서 count장 저장 (run.py 동시 실행 모드)"""
    saved = 0
    while saved < count:
        frame = _get_shared_frame()
        if frame is None:
            time.sleep(0.2)
            continue
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = save_dir / f"{ts}_{saved:03d}.jpg"
        cv2.imwrite(str(fname), frame)
        saved += 1
        time.sleep(0.5)  # 중복 프레임 방지
    return saved


def capture_batch_camera(cap: cv2.VideoCapture, save_dir: Path, count: int) -> int:
    """카메라 직접 접근으로 count장 저장 (단독 실행 모드)"""
    saved = 0
    attempts = 0
    while saved < count and attempts < count * 3:
        ret, frame = cap.read()
        attempts += 1
        if not ret:
            time.sleep(0.1)
            continue
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = save_dir / f"{ts}_{saved:03d}.jpg"
        cv2.imwrite(str(fname), frame)
        saved += 1
        time.sleep(0.5)
    return saved


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="파인튜닝용 자동 캡처 스크립트")
    parser.add_argument("--interval", type=int, default=60,
                        help="캡처 간격 (분, 기본 60)")
    parser.add_argument("--count",    type=int, default=50,
                        help="회당 캡처 장수 (기본 50)")
    parser.add_argument("--days",     type=float, default=4.0,
                        help="총 실행 기간 (일, 기본 4)")
    parser.add_argument("--once",     action="store_true",
                        help="지금 한 번만 찍고 종료")
    args = parser.parse_args()

    save_dir = Path("data/captures")
    save_dir.mkdir(parents=True, exist_ok=True)

    # 공유 버퍼 유무로 실행 모드 결정
    use_shared = (_get_shared_frame() is not None)

    cap = None
    if not use_shared:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 416)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 416)
        if not cap.isOpened():
            print("[ERROR] 카메라 열기 실패.")
            print("        run.py 실행 중이면 공유 버퍼 연결을 확인하세요.")
            return

    # 배치 수 계산
    if args.once:
        total_batches = 1
    else:
        total_batches = int((args.days * 24 * 60) / args.interval)
    total_target = total_batches * args.count

    mode_str = "공유버퍼(run.py 연동)" if use_shared else "카메라 직접 접근"
    print("=" * 52)
    print("  금붕어 파인튜닝 자동 캡처")
    print("=" * 52)
    print(f"  모드       : {mode_str}")
    print(f"  저장 경로  : {save_dir.resolve()}")
    print(f"  캡처 간격  : {args.interval}분")
    print(f"  회당 장수  : {args.count}장")
    if not args.once:
        print(f"  총 기간    : {args.days}일 ({total_batches}회)")
    print(f"  예상 총량  : {total_target}장")
    print("=" * 52)

    total_saved = 0
    try:
        for batch_num in range(1, total_batches + 1):
            print(f"\n[{datetime.now():%m/%d %H:%M}] "
                  f"배치 {batch_num}/{total_batches} 촬영 중...")

            if use_shared:
                n = capture_batch_shared(save_dir, args.count)
            else:
                n = capture_batch_camera(cap, save_dir, args.count)

            total_saved += n
            print(f"[{datetime.now():%m/%d %H:%M}] "
                  f"{n}장 저장 (누적 {total_saved}/{total_target}장)")

            if batch_num < total_batches:
                print(f"  → {args.interval}분 후 다음 배치")
                time.sleep(args.interval * 60)

    except KeyboardInterrupt:
        print(f"\n[STOP] 사용자 중단. 총 {total_saved}장 저장됨.")
    finally:
        if cap is not None:
            cap.release()

    print(f"\n[DONE] 완료. 총 {total_saved}장")
    print(f"       저장 위치: {save_dir.resolve()}")
    print("       Roboflow에 data/captures/ 폴더 통째로 업로드하세요.")


if __name__ == "__main__":
    main()
