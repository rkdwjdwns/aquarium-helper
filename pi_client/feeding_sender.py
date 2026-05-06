"""
feeding_sender.py
급이 이벤트 + FRS(급이 반응 점수) → 서버 전송
POST /api/feeding/
"""

import requests
from config import BASE_URL, HEADERS, TANK_ID


def send_feeding(trigger: str, amount_g: float, growth_stage: str,
                 turbidity_before: float, turbidity_after: float,
                 is_overfeeding: bool,
                 rt_seconds: float, ar_ratio: float, sf_ratio: float,
                 frs_score: int,
                 activity_before: float, activity_during: float, activity_after: float) -> dict | None:
    """
    급이 이벤트와 FRS 분석 결과를 서버로 전송합니다.

    Args:
        trigger          : 급이 트리거 ('AUTO' | 'MANUAL')
        amount_g         : 급이량 (g)
        growth_stage     : 성장 단계 ('FRY' | 'YOUNG' | 'ADULT')
        turbidity_before : 급이 전 탁도 (NTU)
        turbidity_after  : 급이 후 탁도 (NTU)
        is_overfeeding   : 과급여 여부
        rt_seconds       : 반응 시간 (초)
        ar_ratio         : 활동 증가율
        sf_ratio         : 수면 접근 빈도
        frs_score        : 급이 반응 점수 (0~100)
        activity_before  : 급이 전 활동량
        activity_during  : 급이 중 활동량
        activity_after   : 급이 후 활동량
    """
    payload = {
        "tank_id":          TANK_ID,
        "trigger":          trigger,
        "amount_g":         amount_g,
        "growth_stage":     growth_stage,
        "turbidity_before": turbidity_before,
        "turbidity_after":  turbidity_after,
        "is_overfeeding":   is_overfeeding,
        "rt_seconds":       rt_seconds,
        "ar_ratio":         ar_ratio,
        "sf_ratio":         sf_ratio,
        "frs_score":        frs_score,
        "activity_before":  activity_before,
        "activity_during":  activity_during,
        "activity_after":   activity_after,
    }

    try:
        res = requests.post(
            f"{BASE_URL}/api/feeding/",
            json=payload,
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        flag = " ⚠️ 과급여" if is_overfeeding else ""
        print(f"[FEEDING] 전송 완료 | {amount_g}g {trigger} | FRS={frs_score}{flag}")
        return data

    except requests.exceptions.Timeout:
        print("[FEEDING] 오류: 서버 응답 시간 초과")
    except requests.exceptions.ConnectionError:
        print("[FEEDING] 오류: 서버 연결 실패")
    except requests.exceptions.HTTPError as e:
        print(f"[FEEDING] HTTP 오류: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"[FEEDING] 알 수 없는 오류: {e}")

    return None


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    result = send_feeding(
        trigger="AUTO",
        amount_g=0.3,
        growth_stage="FRY",
        turbidity_before=10.2,
        turbidity_after=18.5,
        is_overfeeding=False,
        rt_seconds=4.2,
        ar_ratio=1.8,
        sf_ratio=0.45,
        frs_score=78,
        activity_before=12.3,
        activity_during=22.1,
        activity_after=15.4,
    )
    print(result)
