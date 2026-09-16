"""ESP32 -> Pi -> Django sensor API sender.

현재 네 번째 물리 센서 채널은 탁도(NTU)가 아니라 TDS(ppm)이다.
TDS는 `tds_ppm` 필드로 명시적으로 전송하고, 레거시 `turbidity` 필드는
0.0으로 유지해 TDS 값을 NTU 기준으로 잘못 판정하지 않도록 한다.
"""

import requests
from config import BASE_URL, HEADERS, TANK_ID


def send_sensor(
    temperature: float,
    ph: float,
    dissolved_oxygen: float,
    tds_ppm: float,
    water_level: float,
) -> dict | None:
    payload = {
        "tank_id": TANK_ID,
        "temperature": float(temperature),
        "ph": float(ph),
        "dissolved_oxygen": float(dissolved_oxygen),
        "tds_ppm": float(tds_ppm),
        "turbidity": 0.0,
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
    print(
        "sensor_sender.py는 실제 센서값을 전달받아 사용하는 모듈입니다. "
        "단독 실행용 임의 센서 전송은 제거했습니다."
    )
