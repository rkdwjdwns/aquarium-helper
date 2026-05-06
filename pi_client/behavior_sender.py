"""
behavior_sender.py
YOLOv11 + ByteTrack 분석 결과 → 서버 전송
POST /api/behavior/
"""

import requests
from config import BASE_URL, HEADERS, TANK_ID


def send_behavior(fish_count: int, overlap_frames: int, activity_level: float,
                  abr_score: float, dominant_zone: str,
                  zone_top_ratio: float, zone_mid_ratio: float, zone_bot_ratio: float,
                  size_index: float, feeding_score: int,
                  status: str, is_anomaly: bool, note: str = "") -> dict | None:
    """
    YOLOv11 + ByteTrack 행동 분석 결과를 서버로 전송합니다.

    Args:
        fish_count      : 탐지된 개체 수
        overlap_frames  : 겹침 프레임 수
        activity_level  : 활동량 (px/s)
        abr_score       : 이상 행동율 (0~1)
        dominant_zone   : 주 체류 구역 ('TOP' | 'MID' | 'BOT')
        zone_top_ratio  : 상층 체류 비율 (0~1)
        zone_mid_ratio  : 중층 체류 비율 (0~1)
        zone_bot_ratio  : 하층 체류 비율 (0~1)
        size_index      : 크기 지수 (%)
        feeding_score   : 급이 반응 점수 (0~100)
        status          : 상태 ('EXCELLENT'|'GOOD'|'NORMAL'|'WARNING'|'POOR')
        is_anomaly      : 이상 행동 감지 여부
        note            : AI 권장사항 (선택)
    """
    payload = {
        "tank_id":        TANK_ID,
        "fish_count":     fish_count,
        "overlap_frames": overlap_frames,
        "activity_level": activity_level,
        "abr_score":      abr_score,
        "dominant_zone":  dominant_zone,
        "zone_top_ratio": zone_top_ratio,
        "zone_mid_ratio": zone_mid_ratio,
        "zone_bot_ratio": zone_bot_ratio,
        "size_index":     size_index,
        "feeding_score":  feeding_score,
        "status":         status,
        "is_anomaly":     is_anomaly,
        "note":           note,
    }

    try:
        res = requests.post(
            f"{BASE_URL}/api/behavior/",
            json=payload,
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        flag = " ⚠️ 이상감지" if is_anomaly else ""
        print(f"[BEHAVIOR] 전송 완료 | 개체수={fish_count} | 활동량={activity_level:.1f} | 상태={status}{flag}")
        return data

    except requests.exceptions.Timeout:
        print("[BEHAVIOR] 오류: 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[BEHAVIOR] 오류: 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[BEHAVIOR] HTTP 오류: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"[BEHAVIOR] 알 수 없는 오류: {e}")

    return None


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    result = send_behavior(
        fish_count=3,
        overlap_frames=2,
        activity_level=14.5,
        abr_score=0.05,
        dominant_zone="MID",
        zone_top_ratio=0.1,
        zone_mid_ratio=0.6,
        zone_bot_ratio=0.3,
        size_index=7.8,
        feeding_score=82,
        status="GOOD",
        is_anomaly=False,
        note="",
    )
    print(result)
