"""
기존 apps/monitoring/api_views.py 전체 파일을 교체하지 않고,
API Key 미설정 시 인증을 통과시키는 fail-open 두 군데만 안전하게 수정합니다.

저장소 루트에서:
    python tools/apply_api_security_patch.py
"""

from pathlib import Path

path = Path("apps/monitoring/api_views.py")
if not path.exists():
    raise SystemExit(
        "apps/monitoring/api_views.py를 찾을 수 없습니다. 저장소 루트에서 실행하세요."
    )

text = path.read_text(encoding="utf-8")

old_decorator = """        server_key = os.getenv('PI_API_KEY', '')
        if not server_key:
            logger.warning("PI_API_KEY 환경변수가 설정되어 있지 않습니다.")
            return func(request, *args, **kwargs)
        client_key = request.headers.get('X-API-KEY', '')
"""

new_decorator = """        server_key = os.getenv('PI_API_KEY', '')
        if not server_key:
            logger.error("PI_API_KEY 환경변수가 설정되어 있지 않습니다.")
            return _error(
                "서버 API Key가 설정되지 않아 요청을 처리할 수 없습니다.",
                status=503,
            )
        client_key = request.headers.get('X-API-KEY', '')
"""

old_check = """    server_key = os.getenv('PI_API_KEY', '')
    if not server_key:
        return True
    return request.headers.get('X-API-KEY', '') == server_key
"""

new_check = """    server_key = os.getenv('PI_API_KEY', '')
    if not server_key:
        logger.error("PI_API_KEY 환경변수가 설정되어 있지 않습니다.")
        return False
    return request.headers.get('X-API-KEY', '') == server_key
"""

for label, old, new in [
    ("api_key_required", old_decorator, new_decorator),
    ("_check_api_key", old_check, new_check),
]:
    if old not in text:
        raise SystemExit(
            f"{label} 원본 코드가 예상과 달라 패치를 중단했습니다. "
            "파일이 이미 수정되었는지 확인하세요."
        )
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("완료: apps/monitoring/api_views.py API Key fail-open 제거")
