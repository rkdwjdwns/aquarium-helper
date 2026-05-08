"""
run.py — Goldfish AI 루트 진입점
금붕어 자동 사육 AI 시스템 (v2.0)

프로젝트 루트(GOLDFISH_AI/)에서 실행:
  python run.py                          # 카메라, config.yaml 자동 로드
  python run.py --show                   # 실시간 화면 표시
  python run.py --source video.mp4       # 영상 파일
  python run.py --config my_config.yaml  # 설정 파일 지정
  python run.py --mock-sensor            # ESP32 없이 센서 Mock

실행 중 키 (--show 모드):
  f — 급이 이벤트 기록 + FRS 분석 자동 예약
  q — 종료
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (어디서 실행해도 import 보장)
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.demo_pipeline import main

if __name__ == "__main__":
    main()
