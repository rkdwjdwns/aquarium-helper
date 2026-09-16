/* =========================
   환경정보 상세 모달
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

async function openEnvironmentDetail(){
  await Promise.all([refreshDashboardForDetail(), refreshStatesForDetail()]);
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

window.openEnvironmentDetail = openEnvironmentDetail;
