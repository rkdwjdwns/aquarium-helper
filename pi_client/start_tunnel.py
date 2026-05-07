"""
start_tunnel.py
cloudflared 터널 시작 + URL 자동 서버 등록

Pi 부팅 시 실행하면:
1. cloudflared 터널 시작
2. trycloudflare.com URL 파싱
3. 서버 DB에 자동 등록
4. camera 페이지에서 바로 사용 가능
"""

import subprocess
import requests
import re
import sys
import time
from config import BASE_URL, HEADERS, TANK_ID

def start_tunnel():
    print("[TUNNEL] cloudflared 터널 시작 중...")

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:8080"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    tunnel_url = None

    for line in proc.stdout:
        print(f"[CLOUDFLARED] {line.rstrip()}")

        # URL 파싱
        match = re.search(r'https://[\w\-]+\.trycloudflare\.com', line)
        if match:
            tunnel_url = match.group(0)
            print(f"[TUNNEL] URL 감지: {tunnel_url}")

            # 서버에 등록
            try:
                res = requests.post(
                    f"{BASE_URL}/api/register-camera-url/",
                    json={"tank_id": TANK_ID, "camera_url": tunnel_url},
                    headers=HEADERS,
                    timeout=10,
                )
                if res.status_code == 200:
                    print(f"[TUNNEL] ✅ 서버 등록 완료: {tunnel_url}")
                else:
                    print(f"[TUNNEL] ⚠️ 서버 등록 실패: {res.status_code}")
            except Exception as e:
                print(f"[TUNNEL] 등록 오류: {e}")

    proc.wait()


if __name__ == "__main__":
    start_tunnel()
