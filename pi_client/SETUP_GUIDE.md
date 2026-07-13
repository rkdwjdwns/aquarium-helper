# Goldfish AI Raspberry Pi 실행 가이드

## 1. 기준 구조

프로젝트는 다음 경로를 기준으로 실행한다.

```text
/home/raspi/aquarium-helper/goldfish_ai
├── run.py
├── config.yaml
├── scripts/
└── pi_client/
```

`run.py`가 아래 기능을 통합 실행한다.

- ESP32 USB Serial 센서 수신
- Pi Camera 영상 분석
- YOLO11 + ByteTrack 추적
- FRS 및 성장 분석
- 서버 전송
- MJPEG 스트리밍

별도 `pi_client/main.py` 또는 별도 카메라 서비스를 동시에 실행하지 않는다.

## 2. Python 환경

```bash
cd /home/raspi/aquarium-helper/goldfish_ai
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r pi_client/requirements.txt
```

Pi Camera 지원 패키지는 Raspberry Pi OS에서 설치한다.

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv
```

SciPy 설치가 어려운 경우에도 성장예측은 내부 grid-search fallback으로 동작한다.

## 3. ESP32 연결

현재 연결은 MQTT가 아니라 USB Serial이다.

```text
ESP32-S3 USB → Raspberry Pi USB
장치 경로       → /dev/ttyACM0
통신 속도       → 115200 bps
페이로드        → JSON 1줄
현재 송신 주기  → 약 10초
```

USB Serial 연결에는 `raspi-config`의 GPIO UART 활성화가 필요하지 않다.

장치 확인:

```bash
ls -l /dev/ttyACM*
```

권한 오류가 나면:

```bash
sudo usermod -aG dialout raspi
sudo reboot
```

센서 단독 테스트:

```bash
cd /home/raspi/aquarium-helper/goldfish_ai
source venv/bin/activate
python scripts/sensor_reader.py --port /dev/ttyACM0 --baudrate 115200
```

## 4. 설정 확인

`config.yaml`의 핵심 설정:

```yaml
pipeline:
  expected_fish_count: 2

sensor:
  mode: serial
  port: /dev/ttyACM0
  baudrate: 115200

analytics:
  frs:
    before_sec: 60.0
    during_sec: 180.0

growth_prediction:
  enabled: true
  expected_fish_count: 2
```

성장 분석은 카메라 보정 전에는 대기 상태다.

```yaml
camera:
  px_to_cm_ratio: 0.0
```

실측 보정 후 1픽셀당 cm 값을 입력해야 `growth_records.csv` 및 vBGF 예측이 생성된다.

## 5. 통합 실행

```bash
cd /home/raspi/aquarium-helper/goldfish_ai
source venv/bin/activate
python run.py
```

화면 확인 포함:

```bash
python run.py --show
```

서버 전송 없이 로컬 테스트:

```bash
python run.py --mock-sensor --no-server --show
```

종료:

```text
Ctrl+C
```

## 6. systemd 등록

```bash
cd /home/raspi/aquarium-helper/goldfish_ai
bash pi_client/install_services.sh
```

확인:

```bash
sudo systemctl status aquarium
journalctl -u aquarium -f
```

`run.py`가 카메라 스트리밍까지 담당하므로 `aquarium-camera.service`는 설치하지 않는다.

## 7. 출력 파일

```text
data/fish_metrics_*.csv       프레임별 행동 데이터
data/feeding_events.csv       예약 급이 이벤트
data/frs_history.csv          FRS 결과
data/growth_records.csv       개체별 체장 기록
data/growth_prediction.csv    vBGF 성장예측 결과
data/sensor_log.csv           수질 센서 기록
```

## 8. 릴레이 주의사항

현재 `command_poller.py`의 `set_relay()`는 시뮬레이션 출력 상태다. 실제 4종 릴레이를 작동하려면 현재 하드웨어 배선 위치에 맞춰 GPIO 또는 ESP32 명령 송신 코드를 별도로 활성화해야 한다.

대상 장치는 다음 4종이다.

```text
HEATER
COOLING
FILTER
AIR_PUMP
```
