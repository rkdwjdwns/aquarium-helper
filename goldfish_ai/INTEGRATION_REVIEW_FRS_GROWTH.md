# FRS·성장예측 통합 점검 및 수정 결과

## 1. 최종 판정

업로드본은 새 FRS 및 `growth_prediction.py` 파일이 들어 있었지만, 실제 실행 흐름에는 구형 성장 모듈과 임의 계산 로직이 남아 있어 그대로는 신규 성장예측이 동작하지 않는 구조였다.

수정본은 다음 실행 경로로 정리했다.

```text
run.py
  ├─ SensorReader 1회 실행
  ├─ ServerTx 1회 실행
  ├─ DecisionLoop
  └─ demo_pipeline.py
       ├─ YOLO11 + ByteTrack
       ├─ FRS 예약 이벤트/분석
       ├─ 성장 측정값 집계
       ├─ vBGF 성장예측
       └─ 서버 전송
```

정적 컴파일과 합성 데이터 기반 통합 테스트는 통과했다. 실제 Pi Camera, ESP32, Render 서버 및 릴레이 하드웨어는 이 환경에서 직접 시험할 수 없으므로 현장 연동 테스트는 별도로 필요하다.

## 2. 발견한 주요 문제와 수정 내용

### 2.1 FRS

- 급이 후 관찰 시간이 구형 기본값 300초로 남은 부분을 180초로 통일했다.
- 예약 시각 이전에 이벤트가 조기 발동하여 pre/post 구간이 오염될 수 있는 문제를 차단했다.
- 예약 급이 이벤트 시각을 실제 감지 순간이 아니라 정확한 예약 슬롯 시각으로 기록한다.
- 재시작 시 같은 예약 슬롯이 중복 기록되지 않도록 기존 CSV에서 발동 슬롯을 복원한다.
- FRS 결과가 로컬 CSV에만 저장되고 서버로 전달되지 않던 경로를 연결했다.
- 최신 FRSResult 필드와 기존 백엔드 `feeding_sender.py` 필드 간 매핑을 수정했다.
- 0px/s 정지 상태도 급이 반응 분석에 포함한다.
- 급이 직전부터 TOP에 있던 개체를 0초 반응으로 잘못 처리하지 않고, 실제 비TOP→TOP 전이를 탐지한다.
- 실제 Pi 처리 속도가 9~12FPS일 때도 연속 관측 데이터가 충분하면 계산되도록 coverage 검사를 목표 FPS 고정 행 수 방식에서 실제 관측 프레임 방식으로 변경했다.
- 한 급이 이벤트의 FRS가 프레임마다 중복 저장되지 않도록 방지했다.

### 2.2 성장 추정 및 vBGF 예측

- 새 `growth_prediction.py`가 실제 파이프라인에서 호출되지 않던 문제를 수정했다.
- `run.py`에 남아 있던 `size_index × 0.5`, 3마리 하드코딩 임의 성장 전송 로직을 제거했다.
- 물고기 수를 Fish #1~#2 기준으로 변경했다.
- 면적 비율인 `size_index`를 픽셀 길이처럼 사용하던 단위 오류를 제거했다.
- 성장 측정은 `bbox_long_side_px`를 기본값으로 사용한다.
- `bbox_width_px`, `bbox_height_px`, `bbox_long_side_px`, `bbox_diagonal_px`를 feature/CSV에 추가했다.
- 겹침이 큰 bbox는 성장 측정에서 제외한다.
- 단일 프레임값이 아니라 1시간 동안 누적한 bbox 측정값을 MAD 이상치 제거 후 상위 75% 분위수로 집계한다.
- 정면 자세로 인해 bbox 장축이 짧아지는 체장 과소추정 영향을 완화했다.
- ByteTrack raw ID가 변경돼도 위치 기반 Fish #1~#2 안정 ID로 재연결한다.
- vBGF 모델에는 시간별 측정치를 그대로 넣지 않고 1일 단위 대표값으로 다시 집계한다. 시간별 반복 관측으로 표본 수와 R²가 과대평가되는 문제를 줄였다.
- 최소 7개 일별 기록과 최소 7일 관측 기간을 충족한 뒤 vBGF를 적합한다.
- SciPy `curve_fit`을 우선 사용하고, 설치되지 않은 경우 grid-search vBGF로 fallback한다.
- 최종 성체 체장 L∞, 성장계수 k, t0, R², RMSE, 95% 오차범위, 30일/90일 예측값을 계산한다.
- 선형회귀 결과도 비교용으로 보존한다.
- 성장 단계 기준은 `config.yaml`의 fry/juvenile/adult 범위를 사용한다.
- 새 기록이 생성된 개체만 서버로 전송해 다른 개체의 과거 결과가 중복 저장되는 문제를 막았다.

### 2.3 공통 실행 구조

