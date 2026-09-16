# 분석 CSV 자동 생성 파이프라인

## 목적

분석 화면에서 사용하는 CSV를 사람이 직접 편집하지 않고,
Django DB에 저장된 원천 데이터와 과거 폐사 개체 재구성 원천 자료를
자동으로 분석용 CSV로 변환합니다.

## 데이터 흐름

```text
ESP32 / Raspberry Pi / 개체 추적
              |
              v
         Django DB
              |
              |  GrowthRecord
              |  FishActivityDetail
              |  FeedingEvent / FeedingResponse
              |
              +------------------------------+
                                             |
폐사 개체 재구성 원천 CSV ------------------+
deceased_fish_growth_reconstructed.csv       |
                                             v
                           python manage.py generate_analysis_csv
                                             |
                  +--------------------------+-----------------------+
                  |              |                |                  |
                  v              v                v                  v
        growth_analysis.csv activity_analysis.csv abr_analysis.csv feeding_analysis.csv
                  |              |                |                  |
                  +--------------------------+-----------------------+
                                             |
                                             v
                                      분석 페이지 시각화
```

## 실행

```bash
python manage.py generate_analysis_csv
```

특정 어항:

```bash
python manage.py generate_analysis_csv --tank-id 1
```

폐사 개체 재구성 자료 제외:

```bash
python manage.py generate_analysis_csv --tank-id 1 --without-reconstructed
```

## 생성 파일

`static/monitoring/data/`

- `growth_analysis.csv`
- `activity_analysis.csv`
- `abr_analysis.csv`
- `feeding_analysis.csv`

자동 생성 결과이므로 Git에는 저장하지 않습니다.

## 데이터 출처

- `measured`: DB에 저장된 실제 수집/분석 결과
- `synthetic_reconstruction`: 당시 관찰 정보를 바탕으로 재구성한 폐사 개체 분석용 자료

재구성 자료를 실제 측정값이라고 표현하지 않습니다.

## 성장 CSV

주요 컬럼:

- `timestamp`
- `day_since_first`
- `fish_id`
- `estimated_length_cm`
- `estimated_weight_g`
- `growth_rate_cm_day`
- `growth_stage`
- `life_status`
- `data_source`
- `note`

정확한 폐사 날짜가 없는 Fish 3은 임의 날짜를 만들지 않고
`day_since_first`로 비교합니다.

## 활동 CSV

주요 컬럼:

- `fish_id`
- `activity_level_px_s`
- `dominant_zone`
- `behavior_status`
- `is_anomaly`
- `life_status`
- `data_source`

## ABR CSV

주요 컬럼:

- `fish_id`
- `abr_score`
- `abr_pct`
- `dominant_zone`
- `behavior_status`
- `is_anomaly`
- `life_status`
- `data_source`

재구성 자료에 대해 임의 정상/주의 기준을 추가하지 않고 원본 ABR 값만 제공합니다.

## 급이 CSV

주요 컬럼:

- `event_id`
- `meal_no`
- `status`
- `feed_amount_g`
- `frs_score`
- `response_latency_sec`
- `activity_before_px_s`
- `activity_during_px_s`
- `activity_after_px_s`
- `activity_increase_pct`

급이 반응 데이터가 없으면 `status=NO_RESPONSE_DATA`로 출력하고
없는 값을 임의 숫자로 채우지 않습니다.

## Render 배포

수정된 `build.sh` 실행 순서:

1. migrate
2. seed_state_codes
3. generate_analysis_csv
4. collectstatic
5. 관리자 계정 확인

따라서 새 배포 시 분석 CSV가 자동 생성되어 정적 파일에 포함됩니다.

`ANALYSIS_TANK_ID` 환경변수를 설정하면 해당 Tank를 사용하고,
설정하지 않으면 가장 먼저 생성된 Tank를 사용합니다.

## 프론트 파일명 변경

기존:

```javascript
const FEEDING_CSV_URL = "{% static 'monitoring/data/feeding_analysis_mock.csv' %}";
const ABR_CSV_URL = "{% static 'monitoring/data/abr_analysis_mock.csv' %}";
const ACTIVITY_CSV_URL = "{% static 'monitoring/data/activity_analysis_mock.csv' %}";
const GROWTH_CSV_URL = "{% static 'monitoring/data/growth_analysis_mock.csv' %}";
```

변경:

```javascript
const FEEDING_CSV_URL = "{% static 'monitoring/data/feeding_analysis.csv' %}";
const ABR_CSV_URL = "{% static 'monitoring/data/abr_analysis.csv' %}";
const ACTIVITY_CSV_URL = "{% static 'monitoring/data/activity_analysis.csv' %}";
const GROWTH_CSV_URL = "{% static 'monitoring/data/growth_analysis.csv' %}";
```

새 CSV 스키마에 맞춰 JS 컬럼 파싱도 수정해야 합니다.

## 기존 mock 파일

새 프론트가 정상 동작하면 삭제:

- `growth_analysis_mock.csv`
- `activity_analysis_mock.csv`
- `abr_analysis_mock.csv`
- `feeding_analysis_mock.csv`

`deceased_fish_growth_reconstructed.csv`는 원천 자료이므로 유지합니다.
