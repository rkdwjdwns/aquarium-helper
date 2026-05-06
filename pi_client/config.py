import os

BASE_URL = "https://aquarium-helper.onrender.com/monitoring"
API_KEY  = os.environ.get("PI_API_KEY", "aquarium-pi-secret-2025")
TANK_ID  = 1

HEADERS = {
    "Content-Type": "application/json",
    "X-API-KEY": API_KEY,
}
