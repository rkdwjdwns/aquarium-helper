"""
test_server.py
하드웨어 없이 서버 연결을 테스트하는 스크립트

실행: python test_server.py
모든 API 엔드포인트에 더미 데이터를 전송하고 결과를 출력합니다.
"""

import requests
from config import BASE_URL, HEADERS, TANK_ID


def test_health():
    print("\n[1] 헬스체크 (/api/health/)")
    print("-" * 40)
    try:
        res = requests.get(f"{BASE_URL}/api/health/", timeout=10)
        print(f"  상태코드 : {res.status_code}")
        print(f"  응답     : {res.json()}")
        return res.status_code == 200
    except requests.exceptions.ConnectionError:
        print("  ❌ 서버 연결 실패 — Render 슬립 상태일 수 있어요")
        print(f"     브라우저에서 먼저 열어보세요: {BASE_URL}/api/health/")
        return False
    except Exception as e:
        print(f"  ❌ 오류: {e}")
        return False


def test_sensor():
    print("\n[2] 센서 데이터 전송 (/api/sensor/)")
    print("-" * 40)
    payload = {
        "tank_id":          TANK_ID,
        "temperature":      22.5,
        "ph":               7.2,
        "dissolved_oxygen": 6.8,
        "turbidity":        12.3,
        "water_level":      90.0,
    }
    try:
        res = requests.post(f"{BASE_URL}/api/sensor/", json=payload, headers=HEADERS, timeout=10)
        print(f"  상태코드 : {res.status_code}")
        print(f"  응답     : {res.json()}")
        return res.status_code in (200, 201)
    except Exception as e:
        print(f"  ❌ 오류: {e}")
        return False


def test_behavior():
    print("\n[3] 행동 분석 전송 (/api/behavior/)")
    print("-" * 40)
    payload = {
        "tank_id":        TANK_ID,
        "fish_count":     3,
        "overlap_frames": 1,
        "activity_level": 14.5,
        "abr_score":      0.04,
        "dominant_zone":  "MID",
        "zone_top_ratio": 0.1,
        "zone_mid_ratio": 0.7,
        "zone_bot_ratio": 0.2,
        "size_index":     7.8,
        "feeding_score":  0,
        "status":         "GOOD",
        "is_anomaly":     False,
        "note":           "테스트",
    }
    try:
        res = requests.post(f"{BASE_URL}/api/behavior/", json=payload, headers=HEADERS, timeout=10)
        print(f"  상태코드 : {res.status_code}")
        print(f"  응답     : {res.json()}")
        return res.status_code in (200, 201)
    except Exception as e:
        print(f"  ❌ 오류: {e}")
        return False


def test_commands():
    print(f"\n[4] 제어 명령 조회 (/api/commands/{TANK_ID}/)")
    print("-" * 40)
    try:
        res = requests.get(f"{BASE_URL}/api/commands/{TANK_ID}/", headers=HEADERS, timeout=10)
        print(f"  상태코드 : {res.status_code}")
        data = res.json()
        devices = data.get("devices", [])
        for d in devices:
            state = "ON " if d.get("is_on") else "OFF"
            mode  = "자동" if d.get("is_auto") else "수동"
            print(f"  장치: {d.get('type'):<10} {state}  ({mode})")
        return res.status_code == 200
    except Exception as e:
        print(f"  ❌ 오류: {e}")
        return False


def test_growth():
    print("\n[5] 성장 기록 전송 (/api/growth/)")
    print("-" * 40)
    payload = {
        "tank_id":            TANK_ID,
        "fish_id":            1,
        "size_index":         7.8,
        "estimated_length":   2.1,
        "estimated_weight":   0.052,
        "growth_rate":        0.05,
        "growth_stage":       "FRY",
        "recommended_feed_g": 0.01,
    }
    try:
        res = requests.post(f"{BASE_URL}/api/growth/", json=payload, headers=HEADERS, timeout=10)
        print(f"  상태코드 : {res.status_code}")
        print(f"  응답     : {res.json()}")
        return res.status_code in (200, 201)
    except Exception as e:
        print(f"  ❌ 오류: {e}")
        return False


# ──────────────────────────────────────────────
# 전체 테스트 실행
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 40)
    print(" 어항 시스템 서버 연결 테스트")
    print(f" {BASE_URL}")
    print("=" * 40)

    results = {
        "헬스체크":       test_health(),
        "센서 전송":      test_sensor(),
        "행동 분석 전송": test_behavior(),
        "제어 명령 조회": test_commands(),
        "성장 기록 전송": test_growth(),
    }

    print("\n" + "=" * 40)
    print(" 결과 요약")
    print("=" * 40)
    all_pass = True
    for name, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("  모든 테스트 통과 — 하드웨어 연결 준비 완료!")
    else:
        print("  일부 실패 — config.py의 API_KEY와 TANK_ID를 확인하세요.")
    print("=" * 40)
