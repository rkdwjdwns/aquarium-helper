# 업로드 가이드

## 추가

GitHub 저장소의 동일 경로에 추가:

```text
apps/monitoring/management/commands/generate_analysis_csv.py
docs/ANALYSIS_PIPELINE.md
```

## 교체

기존 파일 교체:

```text
build.sh
.gitignore
```

## 유지

이미 존재하는 원천 파일:

```text
static/monitoring/data/deceased_fish_growth_reconstructed.csv
```

이 파일은 생성 결과가 아니라 Fish 3 과거 재구성 원천 데이터입니다.

## 프론트 수정 위치

```text
templates/monitoring/analysis.html
```

파일명 변경:

```text
feeding_analysis_mock.csv -> feeding_analysis.csv
abr_analysis_mock.csv      -> abr_analysis.csv
activity_analysis_mock.csv -> activity_analysis.csv
growth_analysis_mock.csv   -> growth_analysis.csv
```

새 CSV는 개체별 구조라 JS 파싱 컬럼도 `docs/ANALYSIS_PIPELINE.md`를 기준으로 수정하세요.

## 로컬 테스트

```bash
python manage.py generate_analysis_csv --tank-id 1
python manage.py check
```

성공 시 자동 생성:

```text
static/monitoring/data/growth_analysis.csv
static/monitoring/data/activity_analysis.csv
static/monitoring/data/abr_analysis.csv
static/monitoring/data/feeding_analysis.csv
```

위 네 파일은 `.gitignore` 대상입니다.

## Render 환경변수

권장:

```text
ANALYSIS_TANK_ID=1
```

Tank가 하나뿐이면 없어도 동작합니다.

## Render 자동화

GitHub push → Render build 시:

```text
migrate
  ↓
seed_state_codes
  ↓
generate_analysis_csv
  ↓
collectstatic
```

즉 배포 시마다 최신 DB 기준 분석 CSV를 다시 생성합니다.

## 프론트 전환 완료 후 기존 mock 파일 삭제

```bash
git rm static/monitoring/data/growth_analysis_mock.csv
git rm static/monitoring/data/activity_analysis_mock.csv
git rm static/monitoring/data/abr_analysis_mock.csv
git rm static/monitoring/data/feeding_analysis_mock.csv
```

## 권장 커밋

```bash
git add apps/monitoring/management/commands/generate_analysis_csv.py
git add docs/ANALYSIS_PIPELINE.md
git add build.sh .gitignore
git commit -m "feat: automate analysis CSV generation"
git push
```
