# Goldfish AI

Raspberry Pi 5 기반 관상어 모니터링·AI 분석·자동제어 프로젝트입니다.

## 실행

통합 실행 진입점은 `goldfish_ai/run.py`입니다.

```bash
cd goldfish_ai
python run.py
```

## 센서 및 제어

- 센서: 수온(°C), pH, DO(mg/L), TDS(ppm)
- HEATER / COOLING: Django `Tank`의 기준값으로 서버가 자동제어
- FILTER: Django 시간 스케줄로 자동제어. 기본 `00:00~00:00`은 안전한 기본값으로 24시간 ON
- LIGHT: Raspberry Pi 시간 스케줄 + ABR 기반 AI REST override
- AIR_PUMP: 실제 수조에서 상시가동, 소프트웨어 제어 제외
- FEEDER: 외부 앱 자체 제어, 본 시스템 제어 제외

## AI 분석

- Activity: 동일 시간대 baseline median 대비 Activity Index, Q25/Q75 상태판정
- ABR: 동일 시간대 P01~P99 이탈 5초 bin의 최근 5분 비율, Alert 기준 `>= 13%`
- FRS: 급이 전/후 행동을 이용한 Activity response 70% + response latency 30%
- Growth: 수조 30cm 기준 ratio→cm 추정 + vBGF 예측

AI 조명 제어는 ABR `>= 13%`가 연속 2회 확인되고 분석 품질이 GOOD/FAIR인 경우 REST 모드로 진입해 조명을 일시적으로 OFF합니다.

## 발표용 데이터 위치

```text
goldfish_ai/data/
├── activity_baseline_v2.csv
├── dashboard_rules_v2.json
└── presentation/
    ├── activity_dashboard.csv
    ├── abr_dashboard.csv
    ├── feeding_response_v2.csv
    └── growth_dashboard.csv
```

`activity_baseline_v2.csv`는 발표용 파일이 아니라 Activity/ABR 런타임 계산에도 필요한 기준 데이터입니다.
`ai_control_decisions.csv`는 실행 시 자동 생성됩니다.

## Growth calibration

고정 카메라 화면에서 보이는 수조 내부 기준 폭(px)을 측정한 뒤 `config.yaml`의
`growth_prediction.reference_length_px`에 입력합니다. 실제 기준 길이는 30cm입니다.
