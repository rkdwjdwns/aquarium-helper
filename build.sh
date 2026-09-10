#!/usr/bin/env bash
set -e

echo "=== 정적 파일 수집 ==="
python manage.py collectstatic --no-input

echo "=== DB 마이그레이션 ==="
python manage.py migrate

echo "=== 상태 진단 코드(StateCode) 초기화 ==="
python manage.py seed_state_codes

echo "=== 오래된 데이터 정리 (2주 이상) ==="
python manage.py cleanup_old_data --weeks=2 || echo "⚠️ 데이터 정리 실패 — 배포는 계속 진행합니다"

echo "=== 관리자 계정 자동 생성 ==="
python manage.py shell << 'EOF'
import os
from django.contrib.auth import get_user_model

User = get_user_model()

username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin1234')
email    = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@aquarium.com')

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"✅ 관리자 계정 생성 완료: {username}")
else:
    print(f"ℹ️ 관리자 계정 이미 존재: {username}")
EOF

echo "=== 배포 완료 ==="