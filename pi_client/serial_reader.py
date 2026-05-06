"""
serial_reader.py
ESP32 → Pi UART 수신 모듈

수신 포맷 (JSON 1줄):
  {"temp": 22.5, "ph": 7.2, "do": 6.8, "turb": 12.3, "level": 90.0}

사용법:
  from serial_reader import SerialReader

  reader = SerialReader()
  data = reader.read()
  if data:
      print(data["temp"])  # 22.5
"""

import json
import serial
import serial.tools.list_ports


# ── 기본 설정 ──────────────────────────────────
SERIAL_PORT = "/dev/ttyUSB0"   # Pi에서 ESP32 연결 포트
BAUD_RATE   = 115200
TIMEOUT_SEC = 3.0


def find_esp32_port() -> str | None:
    """연결된 ESP32 포트를 자동으로 탐색합니다."""
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        if any(k in desc for k in ["cp210", "ch340", "ftdi", "usb serial"]):
            print(f"[SERIAL] ESP32 포트 자동 감지: {p.device}")
            return p.device
    return None


class SerialReader:
    def __init__(self, port: str = SERIAL_PORT, baud: int = BAUD_RATE):
        detected = find_esp32_port()
        self.port = detected or port
        self.baud = baud
        self._ser: serial.Serial | None = None
        self._connect()

    def _connect(self):
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=TIMEOUT_SEC)
            print(f"[SERIAL] 연결 성공: {self.port} @ {self.baud}bps")
        except serial.SerialException as e:
            print(f"[SERIAL] 연결 실패: {e}")
            self._ser = None

    def read(self) -> dict | None:
        """
        ESP32에서 JSON 1줄을 읽어 dict로 반환합니다.

        Returns:
            {
                "temp" : float,   # 수온 (°C)
                "ph"   : float,   # pH
                "do"   : float,   # 용존산소 (mg/L)
                "turb" : float,   # 탁도 (NTU)
                "level": float,   # 수위 (%)
            }
            또는 None (읽기 실패 시)
        """
        if self._ser is None:
            self._connect()
            return None

        try:
            line = self._ser.readline().decode("utf-8").strip()
            if not line:
                return None

            data = json.loads(line)

            # status 메시지는 무시
            if "status" in data:
                print(f"[SERIAL] ESP32: {data['status']}")
                return None

            return data

        except json.JSONDecodeError:
            print(f"[SERIAL] JSON 파싱 오류: {line!r}")
        except serial.SerialException as e:
            print(f"[SERIAL] 수신 오류: {e}")
            self._ser = None
        except Exception as e:
            print(f"[SERIAL] 알 수 없는 오류: {e}")

        return None

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()
            print("[SERIAL] 연결 종료")


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    reader = SerialReader()
    print("ESP32 데이터 수신 대기 중... (Ctrl+C로 종료)")
    try:
        while True:
            data = reader.read()
            if data:
                print(f"수온={data.get('temp')}°C  pH={data.get('ph')}  "
                      f"DO={data.get('do')}mg/L  탁도={data.get('turb')}NTU  "
                      f"수위={data.get('level')}%")
    except KeyboardInterrupt:
        reader.close()
