import os

BASE_URL = os.environ.get(
    "AQUARIUM_BASE_URL",
    "https://aquarium-helper.onrender.com/monitoring",
).rstrip("/")

API_KEY = os.environ.get("PI_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError(
        "PI_API_KEY 환경변수가 설정되지 않았습니다. "
        "실제 API Key를 환경변수로 설정한 뒤 실행하세요."
    )

TANK_ID = int(os.environ.get("TANK_ID", "1"))

HEADERS = {
    "Content-Type": "application/json",
    "X-API-KEY": API_KEY,
}
