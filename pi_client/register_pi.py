"""
register_pi.py
Pi 시작 시 자신의 IP를 서버에 자동 등록

main.py에서 시작할 때 한 번 호출하면
카메라 페이지에서 IP 입력 없이 자동 연결됩니다.
"""

import socket
import requests
from config import BASE_URL, HEADERS, TANK_ID

STREAM_PORT = 8080


def get_local_ip() -> str:
    """현재 Pi의 로컬 IP 주소를 가져옵니다."""
    try:
        # 외부 연결 시도로 실제 사용 중인 네트워크 인터페이스 IP 확인
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def register_pi_ip(stream_port: int = STREAM_PORT) -> bool:
    """
    Pi의 IP를 서버에 등록합니다.

    Returns:
        True: 등록 성공, False: 실패
    """
    local_ip = get_local_ip()

    try:
        res = requests.post(
            f"{BASE_URL}/api/register-pi/",
            json={
                "tank_id":        TANK_ID,
                "pi_ip":          local_ip,
                "pi_stream_port": stream_port,
            },
            headers=HEADERS,
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        print(f"[PI] IP 등록 완료: {local_ip}:{stream_port}")
        print(f"[PI] 스트림 URL: {data.get('stream_url', '')}")
        return True

    except requests.exceptions.ConnectionError:
        print(f"[PI] IP 등록 실패: 서버 연결 불가 (나중에 재시도)")
    except requests.exceptions.HTTPError as e:
        print(f"[PI] IP 등록 실패: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"[PI] IP 등록 실패: {e}")

    return False


# ── 단독 실행 테스트 ──────────────────────────────
if __name__ == "__main__":
    print(f"[PI] 로컬 IP: {get_local_ip()}")
    register_pi_ip()
