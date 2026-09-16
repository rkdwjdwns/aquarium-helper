"""
growth_sender.py
개체별 성장 기록 → 서버 전송
POST /api/growth/
성장 추정 공식: W = 0.01049 × TL^3.14
"""

import requests
from config import BASE_URL, HEADERS, TANK_ID


def estimate_weight(length_cm: float) -> float:
    """체장(cm)으로 체중(g) 추정 — W = 0.01049 × TL^3.14"""
    return round(0.01049 * (length_cm ** 3.14), 4)


def send_growth(fish_id: int, size_index: float, estimated_length: float,
                growth_rate: float, growth_stage: str,
                recommended_feed_g: float,
                estimated_weight: float | None = None) -> dict | None:
    """
    개체별 성장 기록을 서버로 전송합니다.

    Args:
        fish_id            : ByteTrack 개체 ID
        size_index         : 크기 지수 (bbox면적/프레임면적×100)
        estimated_length   : 추정 체장 (cm)
        growth_rate        : 성장률 (cm/day)
        growth_stage       : 성장 단계 ('FRY' | 'YOUNG' | 'ADULT')
        recommended_feed_g : 권장 1회 급이량 (g)
        estimated_weight   : 추정 체중 (g), None이면 공식으로 자동 계산
    """
    weight = estimated_weight if estimated_weight is not None else estimate_weight(estimated_length)

    payload = {
        "tank_id":           TANK_ID,
        "fish_id":           fish_id,
        "size_index":        size_index,
        "estimated_length":  estimated_length,
        "estimated_weight":  weight,
        "growth_rate":       growth_rate,
        "growth_stage":      growth_stage,
        "recommended_feed_g": recommended_feed_g,
    }

    try:
        res = requests.post(
            f"{BASE_URL}/api/growth/",
            json=payload,
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        print(f"[GROWTH] 전송 완료 | ID={fish_id} | {estimated_length}cm / {weight}g | 권장급이={recommended_feed_g}g")
        return data

    except requests.exceptions.Timeout:
        print("[GROWTH] 오류: 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[GROWTH] 오류: 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[GROWTH] HTTP 오류: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"[GROWTH] 알 수 없는 오류: {e}")

    return None


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    result = send_growth(
        fish_id=1,
        size_index=7.8,
        estimated_length=2.1,
        growth_rate=0.05,
        growth_stage="FRY",
        recommended_feed_g=0.01,
    )
    print(result)
