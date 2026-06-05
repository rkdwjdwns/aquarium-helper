#include <Arduino.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>

#define CALIBRATION_MODE false

// ── 핀 정의 (J1 왼쪽 핀만 사용) ──────────────
#define ONE_WIRE_BUS  4   // 수온  J1-4
#define PIN_PH        5   // pH    J1-5
#define PIN_TURBIDITY 6   // TDS   J1-6
#define PIN_DO        7   // DO    J1-7


#define SEND_INTERVAL_MS 10000


// ── [★ 추가] 하드웨어 특성 상수 정의 ──────────
#define ADC_RES 4095.0f
#define ESP32_VREF 3300.0f  // ESP32 전원 전압 (3300mV)

// [★ 중요] 사용자의 전압 분배 저항 비율 (예: 5V 출력을 3.3V로 낮출 때 원래 전압 복원용 배수)
// 만약 10k / 20k 저항을 썼거나 전압 분배비가 다르면 이 배수를 정확히 수정하세요.
const float VOLTAGE_DIVIDER_RATIO = 1.5151f; 

OneWire           oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensor(&oneWire);

// ── pH 교정 ────────────────────────────────────
struct { int raw_7=1450; int raw_4=1050; } phCalib;

float calcPH(int raw) {
    float slope = (4.0f - 7.0f) / (float)(phCalib.raw_4 - phCalib.raw_7);
    return constrain(7.0f + slope * (raw - phCalib.raw_7), 0.0f, 14.0f);
}

// ── DO 교정 ────────────────────────────────────
struct { int raw_sat=631; } doCalib;

float getSatDO(float t) {
    if (t <= 20) return 9.08f;
    if (t <= 22) return 8.73f;
    if (t <= 24) return 8.40f;
    if (t <= 26) return 8.09f;
    return 7.83f;
}

// [★ 수정] 전압 분배 회로를 감안하여 전압(mV) 단위로 변환 후 DO 계산
float calcDO(int raw, float temp) {
    if (doCalib.raw_sat <= 0) return 0.0f;

    // 1. ESP32 핀에 인가된 전압(mV) 계산
    float pinVoltage = ((float)raw / ADC_RES) * ESP32_VREF;
    // 2. 분배 회로 이전의 원래 DO 센서 출력 전압(mV) 복원
    float originalSensorVoltage = pinVoltage * VOLTAGE_DIVIDER_RATIO;
    
    // 3. 원래 전압과 대기 포화 전압(raw_sat)을 비교하여 DO 계산
    float doValue = (originalSensorVoltage / (float)doCalib.raw_sat) * getSatDO(temp);
    return constrain(doValue, 0.0f, 20.0f);
}

// ── TDS 교정 및 표준 정밀 수식 (3.3V 직결 전용) ─────────────────────
struct { float v_ref=3.3f; float ppm_max=1000.0f; } tdsCalib;

float calcTDS(int raw, float temp) {
    // 1. ESP32 핀에 걸린 실제 전압(V 단위)을 바로 계산 (분배 회로 배수 제거)
    float originalSensorVoltage = ((float)raw / ADC_RES) * (ESP32_VREF / 1000.0f); 

    // 2. 수온에 따른 전도도 변화 온도 보정 (25도 기준)
    float tempCoeff = 1.0f + 0.02f * (temp - 25.0f);
    float compensationVoltage = originalSensorVoltage / tempCoeff;

    // 3. 아날로그 TDS 센서 표준 3차 다항식 데이터 매핑 공식
    float tdsValue = (133.42f * compensationVoltage * compensationVoltage * compensationVoltage) 
                   - (255.86f * compensationVoltage * compensationVoltage) 
                   + (857.39f * compensationVoltage);
                   
    return constrain(tdsValue, 0.0f, 1000.0f);
}

// ── 이동 평균 필터 ─────────────────────────────
class MovingAvg {
    int buf[5]={0}; int idx=0; int sum=0; int cnt=0;
public:
    int update(int v) {
        sum -= buf[idx]; buf[idx]=v; sum+=v;
        idx=(idx+1)%5; if(cnt<5)cnt++;
        return sum/cnt;
    }
};

MovingAvg phF, doF, turbF;

// ── 수온 읽기 ──────────────────────────────────
float readTemperature() {
    tempSensor.requestTemperatures();
    float t = tempSensor.getTempCByIndex(0);
    return (t == DEVICE_DISCONNECTED_C) ? 22.0f : t;
}

// ── UART 전송 ──────────────────────────────────
void sendSensorData() {
    float temp  = readTemperature();
    float ph    = calcPH(phF.update(analogRead(PIN_PH)));
    float doVal = calcDO(doF.update(analogRead(PIN_DO)), temp);
    float tds   = calcTDS(turbF.update(analogRead(PIN_TURBIDITY)), temp);

    JsonDocument doc;
    doc["temp"] = temp;
    doc["ph"]   = ph;
    doc["do"]   = doVal;
    doc["turb"] = tds;
    doc["level"] = 100.0;  // 수위 센서 없으므로 기본값
    serializeJson(doc, Serial);
    Serial.println();
}

// ── [★ 수정] 교정 모드 시 실제 전압(mV)도 표기하도록 개선 ─────────────────
void printCalibData() {
    tempSensor.requestTemperatures();
    float t = tempSensor.getTempCByIndex(0);
    
    int doRaw = analogRead(PIN_DO);
    float doPinV = ((float)doRaw / ADC_RES) * ESP32_VREF;
    float doSensorV = doPinV * VOLTAGE_DIVIDER_RATIO;

    Serial.println("=== 교정 모드 ===");
    Serial.print("수온       : "); Serial.println(t);
    Serial.print("pH ADC     : "); Serial.println(analogRead(PIN_PH));
    Serial.print("DO ADC     : "); Serial.print(doRaw); 
    Serial.print(" (복원 전압: "); Serial.print(doSensorV, 1); Serial.println(" mV)");
    Serial.print("TDS ADC    : "); Serial.println(analogRead(PIN_TURBIDITY));
    Serial.println("=================");
}

unsigned long lastSend = 0;

void setup() {
    Serial.begin(115200);
    tempSensor.begin();
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    // 이동 평균 필터 초기화
    for (int i = 0; i < 5; i++) {
        phF.update(analogRead(PIN_PH));
        doF.update(analogRead(PIN_DO));
        turbF.update(analogRead(PIN_TURBIDITY));
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
