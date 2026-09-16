# Aquarium Helper 제출 전 수정본 업로드 가이드

이 ZIP은 **프론트 파일을 건드리지 않고**, 발표용 임시값/하드코딩/자동삭제/보안 fallback을 정리한 수정본입니다.

## 1. 그대로 교체해서 업로드할 파일

ZIP 내부 경로를 GitHub 저장소의 같은 경로에 덮어쓰세요.

- `pi_client/config.py`
- `pi_client/main.py`
- `pi_client/sensor_sender.py`
- `pi_client/serial_reader.py`
- `pi_client/feeding_controller.py`
- `build.sh`
- `apps/monitoring/management/commands/cleanup_old_data.py`
- `fish/settings.py`
- `.env.example`
- `static/monitoring/data/deceased_fish_growth_reconstructed.csv`

## 2. api_views.py 보안 우회 제거

`apps/monitoring/api_views.py`는 1,000줄이 넘는 핵심 파일이라 ZIP에서 통째로 교체하지 않았습니다.
대신 현재 GitHub 코드의 정확한 두 구간만 바꾸는 스크립트를 넣었습니다.

로컬 저장소 루트에서 다음을 실행하세요.

```bash
python tools/apply_api_security_patch.py
```

실행 후 변경된 파일:
- `apps/monitoring/api_views.py`

그 다음 **변경된 `apps/monitoring/api_views.py` 자체를 GitHub에 커밋**하세요.

`tools/apply_api_security_patch.py`는 작업용 도구이므로 제출 저장소에 올려도 되고, 올리지 않아도 됩니다.

## 3. Render 환경변수에서 반드시 확인할 값

다음 값은 코드에 넣지 말고 Render Environment에 설정하세요.

- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS=aquarium-helper.onrender.com`
- `DATABASE_URL`
- `PI_API_KEY`
- 필요 시 `GEMINI_API_KEY_1` 또는 `GEMINI_API_KEY_2`
- 관리자 자동 생성이 필요하면
  - `DJANGO_SUPERUSER_USERNAME`
  - `DJANGO_SUPERUSER_PASSWORD`
  - `DJANGO_SUPERUSER_EMAIL`

`PI_API_KEY`는 Raspberry Pi 환경변수에도 **같은 값**을 설정해야 합니다.

## 4. Raspberry Pi 환경변수

예시:

```bash
export PI_API_KEY='실제-긴-랜덤-키'
export AQUARIUM_BASE_URL='https://aquarium-helper.onrender.com/monitoring'
export TANK_ID='1'
python pi_client/main.py
```

## 5. 수정 내용 요약

- `fish_count=2`, `activity_level=14.5`, Fish 1 `2.1cm` 등 발표용 고정 AI 결과 제거
- 센서 누락 시 22.0°C / pH 7.4 / DO 6.0 등 정상값을 만들어 보내던 fallback 제거
- ESP32 `turb` 채널을 실제 센서 성격에 맞게 TDS(ppm)로 전송
- 급이 설정 URL의 `/monitoring/monitoring/...` 중복 가능성 수정
- 실제 탁도/행동 측정 없이 급이 후 값을 계산해서 저장하던 로직 제거
- 실제 GPIO 급이기가 연결되지 않은 상태에서 성공 급이 이벤트를 만들지 않도록 수정
- 배포 시 2주 이전 데이터를 자동 삭제하던 `build.sh` 로직 제거
- `cleanup_old_data`는 `--weeks`와 `--confirm`을 명시해야만 삭제하도록 보호
- `admin/admin1234` 기본 관리자 계정 제거
- Django `SECRET_KEY` 하드코딩 fallback 제거, `DEBUG` 기본값 False
- Pi API Key 하드코딩 fallback 제거
- 서버에서 `PI_API_KEY` 미설정 시 요청을 통과시키던 fail-open 제거용 패치 제공

## 6. 폐사 개체 CSV 주의

`static/monitoring/data/deceased_fish_growth_reconstructed.csv`는
**실측 원본이 아니라 시각화/분석 보완을 위한 재구성 데이터**입니다.

- Fish ID: 3
- 초기 체장: 약 2.9cm
- 생존 기간: 약 19일
- 후반부 성장 정체 + 활동량 감소 + ABR 상승 흐름
- `data_source=synthetic_reconstruction`으로 명시

발표/보고서/README에서 이 데이터를 실제 계측 원본이라고 표현하지 마세요.
권장 표현:
"당시 실측 기록이 충분하지 않아, 관찰된 초기 크기와 생존 기간을 기준으로 분석 화면 검증용 시계열을 재구성하였다."

## 7. 업로드 후 확인

```bash
python manage.py check
python manage.py migrate --check
```

Render 재배포 후에는:
- 센서 POST가 정상적으로 인증되는지
- `PI_API_KEY` 미설정 상태에서 요청이 거부되는지
- 배포 시 기존 센서/행동 데이터가 삭제되지 않는지
- Pi에서 TDS 값이 `tds_ppm`으로 저장되는지

를 확인하세요.
