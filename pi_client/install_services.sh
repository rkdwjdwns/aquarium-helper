#!/bin/bash
# install_services.sh
# Pi에서 한 번만 실행하면 부팅 시 자동 시작 등록
#
# 실행 방법:
#   chmod +x install_services.sh
#   sudo ./install_services.sh

set -e

echo "=== 어항 시스템 자동 시작 설치 ==="

# 서비스 파일 복사
sudo cp aquarium.service        /etc/systemd/system/
sudo cp aquarium-camera.service /etc/systemd/system/

# systemd 리로드
sudo systemctl daemon-reload

# 서비스 활성화 (부팅 시 자동 시작)
sudo systemctl enable aquarium.service
sudo systemctl enable aquarium-camera.service

# 즉시 시작
sudo systemctl start aquarium.service
sudo systemctl start aquarium-camera.service

echo ""
echo "✅ 설치 완료!"
echo ""
echo "상태 확인:"
echo "  sudo systemctl status aquarium"
echo "  sudo systemctl status aquarium-camera"
echo ""
echo "로그 확인:"
echo "  journalctl -u aquarium -f"
echo "  journalctl -u aquarium-camera -f"
echo ""
echo "서비스 중지:"
echo "  sudo systemctl stop aquarium"
echo "  sudo systemctl stop aquarium-camera"
