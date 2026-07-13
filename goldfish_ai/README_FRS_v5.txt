Goldfish AI FRS Integrated Patch v5

기준:
- v4 안정본(run.py/sensor_reader.py/server_tx.py/demo_pipeline.py)의 센서/서버/종료 구조 유지
- 새 FRS 설계 파일을 선별 이식

적용 파일:
- config.yaml
- run.py
- scripts/demo_pipeline.py
- scripts/sensor_reader.py
- scripts/server_tx.py
- scripts/feeding_events.py
- scripts/analytics/__init__.py
- scripts/analytics/feeding_response.py
- scripts/analytics/amount_advisor.py

FRS 반영 내용:
1. feeding.times / feeding.tolerance_sec 기반 예약 급이 감지
2. FeedingEventLogger + ScheduledFeedingWatcher 연동
3. 매 프레임 유효 트랙/유효 속도 features만 FRS 버퍼에 push
4. pre 60초 / post 180초 기준 FRS 계산
5. 한 급이 이벤트당 compute 1회만 수행
6. frs_history.csv 중복 저장 방지
7. 최근 3회 평균 기반 급이량 추천 출력
8. BehaviorBridge/send_behavior의 frs_score에 최신 FRS 점수 반영
9. 재시작 시 당일 급이 횟수와 이미 발동한 scheduled 슬롯 복원

주의:
- 급이 이벤트는 Pi 시스템 시간 기준입니다. timedatectl에서 Asia/Seoul인지 확인하세요.
- FRS 계산을 보려면 급이 시각 전부터 run.py가 실행되어 pre window 데이터가 쌓여 있어야 합니다.
- post 180초가 지난 뒤 data/frs_history.csv가 생성/갱신됩니다.

적용 예:
cd ~/aquarium-helper/goldfish_ai
cp config.yaml ./config.yaml
cp run.py ./run.py
cp scripts/demo_pipeline.py ./scripts/demo_pipeline.py
cp scripts/sensor_reader.py ./scripts/sensor_reader.py
cp scripts/server_tx.py ./scripts/server_tx.py
cp scripts/feeding_events.py ./scripts/feeding_events.py
mkdir -p scripts/analytics
cp scripts/analytics/__init__.py ./scripts/analytics/__init__.py
cp scripts/analytics/feeding_response.py ./scripts/analytics/feeding_response.py
cp scripts/analytics/amount_advisor.py ./scripts/analytics/amount_advisor.py

테스트:
python3 -m py_compile run.py scripts/demo_pipeline.py scripts/feeding_events.py scripts/analytics/feeding_response.py scripts/analytics/amount_advisor.py
python3 run.py

확인:
tail -f data/feeding_events.csv
tail -f data/frs_history.csv
