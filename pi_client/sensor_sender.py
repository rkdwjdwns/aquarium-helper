"""ESP32 -> Pi -> Django sensor API sender.

The fourth physical sensor channel is TDS (ppm), not turbidity (NTU).
`tds_ppm` is sent explicitly. A legacy `turbidity` field is kept as 0.0 so an
older backend does not accidentally apply NTU thresholds to TDS values.
"""
import requests
from config import BASE_URL, HEADERS, TANK_ID


def send_sensor(
    temperature: float,
    ph: float,
    dissolved_oxygen: float,
    turbidity: float = 0.0,
    water_level: float = 100.0,
    tds_ppm: float | None = None,
) -> dict | None:
    # Backward-call compatibility: old callers may still pass the 4th positional
    # value as `turbidity`. New code should always pass tds_ppm by keyword.
    if tds_ppm is None:
        tds_ppm = 0.0

    payload = {
        "tank_id": TANK_ID,
        "temperature": float(temperature),
        "ph": float(ph),
        "dissolved_oxygen": float(dissolved_oxygen),
        "tds_ppm": float(tds_ppm),
        "turbidity": 0.0,  # legacy backend field; never place TDS here
        "water_level": float(water_level),
    }

    try:
        res = requests.post(
            f"{BASE_URL}/api/sensor/",
            json=payload,
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        print(
            f"[SENSOR] 전송 완료 | TDS={tds_ppm:.1f}ppm | "
            f"수질점수={data.get('water_quality_score')} | "
            f"자동제어={data.get('auto_actions')}"
        )
        return data
    except requests.exceptions.Timeout:
        print("[SENSOR] 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[SENSOR] 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[SENSOR] HTTP 오류: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"[SENSOR] 오류: {e}")
    return None


if __name__ == "__main__":
    print(send_sensor(22.5, 7.2, 6.8, water_level=100.0, tds_ppm=340.0))
