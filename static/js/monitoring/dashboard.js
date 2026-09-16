const APP_CONFIG = document.getElementById('dashboardConfig').dataset;
const numOrNull = v => (v === '' || v == null || v === 'None') ? null : Number(v);
const CHART_HISTORY = JSON.parse(document.getElementById('dashboardChartHistory')?.textContent || '{}');
const TANK_ID = Number(APP_CONFIG.tankId);
const CSRF = APP_CONFIG.csrf;

/* 설정 화면에서 저장한 수질 기준값 */
const SENSOR_THRESHOLDS = {
  tempMin: Number(APP_CONFIG.tempMin),
  tempMax: Number(APP_CONFIG.tempMax),
  phMin: Number(APP_CONFIG.phMin),
  phMax: Number(APP_CONFIG.phMax),
  doMin: Number(APP_CONFIG.doMin),
  tdsMax: Number(APP_CONFIG.tdsMax)
};

/* =========================
   공통 유틸
========================= */
function esc(value){
  return String(value ?? '')
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#039;');
}

function toNumber(value){
  if(value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatValue(value, digits=2){
  const n = toNumber(value);
  return n === null ? '--' : n.toFixed(digits);
}

function formatDate(value){
  if(!value) return '-';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('ko-KR');
}

/* =========================
   사이드바
========================= */
function toggleSb(){
  document.body.classList.toggle('sb-collapsed');
  const sb = document.getElementById('sidebar');
  sb.classList.toggle('collapsed');
  document.getElementById('sbToggle').textContent =
    sb.classList.contains('collapsed') ? '›' : '‹';
  document.getElementById('mainContent').style.marginLeft =
    sb.classList.contains('collapsed') ? '44px' : 'var(--sw)';
}

/* =========================
   장치 제어
========================= */
async function toggleDevice(type){
  try{
    const r = await fetch(`/monitoring/toggle-device/${TANK_ID}/`, {
      method:'POST',
      headers:{
        'Content-Type':'application/x-www-form-urlencoded',
        'X-CSRFToken':CSRF
      },
      body:'device_type=' + encodeURIComponent(type)
    });

    const d = await r.json();

    if(d.status === 'success'){
      location.reload();
      return;
    }

    alert(d.message || '장치 제어에 실패했습니다.');
  }catch(e){
    console.error('[toggleDevice]', e);
    alert('장치 제어 중 오류가 발생했습니다.');
  }
}

/* =========================
   환수
========================= */
function localDateKey(value){
  if(!value) return null;

  // YYYY-MM-DD가 포함된 서버 날짜는 시간대 변환 없이 날짜 부분을 우선 사용
  const raw=String(value).trim();
  const match=raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if(match) return `${match[1]}-${match[2]}-${match[3]}`;

  const d=new Date(value);
  if(Number.isNaN(d.getTime())) return null;

  const y=d.getFullYear();
  const m=String(d.getMonth()+1).padStart(2,'0');
  const day=String(d.getDate()).padStart(2,'0');
  return `${y}-${m}-${day}`;
}

function todayLocalDateKey(){
  const d=new Date();
  const y=d.getFullYear();
  const m=String(d.getMonth()+1).padStart(2,'0');
  const day=String(d.getDate()).padStart(2,'0');
  return `${y}-${m}-${day}`;
}

const WATER_CHANGE_STORAGE_KEY = `waterChangeChecked:${TANK_ID}`;

function isWaterChangeCheckedLocallyToday(){
  try{
    return localStorage.getItem(WATER_CHANGE_STORAGE_KEY) === todayLocalDateKey();
  }catch(e){
    return false;
  }
}

function saveWaterChangeCheckedToday(){
  try{
    localStorage.setItem(WATER_CHANGE_STORAGE_KEY, todayLocalDateKey());
  }catch(e){
    console.warn('[water-change-storage]', e);
  }
}

function clearOldWaterChangeCheck(){
  try{
    const saved=localStorage.getItem(WATER_CHANGE_STORAGE_KEY);
    if(saved && saved !== todayLocalDateKey()){
      localStorage.removeItem(WATER_CHANGE_STORAGE_KEY);
    }
  }catch(e){}
}

function setWaterChangeButtonCompleted(){
  const btn=document.getElementById('waterChangeCheckBtn');
  if(!btn) return;
  btn.classList.add('checked');
  btn.textContent='✓ 환수 체크 완료';
  btn.disabled=true;
  btn.setAttribute('aria-disabled','true');
  btn.title='오늘 환수 기록이 이미 완료되었습니다.';
}

function setWaterChangeButtonReady(){
  const btn=document.getElementById('waterChangeCheckBtn');
  if(!btn) return;
  btn.classList.remove('checked');
  btn.textContent='✓ 환수 체크 하기';
  btn.disabled=false;
  btn.removeAttribute('aria-disabled');
  btn.title='';
}

function updateWaterChangeCheckState(data){
  const lastWaterchange=
    data?.last_waterchange_date ||
    data?.lastWaterchangeDate ||
    null;

  const serverCheckedToday =
    localDateKey(lastWaterchange) === todayLocalDateKey();

  // POST 직후 대시보드 API가 아직 이전 환수일을 반환하더라도
  // 오늘 브라우저에서 성공 처리한 기록을 우선하여 완료 상태를 유지한다.
  const localCheckedToday = isWaterChangeCheckedLocallyToday();

  if(serverCheckedToday || localCheckedToday){
    if(serverCheckedToday) saveWaterChangeCheckedToday();
    setWaterChangeButtonCompleted();
  }else{
    setWaterChangeButtonReady();
  }
}

let waterChangeConfirmResolver=null;

function openWaterChangeConfirm(){
  const modal=document.getElementById('waterChangeConfirmModal');
  if(!modal) return Promise.resolve(false);

  modal.classList.add('open');
  modal.setAttribute('aria-hidden','false');

  return new Promise(resolve=>{
    waterChangeConfirmResolver=resolve;
  });
}

function closeWaterChangeConfirm(result){
  const modal=document.getElementById('waterChangeConfirmModal');
  if(modal){
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden','true');
  }

  if(waterChangeConfirmResolver){
    const resolve=waterChangeConfirmResolver;
    waterChangeConfirmResolver=null;
    resolve(Boolean(result));
  }
}

async function checkWaterChange(){
  const btn=document.getElementById('waterChangeCheckBtn');

  if(btn?.classList.contains('checked') || isWaterChangeCheckedLocallyToday()){
    setWaterChangeButtonCompleted();
    return;
  }

  const confirmed = await openWaterChangeConfirm();
  if(!confirmed) return;

  if(btn){
    btn.disabled=true;
    btn.textContent='환수 기록 중...';
  }

  let completed=false;

  try{
    const r=await fetch(`/monitoring/water-change/${TANK_ID}/`,{
      method:'POST',
      headers:{'X-CSRFToken':CSRF}
    });
    const d=await r.json();

    if(d.status==='success'){
      completed=true;
      saveWaterChangeCheckedToday();
      setWaterChangeButtonCompleted();

      // 즉시 reload하지 않는다.
      // 5초 폴링에서 서버 데이터가 갱신되더라도 localStorage와 함께 완료 상태가 유지된다.
      if(latestDashboard){
        latestDashboard.last_waterchange_date = todayLocalDateKey();
        latestDashboard.lastWaterchangeDate = todayLocalDateKey();
      }
      return;
    }

    alert(d.message||'환수일 기록에 실패했습니다.');
  }catch(e){
    console.error('[water-change-check]',e);
    alert('환수일 기록 중 오류가 발생했습니다.');
  }finally{
    // 성공했을 때는 절대로 버튼을 다시 활성화하지 않는다.
    if(!completed) setWaterChangeButtonReady();
  }
}

const waterChangeConfirmModal=document.getElementById('waterChangeConfirmModal');
if(waterChangeConfirmModal){
  waterChangeConfirmModal.addEventListener('click',e=>{
    if(e.target===waterChangeConfirmModal) closeWaterChangeConfirm(false);
  });
}

document.addEventListener('keydown',e=>{
  if(e.key==='Escape' && waterChangeConfirmModal?.classList.contains('open')){
    closeWaterChangeConfirm(false);
  }
});

/* =========================
   메인 트렌드 차트
========================= */
const C_CONFIG = {
  temp:{
    label:'수온(°C)', color:'#ef4444', min:18, max:30,
    baseLow:numOrNull(APP_CONFIG.tempMin),
    baseHigh:numOrNull(APP_CONFIG.tempMax)
  },
  ph:{
    label:'pH', color:'#3b82f6', min:5, max:9,
    baseLow:numOrNull(APP_CONFIG.phMin),
    baseHigh:numOrNull(APP_CONFIG.phMax)
  },
  do:{
    label:'DO(mg/L)', color:'#10b981', min:0, max:15,
    baseLow:numOrNull(APP_CONFIG.doMin),
    baseHigh:null
  },
  tds:{
    label:'TDS(PPM)', color:'#f59e0b', min:0, max:600,
    baseLow:null,
    baseHigh:numOrNull(APP_CONFIG.tdsMax)
  }
};

let metric = 'temp';
let history = CHART_HISTORY;
let mainHistorySignature = JSON.stringify(history || {});

/*
 * Raspberry Pi dashboard-v2 API 호환
 * raw sensor:
 *   temperature_c, ph, do_mg_l, tds_ppm, level
 * raw sensor_series:
 *   [{t, temp, ph, do, tds, quality}, ...]
 *
 * Django API가 기존 키를 반환하는 경우도 함께 지원한다.
 */
function normalizeSensor(sensor){
  if(!sensor) return null;
  return {
    temperature: sensor.temperature ?? sensor.temperature_c,
    ph: sensor.ph,
    dissolved_oxygen: sensor.dissolved_oxygen ?? sensor.do_mg_l,
    tds_ppm: sensor.tds_ppm ?? sensor.turbidity,
    water_level: sensor.water_level ?? sensor.level,
    water_quality_score: sensor.water_quality_score ?? sensor.waterQualityScore,
    measured_at: sensor.measured_at ?? sensor.created_at ?? sensor.timestamp
  };
}

function historyFromApiPayload(data){
  if(data?.history){
    const h = data.history;
    return {
      labels: Array.isArray(h.labels) ? h.labels : [],
      temp: Array.isArray(h.temp) ? h.temp : [],
      ph: Array.isArray(h.ph) ? h.ph : [],
      do: Array.isArray(h.do) ? h.do : [],
      tds: Array.isArray(h.tds) ? h.tds :
           Array.isArray(h.tds_ppm) ? h.tds_ppm :
           Array.isArray(h.turb) ? h.turb :
           Array.isArray(h.turbidity) ? h.turbidity : []
    };
  }

  if(Array.isArray(data?.sensor_series)){
    return {
      labels: data.sensor_series.map(row => row.t ?? ''),
      temp: data.sensor_series.map(row => row.temp),
      ph: data.sensor_series.map(row => row.ph),
      do: data.sensor_series.map(row => row.do),
      tds: data.sensor_series.map(row => row.tds)
    };
  }

  return {labels:[], temp:[], ph:[], do:[], tds:[]};
}

const chartEl = document.getElementById('trendChart');
const ctx = chartEl.getContext('2d');

const chart = new Chart(ctx,{
  type:'line',
  data:{
    labels:[],
    datasets:[{
      label:'',
      data:[],
      borderColor:'#ef4444',
      backgroundColor:'rgba(239,68,68,.08)',
      borderWidth:2.5,
      pointRadius:4,
      tension:.4,
      fill:true
    }]
  },
  options:{
    responsive:true,
    maintainAspectRatio:false,
    plugins:{
      legend:{display:false},
      annotation:{annotations:{}}
    },
    scales:{
      x:{grid:{display:false},ticks:{font:{size:10},color:'#94a3b8'}},
      y:{grid:{color:'rgba(0,0,0,.04)'},ticks:{font:{size:10},color:'#94a3b8'}}
    },
    animation:{duration:300}
  }
});

function setChart(m, btn){
  metric = m;

  document.querySelectorAll('.chart-tab')
    .forEach(t => t.classList.remove('active'));

  if(btn) btn.classList.add('active');

  if(!history || !history.labels) return;

  const c = C_CONFIG[m];
  const values = Array.isArray(history[m]) ? history[m] : [];

  chart.data.labels = history.labels;
  chart.data.datasets[0].data = values;
  chart.data.datasets[0].label = c.label;
  chart.data.datasets[0].borderColor = c.color;
  chart.data.datasets[0].backgroundColor = c.color + '18';
  chart.data.datasets[0].pointBackgroundColor = c.color;
  chart.options.scales.y.min = c.min;
  chart.options.scales.y.max = c.max;

  const annotations = {};

  if(c.baseLow != null){
    annotations.baseLow = {
      type:'line',
      yMin:c.baseLow,
      yMax:c.baseLow,
      borderColor:'#94a3b8',
      borderWidth:1.5,
      borderDash:[6,4],
      label:{
        display:true,
        content:`하한 ${c.baseLow}`,
        position:'start',
        backgroundColor:'rgba(148,163,184,.85)',
        color:'#fff',
        font:{size:9},
        padding:3
      }
    };
  }

  if(c.baseHigh != null){
    annotations.baseHigh = {
      type:'line',
      yMin:c.baseHigh,
      yMax:c.baseHigh,
      borderColor:'#f97316',
      borderWidth:1.5,
      borderDash:[6,4],
      label:{
        display:true,
        content:`상한 ${c.baseHigh}`,
        position:'end',
        backgroundColor:'rgba(249,115,22,.85)',
        color:'#fff',
        font:{size:9},
        padding:3
      }
    };
  }

  chart.options.plugins.annotation = {annotations};
  chart.update();
}

if(history && history.labels) setChart('temp');

/* =========================
   센서 카드 갱신
========================= */
function updateSensorCards(rawSensor){
  const sensor = normalizeSensor(rawSensor);
  if(!sensor) return;

  const temp = toNumber(sensor.temperature);
  const ph = toNumber(sensor.ph);
  const dissolvedOxygen = toNumber(sensor.dissolved_oxygen);
  const tds = toNumber(sensor.tds_ppm);
  const waterLevel = toNumber(sensor.water_level);

  document.getElementById('val-temp').textContent = formatValue(temp);
  document.getElementById('val-ph').textContent = formatValue(ph);
  document.getElementById('val-do').textContent = formatValue(dissolvedOxygen);
  document.getElementById('val-tds').textContent = formatValue(tds);
  document.getElementById('val-level').textContent = formatValue(waterLevel);

  updateBadge(
    'badge-temp',
    temp === null ? '미연결' : (temp >= SENSOR_THRESHOLDS.tempMin && temp <= SENSOR_THRESHOLDS.tempMax ? '● 적정' : '● 주의'),
    temp === null ? '' : (temp >= SENSOR_THRESHOLDS.tempMin && temp <= SENSOR_THRESHOLDS.tempMax ? 'badge-ok' : 'badge-danger')
  );

  updateBadge(
    'badge-ph',
    ph === null ? '미연결' : (ph >= SENSOR_THRESHOLDS.phMin && ph <= SENSOR_THRESHOLDS.phMax ? '● 안정' : '● 확인필요'),
    ph === null ? '' : (ph >= SENSOR_THRESHOLDS.phMin && ph <= SENSOR_THRESHOLDS.phMax ? 'badge-ok' : 'badge-warn')
  );

  updateBadge(
    'badge-do',
    dissolvedOxygen === null ? '미연결' : (dissolvedOxygen >= SENSOR_THRESHOLDS.doMin ? '● 정상' : '● 부족'),
    dissolvedOxygen === null ? '' : (dissolvedOxygen >= SENSOR_THRESHOLDS.doMin ? 'badge-ok' : 'badge-danger')
  );

  let tdsText = '미연결';
  let tdsClass = '';
  if(tds !== null){
    if(tds <= SENSOR_THRESHOLDS.tdsMax){ tdsText='● 정상'; tdsClass='badge-ok'; }
    else { tdsText='● 위험'; tdsClass='badge-danger'; }
  }
  updateBadge('badge-tds', tdsText, tdsClass);

  let levelText = '미연결';
  let levelClass = '';
  if(waterLevel !== null){
    if(waterLevel >= 80){ levelText='● 정상'; levelClass='badge-ok'; }
    else if(waterLevel >= 60){ levelText='● 낮음'; levelClass='badge-warn'; }
    else { levelText='● 부족'; levelClass='badge-danger'; }
  }
  updateBadge('badge-level', levelText, levelClass);

  if(sensor.water_quality_score !== undefined && sensor.water_quality_score !== null){
    updateWaterQualityScore(sensor.water_quality_score);
  }
}

function updateBadge(id, text, cls){
  const el = document.getElementById(id);
  if(!el) return;

  el.className = 'sensor-badge' + (cls ? ' ' + cls : '');
  el.textContent = text;
}

function updateWaterQualityScore(score){
  const value = toNumber(score);
  const valueEl = document.getElementById('waterQualityScore');
  const barEl = document.getElementById('waterQualityBar');

  if(valueEl) valueEl.textContent = value === null ? '--' : value;
  if(barEl){
    const safe = value === null ? 0 : Math.max(0, Math.min(100, value));
    barEl.style.width = safe + '%';
    barEl.style.background =
      safe >= 70 ? '#10b981' :
      safe >= 40 ? '#f59e0b' : '#ef4444';
  }
}

/* =========================
   5초 폴링
========================= */
async function poll(){
  try{
    const r = await fetch(`/monitoring/api/dashboard-data/${TANK_ID}/`, {
      cache:'no-store'
    });

    if(!r.ok) return;

    const d = await r.json();
    latestDashboard = d;

    updateWaterChangeCheckState(d);

    const liveSensor = d.sensor || (
      d.tds_ppm !== undefined ||
      d.turbidity !== undefined ||
      d.temperature_c !== undefined ||
      d.temperature !== undefined
        ? d
        : null
    );
    if(liveSensor){
      const sensorForUi = {
        ...liveSensor,
        water_quality_score:
          liveSensor.water_quality_score ??
          liveSensor.waterQualityScore ??
          d.water_quality_score ??
          d.waterQualityScore
      };
      updateSensorCards(sensorForUi);
    } else {
      const polledScore =
        d.water_quality_score ??
        d.waterQualityScore;
      if(polledScore !== undefined && polledScore !== null){
        updateWaterQualityScore(polledScore);
      }
    }

    const nextHistory = historyFromApiPayload(d);
    if(nextHistory.labels.length){
      const nextHistorySignature = JSON.stringify(nextHistory);

      // 24시간 그래프 데이터가 실제로 달라졌을 때만 다시 그림.
      // 센서 카드와 상세 최근 12회 데이터는 계속 5초마다 갱신된다.
      if(nextHistorySignature !== mainHistorySignature){
        history = nextHistory;
        mainHistorySignature = nextHistorySignature;
        setChart(metric);
      }
    }

    const banner = document.getElementById('staleBanner');

    if(d.is_stale){
      let ageText = '';
      if(d.age_sec != null){
        const min = Math.floor(d.age_sec / 60);
        ageText = min >= 1 ? ` (${min}분 전 값)` : ' (방금 전 값)';
      }

      document.getElementById('staleBannerText').textContent =
        `센서 데이터 수신이 중단되었습니다. 마지막 수신값을 표시 중입니다${ageText}.`;

      banner.style.display = 'flex';
    }else{
      banner.style.display = 'none';
    }
  }catch(e){
    console.warn('[dashboard poll]', e);
  }
}

clearOldWaterChangeCheck();
if(isWaterChangeCheckedLocallyToday()){
  setWaterChangeButtonCompleted();
}

poll();
setInterval(poll, 5000);

/* =========================
   상태 경고 API
   GET /monitoring/api/states/active/?tank_id=1
========================= */
const LEVEL_STYLE = {
  DANGER:{
    bg:'#fdecea',
    border:'#ef4444',
    text:'#b71c1c',
    badge:'background:#ef4444;color:#fff'
  },
  WARNING:{
    bg:'#fff8e1',
    border:'#f59e0b',
    text:'#7a4a00',
    badge:'background:#f59e0b;color:#fff'
  }
};

function renderListItems(ulId, items){
  const ul = document.getElementById(ulId);
  if(!ul) return;

  const list = Array.isArray(items) ? items : [];

  ul.innerHTML = list.map(item =>
    `<li style="font-size:13px;color:#4b5564;padding:5px 10px;background:#f4f7fb;border-radius:8px">• ${esc(item)}</li>`
  ).join('') ||
  '<li style="font-size:13px;color:#a2adbc;padding:5px 10px">정보 없음</li>';
}

function openStateModal(state){
  const s = LEVEL_STYLE[state.level] || LEVEL_STYLE.WARNING;

  document.getElementById('stateModalHead').style.background = s.bg;
  document.getElementById('stateModalCode').textContent = state.code || 'STATE';
  document.getElementById('stateModalTitle').textContent = state.title || '상태 확인';
  document.getElementById('stateModalValue').textContent =
    state.current_value != null ? state.current_value : '--';

  const dt = state.detected_at ? formatDate(state.detected_at) : '';
  document.getElementById('stateModalTime').textContent =
    dt ? `감지: ${dt}` : '';

  renderListItems('stateModalCauses', state.causes);
  renderListItems('stateModalEffects', state.effects);
  renderListItems('stateModalActions', state.actions);
  renderListItems('stateModalPrevention', state.prevention);

  const modal = document.getElementById('stateModal');
  modal.style.display = 'flex';
}

function closeStateModal(){
  document.getElementById('stateModal').style.display = 'none';
}

document.getElementById('stateModal').addEventListener('click', e => {
  if(e.target === e.currentTarget) closeStateModal();
});

async function fetchActiveStates(){
  try{
    const r = await fetch(
      `/monitoring/api/states/active/?tank_id=${encodeURIComponent(TANK_ID)}`,
      {cache:'no-store'}
    );

    if(!r.ok) return;

    const d = await r.json();
    activeStates = Array.isArray(d.states) ? d.states : [];
    const container = document.getElementById('stateAlerts');

    container.innerHTML = '';

    if(!Array.isArray(d.states) || d.states.length === 0) return;

    d.states.forEach(state => {
      const s = LEVEL_STYLE[state.level] || LEVEL_STYLE.WARNING;

      const div = document.createElement('div');

      div.style.cssText =
        `display:flex;align-items:center;justify-content:space-between;` +
        `padding:14px 18px;border-radius:16px;` +
        `border-left:4px solid ${s.border};background:${s.bg};` +
        `cursor:pointer;gap:12px`;

      div.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;min-width:0">
          <span style="font-size:20px;flex:none">
            ${state.level === 'DANGER' ? '🚨' : '⚠️'}
          </span>
          <div style="min-width:0">
            <span style="font-size:11px;font-weight:900;color:${s.text}">
              ${esc(state.code || '')}
            </span>
            <p style="font-size:14px;font-weight:900;color:${s.text};
              margin:2px 0 0;white-space:nowrap;overflow:hidden;
              text-overflow:ellipsis">
              ${esc(state.title || '상태 확인 필요')}
            </p>
          </div>
        </div>
        <button type="button"
          style="flex:none;border:0;border-radius:10px;padding:7px 14px;
          font-size:12px;font-weight:900;cursor:pointer;${s.badge}">
          상세 보기 →
        </button>
      `;

      div.addEventListener('click', () => openStateModal(state));
      container.appendChild(div);
    });
  }catch(e){
    console.warn('[states]', e);
  }
}

fetchActiveStates();
setInterval(fetchActiveStates, 30000);

/* =========================
   1번째 코드의 환경정보 상세 모달
   - 기존 ENV_DETAIL_MOCK 제거
   - active state API + dashboard history 사용
========================= */
const environmentDetailModal = document.getElementById('environmentDetailModal');
const environmentDetailBtn = document.getElementById('environmentDetailBtn');
const environmentDetailClose = document.getElementById('environmentDetailClose');

const envDetailColorMap = {
  temperature:'#ff5d63',
  ph:'#249ee9',
  do:'#28c943',
  tds:'#f6a11a',
};

const envDetailLabelMap = {
  temperature:'수온',
  ph:'pH',
  do:'DO',
  tds:'TDS',
};

const envDetailUnitMap = {
  temperature:'°C',
  ph:'',
  do:'mg/L',
  tds:'PPM',
};

let latestDashboard = null;
let activeStates = [];

function envDetailLevelLabel(level){
  return level === 'danger' || level === 'DANGER'
    ? '위험'
    : level === 'warning' || level === 'WARNING'
      ? '경고'
      : '정상';
}

function normalizeStateLevel(level){
  if(!level) return 'normal';
  const upper = String(level).toUpperCase();
  if(upper === 'DANGER') return 'danger';
  if(upper === 'WARNING') return 'warning';
  return 'normal';
}

function findStateForSensor(key){
  const aliases = {
    temperature:['TEMP','TEMPERATURE','TMP'],
    ph:['PH'],
    do:['DO','DISSOLVED_OXYGEN'],
    tds:['TDS','TDS_PPM','TURB','TURBIDITY'],
  };

  const targets = aliases[key] || [];

  return activeStates.find(state => {
    const code = String(state.code || '').toUpperCase();
    return targets.some(prefix => code.startsWith(prefix));
  }) || null;
}

function getSensorFromDashboard(key){
  const s = normalizeSensor(latestDashboard && latestDashboard.sensor);
  if(!s) return null;

  if(key === 'temperature') return s.temperature;
  if(key === 'ph') return s.ph;
  if(key === 'do') return s.dissolved_oxygen;
  if(key === 'tds') return s.tds_ppm;

  return null;
}

function getDetailHistoryFromDashboard(){
  const raw = latestDashboard?.detail_history;

  if(raw){
    return {
      labels: Array.isArray(raw.labels) ? raw.labels : [],
      temp: Array.isArray(raw.temp) ? raw.temp : [],
      ph: Array.isArray(raw.ph) ? raw.ph : [],
      do: Array.isArray(raw.do) ? raw.do : [],
      tds: Array.isArray(raw.tds) ? raw.tds :
           Array.isArray(raw.tds_ppm) ? raw.tds_ppm :
           Array.isArray(raw.turb) ? raw.turb :
           Array.isArray(raw.turbidity) ? raw.turbidity : []
    };
  }

  // 하위 호환: detail_history가 없는 서버에서는 기존 history 사용
  return historyFromApiPayload(latestDashboard || {});
}

function getTrendFromDashboard(key){
  const h = getDetailHistoryFromDashboard();
  if(!h) return [];

  if(key === 'temperature') return h.temp;
  if(key === 'ph') return h.ph;
  if(key === 'do') return h.do;
  if(key === 'tds') return h.tds;

  return [];
}

function getCurrentState(key){
  const state = findStateForSensor(key);
  if(state) return normalizeStateLevel(state.level);

  const value = toNumber(getSensorFromDashboard(key));

  if(value === null) return 'normal';

  if(key === 'temperature'){
    return value >= SENSOR_THRESHOLDS.tempMin && value <= SENSOR_THRESHOLDS.tempMax ? 'normal' : 'danger';
  }

  if(key === 'ph'){
    return value >= SENSOR_THRESHOLDS.phMin && value <= SENSOR_THRESHOLDS.phMax ? 'normal' : 'warning';
  }

  if(key === 'do'){
    return value >= SENSOR_THRESHOLDS.doMin ? 'normal' : 'danger';
  }

  if(key === 'tds'){
    return value <= SENSOR_THRESHOLDS.tdsMax ? 'normal' : 'danger';
  }

  return 'normal';
}

function getNormalRange(key){
  const ranges = {
    temperature:`${SENSOR_THRESHOLDS.tempMin} ~ ${SENSOR_THRESHOLDS.tempMax} °C`,
    ph:`${SENSOR_THRESHOLDS.phMin} ~ ${SENSOR_THRESHOLDS.phMax}`,
    do:`${SENSOR_THRESHOLDS.doMin} mg/L 이상`,
    tds:`0 ~ ${SENSOR_THRESHOLDS.tdsMax} PPM`,
  };
  return ranges[key] || '-';
}

function getFallbackDescription(key, level){
  if(level === 'danger') return `${envDetailLabelMap[key]} 수치가 위험 수준입니다.`;
  if(level === 'warning') return `${envDetailLabelMap[key]} 수치가 권장 범위를 벗어났습니다.`;
  return `현재 ${envDetailLabelMap[key]} 상태는 정상입니다.`;
}

function renderEnvDetailStatus(sensor){
  const level = sensor.level || 'normal';

  const badgeClass =
    level === 'danger' ? 'env-danger-badge' :
    level === 'warning' ? 'env-warning-badge' :
    'env-normal-badge';

  document.getElementById('envDetailStatusBadge').innerHTML =
    `<span class="env-status-badge ${badgeClass}">
      <span class="env-status-dot"></span>
      ${envDetailLevelLabel(level)}
    </span>`;

  document.getElementById('envDetailStatusDescription').textContent =
    sensor.description || getFallbackDescription(sensor.key, level);

  const code = document.getElementById('envDetailStateCode');
  code.textContent = sensor.stateCode || 'STATE-NORMAL-000';
  code.classList.remove('code-normal','code-warning','code-danger');
  code.classList.add(
    level === 'danger' ? 'code-danger' :
    level === 'warning' ? 'code-warning' :
    'code-normal'
  );
}

function renderEnvDetailList(id, items, level){
  const el = document.getElementById(id);
  const card = el.closest('.env-detail-card');

  const list = Array.isArray(items) ? items : [];

  if(level === 'normal'){
    card.classList.add('normal-card');
    el.innerHTML =
      '<div class="env-normal-placeholder">이상 상태 없음</div>';
    return;
  }

  card.classList.remove('normal-card');

  el.innerHTML =
    '<ul class="env-detail-list">' +
    (list.length
      ? list.map(item => `<li>${esc(item)}</li>`).join('')
      : '<li>상세 정보가 없습니다.</li>') +
    '</ul>';
}

function makeEnvDetailChart(values, color){
  const numeric = (Array.isArray(values) ? values : [])
    .map(Number)
    .filter(Number.isFinite);

  const line = document.getElementById('envDetailTrendLine');
  const area = document.getElementById('envDetailTrendArea');
  const points = document.getElementById('envDetailTrendPoints');

  if(numeric.length === 0){
    line.setAttribute('points','');
    area.setAttribute('points','');
    points.innerHTML = '';
    ['envY5','envY4','envY3','envY2','envY1']
      .forEach(id => document.getElementById(id).textContent = '-');
    return;
  }

  const width = 800;
  const height = 216;

  if(numeric.length === 1){
    numeric.push(numeric[0]);
  }

  const min = Math.min(...numeric);
  const max = Math.max(...numeric);
  const pad = Math.max((max - min) * .2, .5);
  const lo = min - pad;
  const hi = max + pad;
  const step = width / (numeric.length - 1);

  const coords = numeric.map((value,index) => [
    index * step,
    height - ((value - lo) / (hi - lo)) * height
  ]);

  line.setAttribute(
    'points',
    coords.map(p => p.join(',')).join(' ')
  );
  line.setAttribute('stroke', color);

  area.setAttribute(
    'points',
    coords.map(p => p.join(','))
      .concat([`${width},${height}`,`0,${height}`])
      .join(' ')
  );
  area.setAttribute('fill', color);

  points.innerHTML = '';

  coords.forEach(([x,y]) => {
    const circle = document.createElementNS(
      'http://www.w3.org/2000/svg',
      'circle'
    );
    circle.setAttribute('cx',x);
    circle.setAttribute('cy',y);
    circle.setAttribute('r','4');
    circle.setAttribute('fill',color);
    points.appendChild(circle);
  });

  const ticks = [
    hi,
    hi - (hi-lo)*.25,
    hi - (hi-lo)*.5,
    hi - (hi-lo)*.75,
    lo
  ];

  ['envY5','envY4','envY3','envY2','envY1']
    .forEach((id,index) => {
      document.getElementById(id).textContent =
        ticks[index].toFixed(1);
    });
}

function buildEnvironmentDetailSensor(key){
  const state = findStateForSensor(key);
  const value = getSensorFromDashboard(key);

  const level = getCurrentState(key);

  let stateCode = state ? state.code : null;
  let description = state ? state.description : null;

  const sensor = {
    key,
    label:envDetailLabelMap[key],
    unit:envDetailUnitMap[key],
    value,
    normalRange:getNormalRange(key),
    level,
    stateCode,
    description,
    causes:state ? state.causes : [],
    effects:state ? state.effects : [],
    actions:state ? state.actions : [],
    prevention:state ? state.prevention : [],
    trend:getTrendFromDashboard(key),
    lastUpdated:
      state && state.detected_at
        ? formatDate(state.detected_at)
        : '-' 
  };

  return sensor;
}

function getWaterChangeDisplayValue(){
  const el = document.querySelector('.water-change-btn');
  const text = el ? el.textContent.trim() : '';

  if(text.includes('환수 체크 완료')) return '오늘 완료';

  const title = document.querySelector('.tank-summary p');
  if(title){
    const match = title.textContent.match(/D[+-]\s*\d+/);
    if(match) return match[0].replace(/\s+/g,' ');
  }

  return 'D -';
}

function getDashboardUpdatedAt(){
  const s = latestDashboard?.sensor;
  return formatDate(
    s?.measured_at ||
    s?.created_at ||
    s?.timestamp ||
    latestDashboard?.measured_at ||
    latestDashboard?.updated_at
  );
}

function renderEnvironmentDetailSensor(key){
  const sensor = buildEnvironmentDetailSensor(key);

  const valueText = sensor.value == null
    ? '--'
    : `${formatValue(sensor.value)}${sensor.unit ? ' ' + sensor.unit : ''}`;

  document.getElementById('envDetailSensorValue').textContent = valueText;
  document.getElementById('envDetailNormalRange').textContent =
    '적정 범위 ' + sensor.normalRange;
  document.getElementById('envDetailLastUpdated').textContent =
    sensor.lastUpdated;
  document.getElementById('envDetailTrendSensorName').textContent =
    sensor.label;

  const trendCard = document.getElementById('envDetailTrendCard');
  const detailSectionHead = document.getElementById('envDetailSectionHead');
  const detailGrid = document.getElementById('envDetailGrid');

  trendCard.style.display = 'block';
  detailSectionHead.style.display = 'flex';
  detailGrid.style.display = 'grid';

  makeEnvDetailChart(sensor.trend, envDetailColorMap[key]);

  const detailHistory = getDetailHistoryFromDashboard();
  const labels = Array.isArray(detailHistory?.labels) ? detailHistory.labels : [];
  document.getElementById('envDetailXLabels').innerHTML =
    labels.slice(-6).map(label => `<span>${esc(label)}</span>`).join('');

  renderEnvDetailStatus(sensor);
  renderEnvDetailList('envDetailCauses',sensor.causes,sensor.level);
  renderEnvDetailList('envDetailEffects',sensor.effects,sensor.level);
  renderEnvDetailList('envDetailActions',sensor.actions,sensor.level);
  renderEnvDetailList('envDetailPrevention',sensor.prevention,sensor.level);

  document.querySelectorAll('.env-sensor-tab').forEach(btn => {
    btn.classList.toggle('active',btn.dataset.envSensor === key);
  });
}

function openEnvironmentDetail(){
  renderEnvironmentDetailSensor('temperature');
  environmentDetailModal.classList.add('open');
  environmentDetailModal.setAttribute('aria-hidden','false');
  document.body.style.overflow = 'hidden';
}

function closeEnvironmentDetail(){
  environmentDetailModal.classList.remove('open');
  environmentDetailModal.setAttribute('aria-hidden','true');
  document.body.style.overflow = '';
}

environmentDetailBtn.addEventListener('click',openEnvironmentDetail);
environmentDetailClose.addEventListener('click',closeEnvironmentDetail);

document.querySelectorAll('.env-sensor-tab').forEach(btn => {
  btn.addEventListener('click',() => {
    renderEnvironmentDetailSensor(btn.dataset.envSensor);
  });
});

environmentDetailModal.addEventListener('click',event => {
  if(event.target === environmentDetailModal){
    closeEnvironmentDetail();
  }
});

document.addEventListener('keydown',event => {
  if(event.key === 'Escape' &&
     environmentDetailModal.classList.contains('open')){
    closeEnvironmentDetail();
  }
});

/* =========================
   대시보드 API 응답 저장
   상세 모달은 이 데이터를 사용한다.
========================= */
async function refreshDashboardForDetail(){
  try{
    const r = await fetch(
      `/monitoring/api/dashboard-data/${TANK_ID}/`,
      {cache:'no-store'}
    );
    if(r.ok){
      latestDashboard = await r.json();
    }
  }catch(e){
    console.warn('[detail dashboard]',e);
  }
}

async function refreshStatesForDetail(){
  try{
    const r = await fetch(
      `/monitoring/api/states/active/?tank_id=${encodeURIComponent(TANK_ID)}`,
      {cache:'no-store'}
    );
    if(r.ok){
      const d = await r.json();
      activeStates = Array.isArray(d.states) ? d.states : [];
    }
  }catch(e){
    console.warn('[detail states]',e);
  }
}

/* 최초 상세 모달용 데이터 확보 */
refreshDashboardForDetail();
refreshStatesForDetail();

/* 계정/로그아웃 */
try{
  const account = JSON.parse(
    localStorage.getItem('fishTankAccount') || 'null'
  );

  if(account && account.id){
    const userName = document.getElementById('userName');
    const userCircle = document.querySelector('.user-circle');

    if(userName) userName.textContent = account.id + ' 님';
    if(userCircle) userCircle.textContent = account.id.charAt(0);
  }
}catch(e){}
  
/* 서버 템플릿에 이미 있는 로그아웃 버튼 사용 */
const logoutBtn = document.getElementById('logoutBtn');
if(logoutBtn){
  logoutBtn.addEventListener('click',() => {
    sessionStorage.removeItem('fishTankLoggedIn');
    location.href = '/';
  });
}


// HTML 인라인 이벤트를 외부 JS에서 연결
document.getElementById('sbToggle')?.addEventListener('click',toggleSb);
document.getElementById('stateModalCloseBtn')?.addEventListener('click',closeStateModal);
document.querySelectorAll('.chart-tab[data-chart]').forEach(btn=>btn.addEventListener('click',()=>setChart(btn.dataset.chart,btn)));
document.querySelectorAll('.device-card[data-device]').forEach(card=>card.addEventListener('click',()=>toggleDevice(card.dataset.device)));
document.getElementById('waterChangeCheckBtn')?.addEventListener('click',checkWaterChange);
document.getElementById('waterChangeCancelBtn')?.addEventListener('click',()=>closeWaterChangeConfirm(false));
document.getElementById('waterChangeConfirmBtn')?.addEventListener('click',()=>closeWaterChangeConfirm(true));
