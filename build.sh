#!/usr/bin/env bash
set -e

echo "=== 정적 파일 수집 ==="
python manage.py collectstatic --no-input

echo "=== DB 마이그레이션 ==="
python manage.py migrate

echo "=== 상태 진단 코드(StateCode) 초기화 ==="
python manage.py seed_state_codes

# 수집된 연구/분석 데이터를 배포 시 자동 삭제하지 않는다.
# cleanup_old_data는 필요한 경우 관리자가 명시적으로 실행한다.

echo "=== 관리자 계정 확인 ==="
python manage.py shell << 'EOF'
import os
from django.contrib.auth import get_user_model

User = get_user_model()

username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL')

if not all([username, password, email]):
    print("ℹ️ 관리자 환경변수가 모두 설정되지 않아 자동 생성을 건너뜁니다.")
elif not User.objects.filter(username=username).exists():
    User.objects.create_superuser(
        username=username,
        email=email,
        password=password,
    )
    print(f"✅ 관리자 계정 생성 완료: {username}")
else:
    print(f"ℹ️ 관리자 계정 이미 존재: {username}")
EOF

echo "=== 배포 완료 ==="
