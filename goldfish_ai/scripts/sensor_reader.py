"""
sensor_reader.py — ESP32 USB Serial 수신 독립 Thread (v4 - Serial Integrated)
금붕어 자동 사육 AI 시스템 (v2.0)

ESP32 출력 형식(현재 코드 호환):
  1) 권장 표준:
     {"temperature_c":22.5,"ph":7.2,"do_mg_l":6.8,"turbidity_ntu":12.3}

  2) 현재 ESP32 출력:
     {"temp":23.125,"ph":2.2375,"do":7.980548,"turb":326.5488,"level":100}

설계 원칙:
  - run.py에서 SensorReader를 1회만 시작
  - demo_pipeline.py는 run.py가 넘긴 shared_sensor를 재사용
  - 단독 실행 시에는 이 파일이 직접 Serial을 열어 테스트 가능
  - config.yaml의 sensor.port / baudrate / sample_count / timeout_sec 사용

의존성:
  pip install pyserial
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Any, Optional

try:
    import serial
    from serial import SerialException
    SERIAL_AVAILABLE = True
except ImportError:
    serial = None
    SerialException = Exception
    SERIAL_AVAILABLE = False


@dataclass
class SensorData:
    timestamp: float = 0.0
    temperature_c: float = 0.0
    ph: float = 0.0
    do_mg_l: float = 0.0
    turbidity_ntu: float = 0.0
    level: float = 0.0
    valid: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_THRESHOLDS = {
    "temperature_c": {"min": 21.0, "max": 24.0},
    "ph": {"min": 6.5, "max": 8.0},
    "do_mg_l": {"min": 5.0, "critical_min": 4.0},
    "turbidity_ntu": {"max": 50.0, "stress_level": 100.0},
}


class SensorReader:
    """
    ESP32 USB Serial JSON 수신기.
    외부에서는 start(), stop(), get_latest()만 사용한다.
    """

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baudrate: int = 115200,
        mock: bool = False,
        timeout: float = 1.0,
        sample_count: int = 1,
        reconnect_sec: float = 5.0,
        **_legacy_kwargs: Any,
    ):
        # _legacy_kwargs는 과거 MQTT 인자 broker/topic이 들어와도 즉시 죽지 않게 하기 위한 안전장치.
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.mock = mock
        self.sample_count = max(1, int(sample_count or 1))
        self.reconnect_sec = float(reconnect_sec)

        self._latest: SensorData = SensorData()
        self._samples: deque[SensorData] = deque(maxlen=self.sample_count)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._rx_count = 0
        self._err_count = 0
        self._serial = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        target = self._mock_loop if self.mock else self._serial_loop
        self._thread = threading.Thread(target=target, daemon=True, name="SensorReader")
        self._thread.start()

        mode = "MOCK" if self.mock else f"SERIAL {self.port} @ {self.baudrate}bps"
        avg = f", avg={self.sample_count}" if self.sample_count > 1 else ""
        print(f"[SensorReader] 시작 ({mode}{avg})")

    def stop(self):
        self._stop.set()
        self._close_serial()

        if self._thread:
            self._thread.join(timeout=3.0)

        print(f"[SensorReader] 종료 (수신:{self._rx_count} 오류:{self._err_count})")

    def get_latest(self) -> SensorData:
        with self._lock:
            return self._latest

    def get_stats(self) -> dict:
        return {
            "rx": self._rx_count,
            "err": self._err_count,
            "port": self.port,
            "baudrate": self.baudrate,
            "sample_count": self.sample_count,
            "mock": self.mock,
        }

    def _serial_loop(self):
        if not SERIAL_AVAILABLE:
            print("[SensorReader] pyserial 없음 → pip install pyserial")
            print("[SensorReader] MOCK 모드로 전환")
            self._mock_loop()
            return

        while not self._stop.is_set():
            try:
                self._open_serial()

                while not self._stop.is_set():
                    if self._serial is None or not getattr(self._serial, "is_open", False):
                        break

                    line = self._serial.readline()

                    if self._stop.is_set():
                        break

                    if not line:
                        continue

                    payload = line.decode("utf-8", errors="ignore").strip()
                    if not payload:
                        continue

                    data = self._parse(payload)
                    if data is None:
                        continue

                    data = self._apply_moving_average(data)

                    with self._lock:
                        self._latest = data

                    self._rx_count += 1

            except (SerialException, OSError) as e:
                if self._stop.is_set():
                    break
                self._err_count += 1
                print(f"[SensorReader] Serial 오류: {e} → {self.reconnect_sec:.0f}초 후 재연결")
                self._close_serial()
                self._wait_reconnect()

            except Exception as e:
                if self._stop.is_set():
                    break
                self._err_count += 1
                print(f"[SensorReader] 예외: {e} → {self.reconnect_sec:.0f}초 후 재연결")
                self._close_serial()
                self._wait_reconnect()

        self._close_serial()

    def _open_serial(self):
        self._close_serial()

        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )

        # ESP32-S3는 USB Serial 오픈 시 리셋될 수 있어 부팅 로그가 섞일 수 있음.
        time.sleep(2.0)

        try:
            self._serial.reset_input_buffer()
        except Exception:
            pass

        print(f"[SensorReader] Serial 연결 완료: {self.port}")

    def _close_serial(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            finally:
                self._serial = None

    def _wait_reconnect(self):
        end = time.time() + self.reconnect_sec
        while not self._stop.is_set() and time.time() < end:
            time.sleep(0.1)

    def _parse(self, payload: str) -> Optional[SensorData]:
        """
        ESP32 JSON 파싱.
        표준 키와 현재 ESP32 키를 모두 허용한다.

        허용 키:
          temperature_c | temp | temp_c | temperature
          ph | pH
          do_mg_l | do | dissolved_oxygen
          turbidity_ntu | turb | turbidity | ntu
          level 선택값
        """
        try:
            json_text = self._extract_json_object(payload)
            obj = json.loads(json_text)

            # ESP32 부팅/상태 로그는 센서 데이터가 아니므로 조용히 무시한다.
            if "status" in obj and not any(k in obj for k in ("temperature_c", "temp", "temp_c", "temperature")):
                return None

            return SensorData(
                timestamp=time.time(),
                temperature_c=self._get_float(
                    obj,
                    "temperature_c",
                    "temp",
                    "temp_c",
                    "temperature",
                ),
                ph=self._get_float(obj, "ph", "pH"),
                do_mg_l=self._get_float(
                    obj,
                    "do_mg_l",
                    "do",
                    "dissolved_oxygen",
                ),
                turbidity_ntu=self._get_float(
                    obj,
                    "turbidity_ntu",
                    "turb",
                    "turbidity",
                    "ntu",
                ),
                level=self._get_optional_float(obj, 0.0, "level", "water_level"),
                valid=True,
            )

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            print(f"[SensorReader] 파싱 오류: {e} | payload: {payload[:120]}")
            self._err_count += 1
            return None

    @staticmethod
    def _extract_json_object(payload: str) -> str:
        start = payload.find("{")
        end = payload.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise json.JSONDecodeError("JSON object not found", payload, 0)

        return payload[start:end + 1]

    @staticmethod
    def _get_float(obj: dict, *keys: str) -> float:
        for key in keys:
            if key in obj:
                return float(obj[key])
        raise KeyError(keys[0])

    @staticmethod
    def _get_optional_float(obj: dict, default: float, *keys: str) -> float:
        for key in keys:
            if key in obj:
                return float(obj[key])
        return float(default)

    def _apply_moving_average(self, data: SensorData) -> SensorData:
        if self.sample_count <= 1:
            return data

        self._samples.append(data)
        n = len(self._samples)

        return SensorData(
            timestamp=time.time(),
            temperature_c=sum(x.temperature_c for x in self._samples) / n,
            ph=sum(x.ph for x in self._samples) / n,
            do_mg_l=sum(x.do_mg_l for x in self._samples) / n,
            turbidity_ntu=sum(x.turbidity_ntu for x in self._samples) / n,
            level=sum(x.level for x in self._samples) / n,
            valid=True,
        )

    def _mock_loop(self):
        import math
        import random

        print("[SensorReader] Mock 모드: 더미 센서값 생성 중")

        t = 0
        while not self._stop.is_set():
            data = SensorData(
                timestamp=time.time(),
                temperature_c=22.5 + math.sin(t * 0.05) * 0.5 + random.gauss(0, 0.1),
                ph=7.2 + math.sin(t * 0.02) * 0.1 + random.gauss(0, 0.05),
                do_mg_l=6.5 + math.cos(t * 0.03) * 0.5 + random.gauss(0, 0.1),
                turbidity_ntu=15.0 + abs(math.sin(t * 0.1)) * 10 + random.gauss(0, 1),
                level=100.0,
                valid=True,
            )

            data = self._apply_moving_average(data)

            with self._lock:
                self._latest = data

            self._rx_count += 1
            t += 1
            time.sleep(1.0)


def check_water_quality(data: SensorData, thresholds: Optional[dict] = None) -> list[dict]:
    if not data.valid:
        return []

    t = thresholds or DEFAULT_THRESHOLDS
    alerts = []

    temp_cfg = t.get("temperature_c", {})
    temp_min = temp_cfg.get("warn_min", temp_cfg.get("min", DEFAULT_THRESHOLDS["temperature_c"]["min"]))
    temp_max = temp_cfg.get("warn_max", temp_cfg.get("max", DEFAULT_THRESHOLDS["temperature_c"]["max"]))

    if data.temperature_c < temp_min or data.temperature_c > temp_max:
        alerts.append({"param": "temperature_c", "level": "warning", "value": data.temperature_c})

    ph_cfg = t.get("ph", {})
    ph_min = ph_cfg.get("min", DEFAULT_THRESHOLDS["ph"]["min"])
    ph_max = ph_cfg.get("max", DEFAULT_THRESHOLDS["ph"]["max"])

    if data.ph < ph_min or data.ph > ph_max:
        alerts.append({"param": "ph", "level": "warning", "value": data.ph})

    do_cfg = t.get("do_mg_l", {})
    do_min = do_cfg.get("min", DEFAULT_THRESHOLDS["do_mg_l"]["min"])
    do_critical = do_cfg.get("critical_min", DEFAULT_THRESHOLDS["do_mg_l"]["critical_min"])

    if data.do_mg_l < do_critical:
        alerts.append({"param": "do_mg_l", "level": "critical", "value": data.do_mg_l})
    elif data.do_mg_l < do_min:
        alerts.append({"param": "do_mg_l", "level": "warning", "value": data.do_mg_l})

    turb_cfg = t.get("turbidity_ntu", {})
    turb_max = turb_cfg.get("max", DEFAULT_THRESHOLDS["turbidity_ntu"]["max"])
    turb_critical = turb_cfg.get(
        "critical",
        turb_cfg.get("stress_level", DEFAULT_THRESHOLDS["turbidity_ntu"]["stress_level"]),
    )

    if data.turbidity_ntu > turb_critical:
        alerts.append({"param": "turbidity_ntu", "level": "critical", "value": data.turbidity_ntu})
    elif data.turbidity_ntu > turb_max:
        alerts.append({"param": "turbidity_ntu", "level": "warning", "value": data.turbidity_ntu})

    return alerts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ESP32 Serial 센서 수신 테스트")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--mock", action="store_true", help="ESP32 없이 더미 데이터로 테스트")
    args = parser.parse_args()

    reader = SensorReader(
        port=args.port,
        baudrate=args.baudrate,
        sample_count=args.sample_count,
        mock=args.mock,
    )

    reader.start()

    print("\n  센서 수신 중... (Ctrl+C 종료)\n")
    print(f"  {'수온':>6}  {'pH':>5}  {'DO':>6}  {'탁도':>8}  {'수위':>6}  알림")
    print(f"  {'-' * 65}")

    try:
        while True:
            d = reader.get_latest()

            if d.valid:
                alerts = check_water_quality(d)

                alert_str = ", ".join(
                    f"[{a['level'].upper()}] {a['param']}={a['value']:.2f}"
                    for a in alerts
                ) or "정상"

                print(
                    f"  {d.temperature_c:>5.1f}°C  "
                    f"{d.ph:>4.2f}  "
                    f"{d.do_mg_l:>5.2f}  "
                    f"{d.turbidity_ntu:>7.1f}NTU  "
                    f"{d.level:>5.0f}%  "
                    f"{alert_str}"
                )

            time.sleep(1.0)

    except KeyboardInterrupt:
        pass

    finally:
        reader.stop()
