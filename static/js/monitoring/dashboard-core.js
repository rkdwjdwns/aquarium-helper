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

/* 대시보드 공통 상태 */
let latestDashboard = null;
let activeStates = [];
