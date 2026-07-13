#!/bin/bash
# Goldfish AI systemd 설치
# run.py가 카메라 스트리밍까지 담당하므로 aquarium-camera.service는 설치하지 않는다.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 어항 시스템 자동 시작 설치 ==="

sudo cp "$SCRIPT_DIR/aquarium.service" /etc/systemd/system/aquarium.service

# 구버전 별도 카메라 서비스가 설치돼 있으면 카메라 중복 점유를 막기 위해 중지/비활성화한다.
if systemctl list-unit-files | grep -q '^aquarium-camera.service'; then
  sudo systemctl disable --now aquarium-camera.service || true
  sudo rm -f /etc/systemd/system/aquarium-camera.service
fi

sudo systemctl daemon-reload
sudo systemctl enable aquarium.service
sudo systemctl restart aquarium.service

echo ""
echo "설치 완료"
echo "상태 확인: sudo systemctl status aquarium"
echo "로그 확인: journalctl -u aquarium -f"
echo "서비스 중지: sudo systemctl stop aquarium"
