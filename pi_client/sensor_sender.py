"""
sensor_sender.py
ESP32 → Pi → 서버  수질 센서 데이터 전송
POST /api/sensor/
"""

import requests
from config import BASE_URL, HEADERS, TANK_ID


def send_sensor(temperature: float, ph: float, dissolved_oxygen: float,
                turbidity: float, water_level: float = 100.0) -> dict | None:
    """
    수질 센서 데이터를 서버로 전송합니다.

    Args:
        temperature      : 수온 (°C)
        ph               : pH
        dissolved_oxygen : 용존산소 (mg/L)
        turbidity        : 탁도 (NTU)
        water_level      : 수위 (%, 기본값 100)

    Returns:
        서버 응답 dict 또는 None (실패 시)
        {
            "status": "ok",
            "reading_id": 42,
            "water_quality_score": 85,
            "auto_actions": ["HEATER:OFF"],
            "timestamp": "2025-05-01T12:00:00"
        }
    """
    payload = {
        "tank_id":          TANK_ID,
        "temperature":      temperature,
        "ph":               ph,
        "dissolved_oxygen": dissolved_oxygen,
        "turbidity":        turbidity,
        "water_level":      water_level,
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
        print(f"[SENSOR] 전송 완료 | 수질점수={data.get('water_quality_score')} | 자동제어={data.get('auto_actions')}")
        return data

    except requests.exceptions.Timeout:
        print("[SENSOR] 오류: 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[SENSOR] 오류: 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[SENSOR] HTTP 오류: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"[SENSOR] 알 수 없는 오류: {e}")

    return None


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    result = send_sensor(
        temperature=22.5,
        ph=7.2,
        dissolved_oxygen=6.8,
        turbidity=12.3,
        water_level=90.0,
    )
    print(result)
