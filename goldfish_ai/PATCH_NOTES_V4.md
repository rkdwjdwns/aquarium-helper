# Aquarium Helper v4 AI Control 업그레이드 패치

기준: `rkdwjdwns/aquarium-helper`의 현재 프로젝트 구조와, 2026-09까지 실제 수집/보정한 AI 분석 규칙을 기준으로 정리한 리뷰용 패치.

## 1. 이번 버전에서 확정한 운영 범위

### 실제 실행 진입점
- `goldfish_ai/run.py`

### 센서 / 환경 제어
- 센서값은 기존 서버 API 흐름을 유지.
- 4번째 센서값은 `TDS(ppm)`으로 취급하며 NTU 탁도로 해석하지 않음.
- 실제 제어 범위:
  - `HEATER`: 수온 기반 rule control
  - `COOLING`: 수온 기반 rule control
  - `LIGHT`: 기본 시간 스케줄 + AI REST override
- `AIR_PUMP`: 실제 수조에서 상시 가동. 자동제어 대상 아님.
- `FEEDER`: 자체 앱 사용 장비로 외부 제어 불가. 자동제어 대상 아님.
- `FILTER`: 현재 제어 범위에서 제외.

### AI 분석 결과
발표 화면은 현재 CSV를 분리해서 사용.
- `activity_dashboard.csv`
- `abr_dashboard.csv`
- `feeding_response_v2.csv`
- `growth_dashboard.csv`

센서값은 CSV로 되돌리지 않고 기존 API를 사용한다.

## 2. AI 분석 v2

### Activity
- 5초 행동 집계.
- 동일 시간대 baseline median을 100으로 정규화.
- LOW: 같은 시간대 Q25 미만.
- NORMAL: Q25~Q75.
- HIGH: Q75 초과.
- 프론트에서 50/150 같은 고정 판정선을 사용하지 않음.

### ABR
- 같은 시간대 baseline P01~P99 범위를 벗어나는 유효 5초 bin을 abnormal로 정의.
- 최근 5분 유효 bin 중 abnormal 비율을 `abr_5min_pct`로 산출.
- AI REST 제어의 기준값은 현재 보정 결과를 반영한 13%.

### FRS
- 급이 전 5분 / 후 5분.
- Activity response 70% + response latency 30%.
- 영역(TOP/MID/BOT) 요소는 최종 점수에서 제외.
- 데이터 부족 시 점수 생성 금지(`INSUFFICIENT_DATA`).
- FRS는 급이 반응 지표이며 현재 외부 급이기를 제어하지 않음.

### Growth
- 두 마리 평균 성장 중심.
- 현재 manual anchor: 약 7.3cm / 8.0cm, 평균 7.65cm.
- 향후 카메라 측정은 `fish px / tank reference px * 30cm` 방식.
- 여러 프레임 중앙값과 오차범위를 사용.
- 미래 성장: vBGF.
- 비교선: 코메트 참고 성장 프로파일.

## 3. 신규: AI 기반 조명 REST 제어

신규 파일:
- `goldfish_ai/scripts/ai_control_policy.py`

목적:
- 단순 AI 시각화에서 끝나지 않고 `Camera -> AI Analysis -> Decision -> Hardware`의 폐루프를 구현.
- AI가 환경 안전 장치 전체를 직접 제어하지 않고, 조명에 한해 supervisory override를 수행.

### 제어 규칙
기본값은 `config.yaml`의 `ai_control.light_rest`에 있음.

1. `dashboard_ready == true`
2. `analysis_quality`가 `GOOD` 또는 `FAIR`
3. `ABR >= 13%`
4. 정상 조명 스케줄이 현재 ON 상태
5. 위 조건이 2회 연속 확인

=> `AI REST` 진입 후 조명 OFF.

### 상태
- `NORMAL`: 정상 스케줄 유지
- `WATCH`: 첫 이상 확인 또는 쿨다운 상태, 물리 제어 없음
- `REST`: AI override로 조명 OFF

### 시간 정책
- REST 최소 유지: 20분
- REST 종료 후 기존 조명 스케줄로 즉시 복귀
- 재진입 cooldown: 30분
- cooldown 중에는 ABR이 높아도 추가 REST를 시작하지 않음

### 품질 게이트
- `POOR`, `dashboard_ready=false`, ABR 없음 => AI가 조명을 제어하지 않음.
- Activity state는 제어 원인으로 단독 사용하지 않고 의사결정 로그의 context로 저장.

### 제어 로그
- `data/presentation/ai_control_decisions.csv`
- 상태 전이/제어 액션 발생 시 런타임이 행을 추가.
- 주요 컬럼:
  - `ai_state`
  - `action`
  - `abr_5min_pct`
  - `activity_state`
  - `analysis_quality`
  - `rest_until`
  - `cooldown_until`
  - `reason`

## 4. LIGHT 제어 ownership 변경

AI REST와 서버 polling이 동시에 LIGHT를 제어하면 서로 상태를 덮어쓸 수 있다.
따라서 v4에서는 ownership을 다음처럼 분리한다.