- SensorReader와 ServerTx를 `run.py`에서 각각 1회만 생성하고 파이프라인에 공유한다.
- 서버 비활성 모드에서 Mock 전송 로그가 반복되지 않도록 수정했다.
- 별도 카메라 systemd 서비스가 `run.py`와 카메라를 동시에 점유하지 않도록 설치 스크립트를 정리했다.
- ESP32 통신은 MQTT가 아닌 `/dev/ttyACM0`, 115200bps USB Serial 기준으로 정리했다.
- ESP32 펌웨어의 실제 10초 송신 주기에 맞춰 설정값을 0.1Hz로 맞췄다.
- Pi 실행 가이드를 현재 프로젝트 경로와 통합 실행 방식으로 다시 작성했다.

## 3. 자동 검증 결과

수정본에서 다음 검사를 수행했다.

```text
Python compileall                         PASS
FRS pre/post 2마리, 실제 10FPS 조건       PASS
FRS 실제 TOP 진입 2초 탐지                PASS
FRS 동일 이벤트 중복 계산 방지            PASS
ByteTrack raw ID 변경 후 Fish #1 재연결    PASS
bbox 장축 분위수 성장 기록                PASS
시간별 데이터의 일별 모델 입력 집계        PASS
2개체 합성 vBGF 파라미터 복원              PASS
vBGF R²/RMSE 계산                          PASS
최신 FRSResult → ServerTx 매핑             PASS
최신 GrowthPredictionResult → ServerTx 매핑 PASS
TrackFilter 대표 ID 교체                   PASS
```

## 4. 실행 전 반드시 필요한 작업

### 4.1 카메라 체장 보정

현재 설정은 다음과 같다.

```yaml
camera:
  px_to_cm_ratio: 0.0
```

이 값이 0이면 성장 기록과 예측은 의도적으로 실행되지 않는다. 카메라와 수조를 고정한 뒤 기준 물체 또는 실측 물고기를 이용해 `1px당 cm` 값을 입력해야 한다.

보정 전 로그:

```text
[Growth] camera.px_to_cm_ratio=0 — 체장 기록/예측 대기 중
```

### 4.2 최소 데이터 기간

vBGF 예측은 단기 bbox 변화로 바로 계산하지 않는다.

```text
일별 대표 기록 최소 7개
관측 기간 최소 7일
```

그전에는 `not_enough_data` 또는 `not_enough_span` 상태로 현재 체장만 제공한다.

### 4.3 급이 시각과 실제 급이 동기화

FRS 기준 시각은 `feeding.times`의 예약 슬롯이다. 실제 급이기가 해당 시각에 작동해야 pre 60초/post 180초 구간이 의미가 있다. 실제 급이 지연이 크면 급이기 동작 완료 시각을 이벤트 timestamp로 전달하는 구조가 더 정확하다.

## 5. 아직 남은 외부 연동 한계

### 5.1 백엔드 성장 API 필드 부족

현재 `/api/growth/` sender는 다음 기존 필드만 전송한다.

```text
현재 체장
추정 체중
일 성장률
성장 단계
권장 급이량
```

신규 모델의 아래 값은 `data/growth_prediction.csv`에는 저장되지만 현재 백엔드 API로는 전송되지 않는다.

```text
L∞
k
t0
R²
RMSE
95% 신뢰구간
30일/90일 예측 체장
validation_mode
```

프론트에 성장예측 신뢰도까지 표시하려면 Django 모델/API/프론트 필드 확장이 필요하다.

### 5.2 안정 ID의 한계

Fish #1~#2 매핑은 위치 기반 완화 로직이다. 서로 겹치거나 교차하면 완전한 생체 재식별은 보장하지 못한다. 장기 개체별 성장 분석 정확도를 높이려면 외형 임베딩 기반 Re-ID 또는 크기·무늬 특징 결합이 추가로 필요하다.

### 5.3 실제 릴레이 제어

현재 `pi_client/command_poller.py`의 `set_relay()`는 터미널 출력용 시뮬레이션이다. 실제 4종 릴레이를 작동시키려면 최종 배선 방식에 따라 Pi GPIO 또는 ESP32 Serial 명령 제어를 구현해야 한다.

## 6. 적용 및 확인

전체 수정본을 프로젝트에 덮어쓰기 전에 기존 폴더를 백업한다.

```bash
cd ~/aquarium-helper
cp -a goldfish_ai goldfish_ai_backup
```

문법 검사:

```bash
cd ~/aquarium-helper/goldfish_ai
source venv/bin/activate
python -m compileall -q .
```

통합 실행:

```bash
python run.py
```

성장예측 단독 확인:

```bash
python scripts/analytics/growth_prediction.py \
  --config config.yaml \
  --input data/fish_metrics_파일명.csv \
  --fish-count 2 \
  --px-to-cm-ratio 실측값
```
