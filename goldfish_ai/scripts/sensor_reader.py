"""
sensor_reader.py — ESP32 MQTT 수신 독립 Thread (v2 - MQTT)
금붕어 자동 사육 AI 시스템 (v2.0)

토픽:     goldfish/sensors
페이로드: {"temperature_c":22.5,"ph":7.2,"do_mg_l":6.8,"turbidity_ntu":12.3}

설계 원칙:
  - pipeline.py와 완전히 분리된 독립 Thread
  - pipeline.py는 get_latest()만 호출
  - MQTT 수신은 이 모듈만 담당

Pi 5 Mosquitto 설치:
  sudo apt update && sudo apt install mosquitto mosquitto-clients -y
  sudo systemctl enable mosquitto
  sudo systemctl start mosquitto

의존성:
  pip install paho-mqtt
"""

import json
import threading
import time
from dataclasses import dataclass, asdict
from typing import Optional

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────
# 센서 데이터 구조
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class SensorData:
    timestamp:      float = 0.0
    temperature_c:  float = 0.0
    ph:             float = 0.0
    do_mg_l:        float = 0.0
    turbidity_ntu:  float = 0.0
    valid:          bool  = False

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────
# 수질 기준값 (config.yaml과 동기화)
# ─────────────────────────────────────────────────────────────────────────
THRESHOLDS = {
    "temperature_c":  {"warn_min": 20.0, "warn_max": 25.5},
    "ph":             {"min": 6.5,  "max": 8.0},
    "do_mg_l":        {"min": 5.0,  "critical_min": 4.0},
    "turbidity_ntu":  {"max": 50.0, "critical": 100.0},
}