- `HEATER`, `COOLING`: `command_poller.py`의 서버 polling 대상
- `LIGHT`: `light_timer.py`가 단독 소유
  - 정상: 서버에서 받은 on/off 시간 스케줄
  - AI 이상: AI REST가 스케줄보다 우선하여 OFF
  - REST 종료: 스케줄로 복귀

`command_poller.py`의 `set_relay("LIGHT", ...)` 함수는 local light controller가 사용할 수 있도록 허용하지만, 서버에서 내려오는 LIGHT 상태는 `apply_commands()`에서 무시한다.

## 5. BehaviorBridge 초기화 순서 수정

기존 구조에서는 `run.py`의 DecisionThread가 먼저 `get_bridge()`를 호출하면 `demo_pipeline.py`가 config 기반으로 초기화하기 전에 singleton이 기본값으로 생성될 수 있었다.

v4에서는 DecisionThread 시작 전에 `run.py`가 `activity_v2` 설정과 baseline 경로로 BehaviorBridge를 먼저 초기화한다.
AI REST가 실시간 ABR에 의존하므로 이 초기화 순서를 명시적으로 고정했다.

## 6. 현재 의도적으로 제외한 항목

- 실시간 장애 자동복구 / STALE health card: 이번 범위에서 제외.
- Data Quality & Calibration Engine의 완전 자동 pipeline/API화: 추후 고도화.
- FRS -> 자동급이: 급이기 외부제어 불가로 제외.
- ABR -> AIR_PUMP: 에어펌프는 상시가동이며 인과관계도 단정하지 않음.
- Activity -> HEATER/COOLING: 환경 제어는 수온센서 기반 rule을 유지.

## 7. 매우 중요한 실제 하드웨어 확인사항

현재 GitHub 기준 `pi_client/command_poller.py`의 `set_relay()`는 GPIO를 실제로 쓰는 코드가 아니라 콘솔에 상태를 출력하는 시뮬레이션 함수다.

따라서 이번 패치로 **AI 의사결정 -> LIGHT control software path**는 완성되지만, 실제 조명을 물리적으로 OFF/ON하려면 현재 Raspberry Pi에서 사용 중인 릴레이/GPIO 제어 구현과 연결되어 있어야 한다.

만약 실제 Pi의 `command_poller.py`에 이미 GPIO 코드가 별도로 적용되어 있다면 이번 파일을 통째로 덮어쓰지 말고 다음 변경만 merge해야 한다.
- `POLLABLE_DEVICES = {"HEATER", "COOLING"}`
- `LIGHT`는 서버 polling에서 제외
- 기존 실제 `set_relay()` 구현은 유지

GitHub 주석상의 과거 pin 예시는 LIGHT GPIO24였지만 실제 배선 확인 없이 패치에서 GPIO를 강제 활성화하지 않았다.

## 8. Django/TDS 잔여 작업

기존 Django backend가 `turbidity`를 NTU로 해석하거나 FILTER/AIR_PUMP 자동제어에 사용하는 코드가 남아 있다면 별도 정리가 필요하다.

최종 방향:
- POST/GET 센서 계약: `tds_ppm`
- TDS를 NTU로 취급 금지
- TDS로 FILTER 제어 금지
- AIR_PUMP 제어 제거(상시가동)
- HEATER/COOLING만 센서 기반 자동제어
- LIGHT는 스케줄 + Pi의 AI REST ownership과 충돌하지 않도록 서버 명령 모델 정리

## 9. 적용 전 테스트 결과

현재 패치 작업환경에서 확인:
- Python `compileall` 통과
- `config.yaml` 파싱 통과
- AI Control state machine 테스트 통과
  - NORMAL -> WATCH -> REST -> schedule release
  - 20분 REST
  - 30분 cooldown
  - POOR/미준비 데이터에서 제어하지 않음
  - 스케줄 OFF 상태에서 REST 카운트 누적하지 않음
- LIGHT local override 테스트 통과
  - schedule ON -> LIGHT ON
  - AI REST -> LIGHT OFF
  - REST release -> schedule ON 복귀
- server command polling에서 LIGHT는 무시하고 HEATER는 반영하는 ownership 테스트 통과

## 10. 권장 적용 순서

1. 현재 Raspberry Pi 프로젝트 백업/branch 생성.
2. Pi에서 실제 `command_poller.py`의 `set_relay()`가 simulation인지 실제 GPIO인지 확인.
3. 실제 GPIO 코드가 있으면 해당 함수는 보존한 채 v4 변경사항 merge.
4. v4 패치 overlay.
5. `config.yaml`의 AI REST 설정 확인.
6. `python3 -m compileall -q .` 수행.
7. `run.py` 실행 후 Activity/ABR이 정상 갱신되는지 확인.
8. 테스트 시 ABR 조건을 임시로 낮추거나 test harness를 사용해 WATCH -> REST -> LIGHT OFF -> 복귀를 검증.
9. 검증 후 ABR threshold를 13%, REST 20분, cooldown 30분으로 원복/확인.
10. 발표 화면은 기존 4개 AI 분석 CSV를 사용하고, 필요하면 `ai_control_decisions.csv`를 AI 제어 이력 화면에 추가.
