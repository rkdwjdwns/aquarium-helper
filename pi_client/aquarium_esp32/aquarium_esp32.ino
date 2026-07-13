/*
 * aquarium_esp32.ino
 * ESP32-S3 펌웨어 — 수질 센서 수집 + 교정 + UART 전송
 *
 * 센서 핀:
 *   DS18B20 (수온)   → GPIO 4  (OneWire)
 *   pH 센서          → GPIO 34 (ADC)
 *   DO 센서          → GPIO 35 (ADC)
 *   탁도 센서         → GPIO 32 (ADC)
 *   수위 센서         → GPIO 33 (ADC)
 *
 * 교정 방법:
 *   1. CALIBRATION_MODE true 로 변경 후 업로드
 *   2. 시리얼 모니터에서 raw ADC 값 확인
 *   3. 아래 교정 구조체에 측정값 입력
 *   4. CALIBRATION_MODE false 로 변경 후 재업로드
 */

#include <Arduino.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>

// ── 교정 모드 (true = raw ADC 값 출력) ────────
#define CALIBRATION_MODE false

// ── 핀 정의 ───────────────────────────────────
#define ONE_WIRE_BUS  4
#define PIN_PH        34
#define PIN_DO        35
#define PIN_TURBIDITY 32
#define PIN_WATER_LVL 33

#define SEND_INTERVAL_MS 10000

OneWire           oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensor(&oneWire);


// ── pH 교정 (pH 4.0 / pH 7.0 표준 완충액 사용) ─
struct { int raw_7=2048; int raw_4=1638; } phCalib;

float calcPH(int raw) {
    float slope = (4.0f - 7.0f) / (float)(phCalib.raw_4 - phCalib.raw_7);
    return constrain(7.0f + slope * (raw - phCalib.raw_7), 0.0f, 14.0f);
}


// ── DO 교정 (공기 포화 상태 기준) ──────────────
struct { int raw_sat=3000; } doCalib;

float getSatDO(float t) {
    if (t <= 20) return 9.08f;
    if (t <= 22) return 8.73f;
    if (t <= 24) return 8.40f;
    if (t <= 26) return 8.09f;
    return 7.83f;
}

float calcDO(int raw, float temp) {
    return constrain(((float)raw / doCalib.raw_sat) * getSatDO(temp), 0.0f, 20.0f);
}


// ── 탁도 교정 (증류수=0NTU, 500NTU 표준액 사용) ─
struct { int raw_clear=3800; int raw_500=1200; } turbCalib;

float calcTurbidity(int raw) {
    float ratio = (float)(turbCalib.raw_clear - raw) /
                  (float)(turbCalib.raw_clear - turbCalib.raw_500);
    return constrain(ratio * 500.0f, 0.0f, 500.0f);
}


// ── 수위 교정 (빈 어항=0%, 만수=100%) ──────────
struct { int raw_empty=500; int raw_full=3500; } levelCalib;

float calcWaterLevel(int raw) {
    return constrain(
        (float)(raw - levelCalib.raw_empty) /
        (float)(levelCalib.raw_full - levelCalib.raw_empty) * 100.0f,
        0.0f, 100.0f
    );
}


// ── 이동 평균 필터 (노이즈 제거) ───────────────
class MovingAvg {
    int buf[5]={0}; int idx=0; int sum=0; int cnt=0;
public:
    int update(int v) {
        sum -= buf[idx]; buf[idx]=v; sum+=v;
        idx=(idx+1)%5; if(cnt<5)cnt++;
        return sum/cnt;
    }
};

MovingAvg phF, doF, turbF, levelF;


// ── 센서 읽기 ─────────────────────────────────
float readTemperature() {
    tempSensor.requestTemperatures();
    float t = tempSensor.getTempCByIndex(0);
    return (t == DEVICE_DISCONNECTED_C) ? 22.0f : t;
}


// ── UART 전송 ─────────────────────────────────
void sendSensorData() {
    float temp  = readTemperature();
    float ph    = calcPH(phF.update(analogRead(PIN_PH)));
    float doVal = calcDO(doF.update(analogRead(PIN_DO)), temp);
    float turb  = calcTurbidity(turbF.update(analogRead(PIN_TURBIDITY)));
    float level = calcWaterLevel(levelF.update(analogRead(PIN_WATER_LVL)));

    StaticJsonDocument<256> doc;
    doc["temp"]  = temp;
    doc["ph"]    = ph;
    doc["do"]    = doVal;
    doc["turb"]  = turb;
    doc["level"] = level;
    serializeJson(doc, Serial);
    Serial.println();
}


// ── 교정 모드: raw ADC 값 출력 ─────────────────
void printCalibData() {
    tempSensor.requestTemperatures();
    float t = tempSensor.getTempCByIndex(0);
    Serial.println("=== 교정 모드 (raw ADC 값) ===");
    Serial.print("수온   : "); Serial.print(t);  Serial.println(" °C");
    Serial.print("pH ADC : "); Serial.println(analogRead(PIN_PH));
    Serial.print("DO ADC : "); Serial.println(analogRead(PIN_DO));
    Serial.print("탁도 ADC: "); Serial.println(analogRead(PIN_TURBIDITY));
    Serial.print("수위 ADC: "); Serial.println(analogRead(PIN_WATER_LVL));
    Serial.println("==============================");
}


unsigned long lastSend = 0;

void setup() {
    Serial.begin(115200);
    tempSensor.begin();
    analogReadResolution(12);
    for (int i = 0; i < 5; i++) {
        phF.update(analogRead(PIN_PH));
        doF.update(analogRead(PIN_DO));
        turbF.update(analogRead(PIN_TURBIDITY));
        levelF.update(analogRead(PIN_WATER_LVL));
        delay(10);
    }
    Serial.println("{\"status\":\"ESP32 ready\"}");
}

void loop() {
    unsigned long now = millis();
#if CALIBRATION_MODE
    if (now - lastSend >= 2000) { printCalibData(); lastSend = now; }
#else
    if (now - lastSend >= SEND_INTERVAL_MS) { sendSensorData(); lastSend = now; }
#endif
}