# ─────────────────────────────────────────────────────────────────────────
# SensorReader (MQTT)
# ─────────────────────────────────────────────────────────────────────────
class SensorReader:
    """
    ESP32로부터 MQTT JSON을 수신하고 최신값을 버퍼에 보관.
    pipeline.py는 get_latest()만 호출한다.
    """

    def __init__(self,
                 broker: str  = "localhost",
                 port:   int  = 1883,
                 topic:  str  = "goldfish/sensors",
                 mock:   bool = False):
        self.broker = broker
        self.port   = port
        self.topic  = topic
        self.mock   = mock

        self._latest: SensorData = SensorData()
        self._lock   = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop   = threading.Event()

        self._rx_count  = 0
        self._err_count = 0
        self._client    = None

    # ── 외부 인터페이스 ──────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        target = self._mock_loop if self.mock else self._mqtt_loop
        self._thread = threading.Thread(target=target, daemon=True,
                                        name="SensorReader")
        self._thread.start()
        mode = "MOCK" if self.mock else f"MQTT {self.broker}:{self.port}"
        print(f"[SensorReader] 시작 ({mode}, topic={self.topic})")

    def stop(self):
        self._stop.set()
        if self._client:
            self._client.disconnect()
        if self._thread:
            self._thread.join(timeout=3.0)
        print(f"[SensorReader] 종료 (수신:{self._rx_count} 오류:{self._err_count})")

    def get_latest(self) -> SensorData:
        """최신 센서값 반환. pipeline.py에서 이 메서드만 사용."""
        with self._lock:
            return self._latest

    def get_stats(self) -> dict:
        return {
            "rx":     self._rx_count,
            "err":    self._err_count,
            "broker": self.broker,
            "topic":  self.topic,
            "mock":   self.mock,
        }

    # ── MQTT 루프 ────────────────────────────────────────────────────────
    def _mqtt_loop(self):
        if not MQTT_AVAILABLE:
            print("[SensorReader] paho-mqtt 없음 → pip install paho-mqtt")
            print("[SensorReader] MOCK 모드로 전환")
            self._mock_loop()
            return

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print(f"[SensorReader] Broker 연결 완료 → {self.topic} 구독")
                client.subscribe(self.topic)
            else:
                print(f"[SensorReader] 연결 실패 (rc={rc})")

        def on_message(client, userdata, msg):
            data = self._parse(msg.payload.decode("utf-8", errors="ignore"))
            if data:
                with self._lock:
                    self._latest = data
                self._rx_count += 1

        def on_disconnect(client, userdata, rc):
            if rc != 0:
                print(f"[SensorReader] 연결 끊김 (rc={rc}) → 재연결 시도")

        while not self._stop.is_set():
            try:
                self._client = mqtt.Client(client_id="goldfish_sensor_reader")
                self._client.on_connect    = on_connect
                self._client.on_message    = on_message
                self._client.on_disconnect = on_disconnect

                self._client.connect(self.broker, self.port, keepalive=60)
                self._client.loop_start()

                while not self._stop.is_set():
                    time.sleep(0.5)

                self._client.loop_stop()
                break

            except Exception as e:
                print(f"[SensorReader] MQTT 오류: {e} → 5초 후 재연결")
                time.sleep(5.0)

    # ── Mock 루프 (ESP32 없이 테스트용) ─────────────────────────────────
    def _mock_loop(self):
        import math
        import random
        print("[SensorReader] Mock 모드: 더미 센서값 생성 중")
        t = 0
        while not self._stop.is_set():
            data = SensorData(
                timestamp     = time.time(),
                temperature_c = 22.5 + math.sin(t * 0.05) * 0.5 + random.gauss(0, 0.1),
                ph            = 7.2  + math.sin(t * 0.02) * 0.1 + random.gauss(0, 0.05),
                do_mg_l       = 6.5  + math.cos(t * 0.03) * 0.5 + random.gauss(0, 0.1),
                turbidity_ntu = 15.0 + abs(math.sin(t * 0.1)) * 10 + random.gauss(0, 1),
                valid         = True,
            )
            with self._lock:
                self._latest = data
            self._rx_count += 1
            t += 1
            time.sleep(1.0)

    # ── JSON 파싱 ────────────────────────────────────────────────────────
    def _parse(self, payload: str) -> Optional[SensorData]:
        """
        ESP32 JSON 파싱.
        {"temperature_c":22.5,"ph":7.2,"do_mg_l":6.8,"turbidity_ntu":12.3}
        """
        try:
            obj = json.loads(payload)
            return SensorData(
                timestamp     = time.time(),
                temperature_c = float(obj["temperature_c"]),
                ph            = float(obj["ph"]),
                do_mg_l       = float(obj["do_mg_l"]),
                turbidity_ntu = float(obj["turbidity_ntu"]),
                valid         = True,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[SensorReader] 파싱 오류: {e} | payload: {payload[:80]}")
            self._err_count += 1
            return None


# ─────────────────────────────────────────────────────────────────────────
# 수질 이상 판단 헬퍼 (decision.py에서 사용 예정)
# ─────────────────────────────────────────────────────────────────────────
def check_water_quality(data: SensorData) -> list[dict]:
    if not data.valid:
        return []

    alerts = []
    t = THRESHOLDS

    if (data.temperature_c < t["temperature_c"]["warn_min"] or
            data.temperature_c > t["temperature_c"]["warn_max"]):
        alerts.append({"param": "temperature_c", "level": "warning",
                        "value": data.temperature_c})

    if data.ph < t["ph"]["min"] or data.ph > t["ph"]["max"]:
        alerts.append({"param": "ph", "level": "warning", "value": data.ph})

    if data.do_mg_l < t["do_mg_l"]["critical_min"]:
        alerts.append({"param": "do_mg_l", "level": "critical",
                        "value": data.do_mg_l})
    elif data.do_mg_l < t["do_mg_l"]["min"]:
        alerts.append({"param": "do_mg_l", "level": "warning",
                        "value": data.do_mg_l})

    if data.turbidity_ntu > t["turbidity_ntu"]["critical"]:
        alerts.append({"param": "turbidity_ntu", "level": "critical",
                        "value": data.turbidity_ntu})
    elif data.turbidity_ntu > t["turbidity_ntu"]["max"]:
        alerts.append({"param": "turbidity_ntu", "level": "warning",
                        "value": data.turbidity_ntu})

    return alerts


# ─────────────────────────────────────────────────────────────────────────
# 단독 실행 (수신 테스트용)
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MQTT 센서 수신 테스트")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--topic",  default="goldfish/sensors")
    parser.add_argument("--mock",   action="store_true",
                        help="ESP32 없이 더미 데이터로 테스트")
    args = parser.parse_args()

    reader = SensorReader(broker=args.broker, topic=args.topic, mock=args.mock)
    reader.start()

    print("\n  센서 수신 중... (Ctrl+C 종료)\n")
    print(f"  {'수온':>6}  {'pH':>5}  {'DO':>6}  {'탁도':>8}  알림")
    print(f"  {'-'*55}")

    try:
        while True:
            d = reader.get_latest()
            if d.valid:
                alerts = check_water_quality(d)
                alert_str = ", ".join(
                    f"[{a['level'].upper()}] {a['param']}={a['value']:.2f}"
                    for a in alerts
                ) or "정상"
                print(f"  {d.temperature_c:>5.1f}°C  "
                      f"{d.ph:>4.2f}  "
                      f"{d.do_mg_l:>5.2f}  "
                      f"{d.turbidity_ntu:>7.1f}NTU  "
                      f"{alert_str}")
            time.sleep(1.0)

    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
