# 내일 하드웨어 연동 준비 가이드

## 1. Arduino IDE 설치 및 ESP32 보드 설정

### Arduino IDE 설치
https://www.arduino.cc/en/software 에서 다운로드

### ESP32 보드 추가
1. Arduino IDE → 파일 → 환경설정
2. 추가 보드 관리자 URL에 입력:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. 툴 → 보드 → 보드 관리자 → `esp32` 검색 → 설치

### 보드 선택
- 툴 → 보드 → ESP32 Arduino → **ESP32S3 Dev Module**

### 필수 라이브러리 설치 (툴 → 라이브러리 관리자)
- `OneWire` — DS18B20 수온 센서
- `DallasTemperature` — DS18B20 온도 계산
- `ArduinoJson` — JSON 직렬화

---

## 2. Raspberry Pi 5 초기 설정

### OS 설치
1. https://www.raspberrypi.com/software/ 에서 Raspberry Pi Imager 다운로드
2. SD카드 선택 → OS: **Raspberry Pi OS Lite (64-bit)** 선택
3. 톱니바퀴(설정) 클릭:
   - Wi-Fi SSID / 비밀번호 입력
   - SSH 활성화 체크
   - 사용자명: `pi` / 비밀번호 설정
4. 굽기(Write) → SD카드 Pi에 삽입 후 부팅

### SSH 접속 (같은 Wi-Fi에서)
```bash
ssh pi@raspberrypi.local
# 또는
ssh pi@[Pi의 IP 주소]
```

### 시스템 업데이트
```bash
sudo apt update && sudo apt upgrade -y
```

### Python 패키지 설치
```bash
sudo apt install python3-pip python3-venv -y
cd ~
python3 -m venv venv
source venv/bin/activate
pip install requests pyserial ultralytics opencv-python RPi.GPIO python-dotenv
```

### UART 활성화 (ESP32 통신용)
```bash
sudo raspi-config
# Interface Options → Serial Port
# "login shell over serial?" → No
# "serial port hardware enabled?" → Yes
sudo reboot
```

---

## 3. pi_client 파일 Pi로 전송

### PC에서 Pi로 scp 전송
```bash
# Windows PowerShell에서
scp -r C:\Users\rkdwj\pi_client pi@raspberrypi.local:~/
```

### Pi에서 직접 GitHub clone
```bash
git clone https://github.com/rkdwjdwns/aquarium-helper.git
cp -r aquarium-helper/pi_client ~/pi_client
```

---

## 4. YOLOv11 모델 다운로드 (Pi에서)
```bash
cd ~/pi_client
source ~/venv/bin/activate
python download_model.py
```

---

## 5. 연동 테스트 순서

```bash
# 1. 서버 연결 확인
python test_server.py

# 2. ESP32 연결 후 UART 수신 확인
python serial_reader.py

# 3. 전체 메인 루프 실행
python main.py
```

---

## GPIO 핀 배선 요약

| 장치 | ESP32 핀 | Pi 핀 |
|------|---------|-------|
| DS18B20 수온 | GPIO 4 | — |
| pH ADC | GPIO 34 | — |
| DO ADC | GPIO 35 | — |
| 탁도 ADC | GPIO 32 | — |
| 수위 ADC | GPIO 33 | — |
| UART TX→Pi | GPIO 17 | GPIO 15 (Pin 10) |
| GND 공통 | GND | Pin 6 |
| 히터 릴레이 | — | GPIO 17 (Pin 11) |
| 냉각팬 릴레이 | — | GPIO 18 (Pin 12) |
| 여과기 릴레이 | — | GPIO 27 (Pin 13) |
| 에어펌프 릴레이 | — | GPIO 22 (Pin 15) |

> ⚠️ Pi GPIO 17이 릴레이와 UART RX 둘 다 쓰임 — command_poller.py에서 HEATER 핀을 GPIO 25로 변경 권장
