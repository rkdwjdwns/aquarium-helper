"""
start_tunnel.py
cloudflared 터널 시작 + URL 자동 서버 등록 + 자동 재시작

Pi 부팅 시 실행하면:
1. cloudflared 터널 시작
2. trycloudflare.com URL 파싱
3. 서버 DB에 자동 등록
4. 터널 끊기면 자동 재시작
"""

import subprocess
import requests
import re
import time
from config import BASE_URL, HEADERS, TANK_ID

RETRY_DELAY  = 10   # 재시작 대기 시간 (초)
MAX_RETRIES  = 999  # 최대 재시도 횟수 (사실상 무한)


def register_url(url: str):
    """서버에 터널 URL 등록"""
    try:
        res = requests.post(
            f"{BASE_URL}/api/register-camera-url/",
            json={"tank_id": TANK_ID, "camera_url": url},
            headers=HEADERS,
            timeout=10,
        )
        if res.status_code == 200:
            print(f"[TUNNEL] ✅ 서버 등록 완료: {url}")
        else:
            print(f"[TUNNEL] ⚠️ 서버 등록 실패: {res.status_code}")
    except Exception as e:
        print(f"[TUNNEL] 등록 오류: {e}")


def run_tunnel() -> bool:
    """
    cloudflared 터널 1회 실행.
    정상 종료 시 True, 오류 종료 시 False 반환.
    """
    print("[TUNNEL] cloudflared 터널 시작 중...")

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:8080"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url_registered = False

    for line in proc.stdout:
        print(f"[CLOUDFLARED] {line.rstrip()}")

        # URL 파싱 및 등록
        match = re.search(r'https://[\w\-]+\.trycloudflare\.com', line)
        if match and not url_registered:
            tunnel_url    = match.group(0)
            url_registered = True
            print(f"[TUNNEL] URL 감지: {tunnel_url}")
            register_url(tunnel_url)

    proc.wait()
    exit_code = proc.returncode
    print(f"[TUNNEL] 프로세스 종료 (exit code: {exit_code})")
    return exit_code == 0


def start_tunnel():
    """터널 실행 + 끊기면 자동 재시작"""
    attempt = 0

    while attempt < MAX_RETRIES:
        attempt += 1
        print(f"[TUNNEL] 시도 #{attempt}")

        run_tunnel()

        print(f"[TUNNEL] {RETRY_DELAY}초 후 재시작...")
        time.sleep(RETRY_DELAY)

    print("[TUNNEL] 최대 재시도 횟수 초과. 종료합니다.")


if __name__ == "__main__":
    start_tunnel()