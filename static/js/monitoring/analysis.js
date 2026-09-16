const APP_CONFIG = document.getElementById('analysisConfig').dataset;
const FEEDING_CSV_URL = APP_CONFIG.feedingUrl;
const ABR_CSV_URL = APP_CONFIG.abrUrl;
const ACTIVITY_CSV_URL = APP_CONFIG.activityUrl;
const GROWTH_CSV_URL = APP_CONFIG.growthUrl;

let FEEDING_ROWS = [];
let ABR_ROWS = [];
let ACTIVITY_ROWS = [];
let GROWTH_ROWS = [];
let activityChartInst = null;
let feedingEventChartInst = null;
let growthMainChartInst = null;
let FEEDING_TABLE_ROWS = [];
let feedingRecordPage = 1;
const FEEDING_RECORD_PAGE_SIZE = 6;

function toggleSb(){
  const sb=document.getElementById('sidebar');
  sb.classList.toggle('collapsed');
  const c=sb.classList.contains('collapsed');
  document.getElementById('sbToggle').textContent=c?'›':'‹';
  document.getElementById('mainContent').style.marginLeft=c?'44px':'var(--sw)';
}

function parseCSV(text){
  const rows=[];
  let row=[], cell="", quoted=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i], next=text[i+1];
    if(ch === '"'){
      if(quoted && next === '"'){ cell+='"'; i++; }
      else quoted=!quoted;
    }else if(ch === ',' && !quoted){
      row.push(cell); cell="";
    }else if((ch === '\n' || ch === '\r') && !quoted){
      if(ch === '\r' && next === '\n') i++;
      row.push(cell); cell="";
      if(row.some(v=>v!=="")) rows.push(row);
      row=[];
    }else{
      cell+=ch;
    }
  }
  if(cell!=="" || row.length){ row.push(cell); rows.push(row); }
  const headers=rows.shift().map(h=>h.replace(/^\uFEFF/,"").trim());
  return rows.map(r=>Object.fromEntries(headers.map((h,i)=>[h,(r[i]??"").trim()])));
}

function num(v, fallback=null){
  const n=Number(v);
  return v==="" || Number.isNaN(n) ? fallback : n;
}
function formatTime(ts){
  if(!ts) return "--";
  return ts.replace("+09:00","").replace("T"," ").slice(5,16);
}
function sortDesc(a,b){ return new Date(b.timestamp)-new Date(a.timestamp); }

function rowsUntilNow(rows){
  const now=new Date();
  return [...rows].filter(r=>{
    if(!r.timestamp) return false;
    const t=new Date(r.timestamp);
    return !Number.isNaN(t.getTime()) && t<=now;
  });
}

function rowsInRecentMinutes(rows, minutes){
  const now=new Date();
  const cutoff=new Date(now.getTime()-minutes*60*1000);
  return rowsUntilNow(rows).filter(r=>{
    const t=new Date(r.timestamp);
    return t>=cutoff;
  });
}

function validFeeding(rows){ return rows.filter(r=>r.status==="OK" && r.frs_score!==""); }

function frsGrade(score){
  // FRS 평가 기준
  // 80~100 : 반응 강함
  // 60~79  : 양호
  // 40~59  : 보통
  // 20~39  : 낮음
  // 0~19   : 매우 낮음
  if(score>=80) return "반응 강함";
  if(score>=60) return "양호";
  if(score>=40) return "보통";
  if(score>=20) return "낮음";
  return "매우 낮음";
}

function activityState(row){
  // 활동 상태는 Activity Index로 프론트에서 재판정하지 않고
  // CSV의 behavior_status 값을 그대로 사용한다.
  const grade=String(row?.behavior_status || "").toUpperCase();
  return grade || "--";
}

function setActivityStateStyle(el, grade){
  const colors={
    LOW:"#3b82f6",
    NORMAL:"#10b981",
    HIGH:"#ef4444",
    WATCH:"#f59e0b",
    CAUTION:"#f59e0b",
    WATCH:"#f59e0b",
    ABNORMAL:"#ef4444"
  };
  el.style.color=colors[grade] || "#6b7280";
  el.style.fontWeight="900";
}

function abrGrade(rate){
  // ABR 이상행동률 평가 기준
  // NORMAL  : 0 ~ <5%
  // CAUTION : 5 ~ <13%
  // ABNORMAL   : 13% 이상
  if(rate>=13) return "ABNORMAL";
  if(rate>=5) return "CAUTION";
  return "NORMAL";
}

function setAbrStatusStyle(el, grade){
  const colors={
    NORMAL:"#10b981",
    CAUTION:"#f59e0b",
    ABNORMAL:"#ef4444"
  };
  el.style.color=colors[grade] || "#6b7280";
  el.style.fontWeight="900";
}

function boolValue(v){
  return ["true","1","yes","y"].includes(String(v ?? "").trim().toLowerCase());
}

function renderSummary(){
  const abrRecent=rowsInRecentMinutes(ABR_ROWS,5).sort(sortDesc);
  const s=abrRecent.length ? abrRecent[0] : null;

  const activityRecent=rowsInRecentMinutes(ACTIVITY_ROWS,30).sort(sortDesc);
  const activityLatest=activityRecent.length ? activityRecent[0] : null;

  if(s){
    const abrRate=num(s.abr_pct,0);
    document.getElementById("abrRate").innerHTML=`${abrRate.toFixed(1)}<small>%</small>`;

    const abrStatus=String(s.behavior_status || abrGrade(abrRate)).toUpperCase();
    const abrStatusEl=document.getElementById("abrStatus");
    abrStatusEl.textContent=abrStatus;
    setAbrStatusStyle(abrStatusEl,abrStatus);

    const anomalyCount=abrRecent.filter(r=>boolValue(r.is_anomaly)).length;
    document.getElementById("abrCount").textContent=anomalyCount+"회";
  }else{
    document.getElementById("abrRate").textContent="--";
    document.getElementById("abrStatus").textContent="--";
    document.getElementById("abrStatus").style.color="#6b7280";
    document.getElementById("abrCount").textContent="--";
  }

  if(activityLatest){
    const level=num(activityLatest.activity_level_px_s,null);
    document.getElementById("actIndex").innerHTML=level===null ? "--" : `${level.toFixed(1)}<small> px/s</small>`;

    const levels=activityRecent.map(r=>num(r.activity_level_px_s,null)).filter(v=>v!==null);
    const avg=levels.length ? levels.reduce((a,b)=>a+b,0)/levels.length : null;
    const diff=(level!==null && avg) ? (level-avg)/avg*100 : null;
    document.getElementById("actCompare").textContent=diff===null ? "--" : `${diff>=0?"+":""}${diff.toFixed(1)}%`;
    document.getElementById("actCompare").style.color=diff===null ? "#6b7280" : (diff>=0?"#10b981":"#ef4444");

    const actGrade=activityState(activityLatest);
    const actStateEl=document.getElementById("actState");
    actStateEl.textContent=actGrade;
    setActivityStateStyle(actStateEl,actGrade);

    const qualitySource=activityRecent.find(r=>
      r.quality_good_pct!=="" && r.quality_fair_pct!=="" && r.quality_poor_pct!==""
    );
    if(qualitySource){
      document.getElementById("qualityGood").textContent=num(qualitySource.quality_good_pct,0).toFixed(1)+"%";
      document.getElementById("qualityFair").textContent=num(qualitySource.quality_fair_pct,0).toFixed(1)+"%";
      document.getElementById("qualityPoor").textContent=num(qualitySource.quality_poor_pct,0).toFixed(1)+"%";
    }else{
      document.getElementById("qualityGood").textContent="--";
      document.getElementById("qualityFair").textContent="--";
      document.getElementById("qualityPoor").textContent="--";
    }
  }else{
    document.getElementById("actIndex").textContent="--";
    document.getElementById("actCompare").textContent="--";
    document.getElementById("actState").textContent="--";
    document.getElementById("qualityGood").textContent="--";
    document.getElementById("qualityFair").textContent="--";
    document.getElementById("qualityPoor").textContent="--";
  }
}

function renderActivity(){
  // CSV 전체 기간과 관계없이 브라우저의 현재 시각을 기준으로
  // 현재 시각 - 30분 ~ 현재 시각 사이의 데이터만 표시한다.
  const allRows=[...ACTIVITY_ROWS]
    .filter(r=>r.timestamp && !Number.isNaN(new Date(r.timestamp).getTime()))
    .sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));

  if(!allRows.length) return;

  const now=new Date();
  const cutoffTime=new Date(now.getTime()-30*60*1000);

  const rows=allRows.filter(r=>{
    const t=new Date(r.timestamp);
    return t>=cutoffTime && t<=now;
  });

  const ctx=document.getElementById("activityChart");
  if(activityChartInst) activityChartInst.destroy();

  // 현재 30분 안에 데이터가 없으면 빈 그래프를 표시한다.
  const labels=rows.map(r=>formatTime(r.timestamp).slice(-5));
  const vals=rows.map(r=>num(r.activity_level_px_s,null));
  const validVals=vals.filter(v=>v!==null);
  const avg=validVals.length ? validVals.reduce((a,b)=>a+b,0)/validVals.length : 0;
  const baseline=rows.map(()=>avg);
  if(activityChartInst) activityChartInst.destroy();
  activityChartInst=new Chart(ctx,{
    type:"line",
    data:{
      labels,
      datasets:[
        {label:"Activity Level (px/s)",data:vals,borderColor:"#3b82f6",backgroundColor:"rgba(59,130,246,.08)",pointRadius:3,borderWidth:2,tension:.25,fill:true},
        {label:"최근 30분 평균",data:baseline,borderColor:"#94a3b8",pointRadius:0,borderDash:[5,5],borderWidth:1.5}
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{
        x:{grid:{display:false},ticks:{font:{size:9}}},
        y:{beginAtZero:true,ticks:{font:{size:9}},grid:{color:"rgba(0,0,0,.05)"}}
      }
    }
  });
}

function renderFRSMain(){
  // 현재 시각 이후의 예약/미래 급이 데이터는 제외한다.
  const all=rowsUntilNow(FEEDING_ROWS).sort(sortDesc);
  if(!all.length){
    document.getElementById("frsScore").textContent="--";
    document.getElementById("frsLabel").textContent="유효 기록 없음";
    document.getElementById("frsActivityScore").textContent="--";
    document.getElementById("frsLatencyScore").textContent="--";
    document.getElementById("frsTime").textContent="--";
    document.getElementById("frsRecentValidLabel").textContent="현재 시각 이전 급이 기록 없음";
    return;
  }

  const current=all[0];
  const valid=validFeeding(all).sort(sortDesc);
  const lastValid=valid[0];

  /*
   * 메인 분석카드는 최신 급이 이벤트가 분석불가여도
   * "분석불가 / 행동데이터 부족"을 표시하지 않고
   * 가장 최근에 정상 분석된 FRS 기록을 표시한다.
   */
  const displayRow =
    (current.status==="OK" && current.frs_score!=="")
      ? current
      : lastValid;

  if(!displayRow){
    const score=document.getElementById("frsScore");
    score.textContent="--";
    score.classList.remove("unavailable");

    document.getElementById("frsLabel").textContent="유효 기록 없음";
    document.getElementById("frsLabel").className="";
    document.getElementById("frsActivityScore").textContent="--";
    document.getElementById("frsLatencyScore").textContent="--";
    document.getElementById("frsTime").textContent="--";
    document.getElementById("frsRecentValidLabel").textContent="최근 유효 FRS 없음";
    return;
  }

  const sc=num(displayRow.frs_score,0);
  const score=document.getElementById("frsScore");

  score.innerHTML=`${sc.toFixed(1)}<small>점/100</small>`;
  score.classList.remove("unavailable");

  document.getElementById("frsLabel").textContent=frsGrade(sc);
  const frsLabelEl=document.getElementById("frsLabel");
  if(sc>=60) frsLabelEl.style.color="#10b981";
  else if(sc>=40) frsLabelEl.style.color="#d97706";
  else frsLabelEl.style.color="#ef4444";
  frsLabelEl.style.fontWeight="900";
  document.getElementById("frsActivityScore").textContent=
    num(displayRow.activity_score,0).toFixed(1)+"점";
  document.getElementById("frsLatencyScore").textContent=
    num(displayRow.latency_score,0).toFixed(1)+"점";
  document.getElementById("frsTime").textContent=
    formatTime(displayRow.timestamp);

  /*
   * 최신 이벤트가 분석불가였을 때는
   * 현재 카드가 이전 유효 기록을 보여주고 있음을 명확히 표시.
   */
  document.getElementById("frsRecentValidLabel").textContent =
    displayRow === current
      ? `최근 유효 FRS ${sc.toFixed(1)}점 · ${formatTime(displayRow.timestamp)}`
      : `최근 분석 기록 ${sc.toFixed(1)}점 · ${formatTime(displayRow.timestamp)}`;
}

function parseGrowthDate(v){
  if(!v) return null;
  const raw=String(v).trim();
  const d=new Date(raw.length===10 ? raw+"T00:00:00" : raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatGrowthDate(v){
  const d=parseGrowthDate(v);
  if(!d) return "--";
  return `${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

let selectedGrowthFishId=1;

function growthBool(v){
  return String(v ?? "").trim().toLowerCase()==="true";
}

function isGrowthDeathRow(r){
  return !!r && String(r.life_status || "").trim().toUpperCase()==="DECEASED";
}

function updateGrowthFishButtons(){
  document.querySelectorAll(".growth-fish-btn").forEach(btn=>{
    btn.classList.toggle("active",Number(btn.dataset.fishId)===selectedGrowthFishId);
  });
}

function selectedFishGrowthRows(){
  return [...GROWTH_ROWS]
    .filter(r=>r.timestamp && Number(r.fish_id)===selectedGrowthFishId)
    .sort((a,b)=>parseGrowthDate(a.timestamp)-parseGrowthDate(b.timestamp));
}

function renderGrowthMain(){
  updateGrowthFishButtons();

  const arr=selectedFishGrowthRows();
  if(!arr.length) return;

  const now=new Date();
  const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const todayKey=[
    today.getFullYear(),
    String(today.getMonth()+1).padStart(2,"0"),
    String(today.getDate()).padStart(2,"0")
  ].join("-");

  const deathRow=arr.find(isGrowthDeathRow) || null;
  const isDeadFish=selectedGrowthFishId===3 && !!deathRow;

  // 기존 로직 유지: history/current_anchor는 과거 이력, current_temp는 오늘만 사용.
  // FISH 3의 deceased 행은 마지막 실제 측정점으로 포함한다.
  const weeklyHistoryRows=arr.filter(r=>{
    const d=parseGrowthDate(r.timestamp);
    return d && d<=today &&
      r.estimated_length_cm!=="" &&
      (r.phase==="history" || r.phase==="current_anchor" || isGrowthDeathRow(r));
  });

  const todayTempRow=isDeadFish ? null : arr.find(r=>
    String(r.timestamp || "").slice(0,10)===todayKey &&
    r.phase==="current_temp" &&
    r.estimated_length_cm!==""
  );

  const historyRows=todayTempRow
    ? [...weeklyHistoryRows,todayTempRow]
        .sort((a,b)=>parseGrowthDate(a.timestamp)-parseGrowthDate(b.timestamp))
    : weeklyHistoryRows;

  const currentRow=isDeadFish
    ? deathRow
    : (todayTempRow ||
       (weeklyHistoryRows.length ? weeklyHistoryRows[weeklyHistoryRows.length-1] : null));

  if(!currentRow || !historyRows.length) return;

  const first=historyRows[0];
  const current=num(currentRow.estimated_length_cm,null);
  const currentError=num(currentRow.observed_error_cm,null);
  const firstValue=num(first.estimated_length_cm,null);

  // 현재 '체장'을 cm로 표시한다.
  document.getElementById("growthAvgCurrent").innerHTML=
    current===null ? "--" : `${current.toFixed(2)}<small>cm</small>`;

  document.getElementById("growthAvgDate").textContent=isDeadFish
    ? `${formatGrowthDate(currentRow.timestamp)} 폐사 시점 마지막 체장`
    : `${formatGrowthDate(currentRow.timestamp)} 기준 현재 체장${currentRow.phase==="current_temp" ? " · 현재 데이터" : ""}`;

  document.getElementById("growthErrorRange").textContent=
    currentError===null ? "--" : `±${currentError.toFixed(2)} cm`;

  // FISH 3은 요청대로 사육기간/성장속도를 -- 로 표시한다.
  if(isDeadFish){
    document.getElementById("growthPeriod").textContent="--";
    document.getElementById("growthSpeed").textContent="--";
  }else{
    const days=num(currentRow.day_since_first,null);
    document.getElementById("growthPeriod").textContent=
      days===null ? "--" : `${Math.round(days)}일`;

    const speed=num(currentRow.growth_rate_cm_day,null);
    document.getElementById("growthSpeed").textContent=
      speed===null ? "--" : `${speed>=0?"+":""}${speed.toFixed(3)} cm/day`;
  }

  const futureDays=Number(document.getElementById("growthPeriodSelect")?.value || 180);
  renderGrowthMainChart(arr,currentRow,futureDays,today,isDeadFish);
}

function renderGrowthMainChart(arr,currentRow,futureDays=180,today=null,isDeadFish=false){
  const toggles={};
  document.querySelectorAll(".growth-main-toggle").forEach(
    c=>toggles[c.value]=c.checked
  );

  const anchorDate=parseGrowthDate(currentRow.timestamp);
  const currentDay=today || anchorDate;
  const cutoffDate=anchorDate
    ? new Date(anchorDate.getTime()+futureDays*24*60*60*1000)
    : null;

  // FISH 3은 폐사일까지의 실제 성장값만 표시하되,
  // X축은 6월 한 달 전체(06-01 ~ 06-30)가 보이도록 빈 날짜 구간을 추가한다.
  let graphRows=[...arr];

  graphRows=graphRows.filter(r=>{
    const d=parseGrowthDate(r.timestamp);
    if(!d) return false;

    if(isDeadFish){
      return d<=anchorDate &&
        (r.phase==="history" || r.phase==="current_anchor" || isGrowthDeathRow(r));
    }

    if(r.phase==="history" || r.phase==="current_anchor"){
      return d<=currentDay;
    }
    if(r.phase==="current_temp"){
      return d.getFullYear()===currentDay.getFullYear() &&
             d.getMonth()===currentDay.getMonth() &&
             d.getDate()===currentDay.getDate();
    }
    if(r.phase==="prediction"){
      return d>currentDay && (!cutoffDate || d<=cutoffDate);
    }
    return false;
  });

  // FISH 3의 X축은 기간 선택값과 관계없이 6월 1일~6월 30일로 고정한다.
  // 데이터가 없는 날짜에는 빈 행을 넣어 실제 날짜 간격을 유지하고,
  // 성장선 자체는 폐사일 이후 이어지지 않도록 한다.
  if(isDeadFish && anchorDate){
    const year=anchorDate.getFullYear();
    const rowByDate=new Map(
      graphRows.map(r=>[String(r.timestamp || "").slice(0,10),r])
    );
    const fixedJuneRows=[];
    for(let day=1;day<=30;day++){
      const key=`${year}-06-${String(day).padStart(2,"0")}`;
      fixedJuneRows.push(rowByDate.get(key) || {
        timestamp:key,
        fish_id:String(selectedGrowthFishId),
        estimated_length_cm:"",
        life_status:"",
        phase:"axis_padding"
      });
    }
    graphRows=fixedJuneRows;
  }

  const labels=graphRows.map(r=>formatGrowthDate(r.timestamp));

  const isVisibleObservedRow=r=>{
    const d=parseGrowthDate(r.timestamp);
    if(!d || r.estimated_length_cm==="") return false;

    if(isDeadFish){
      return d<=anchorDate &&
        (r.phase==="history" || r.phase==="current_anchor" || isGrowthDeathRow(r));
    }

    if(d>currentDay) return false;
    if(r.phase==="history" || r.phase==="current_anchor") return true;
    return r.phase==="current_temp" &&
      d.getFullYear()===currentDay.getFullYear() &&
      d.getMonth()===currentDay.getMonth() &&
      d.getDate()===currentDay.getDate();
  };

  const observed=graphRows.map(r=>
    isVisibleObservedRow(r) ? num(r.estimated_length_cm,null) : null
  );
  const observedLower=graphRows.map(r=>
    isVisibleObservedRow(r) ? num(r.observed_lower_cm,null) : null
  );
  const observedUpper=graphRows.map(r=>
    isVisibleObservedRow(r) ? num(r.observed_upper_cm,null) : null
  );

  // FISH 3은 미래 성장 예측을 표시하지 않는다.
  const vbgf=graphRows.map(r=>{
    if(isDeadFish) return null;
    const d=parseGrowthDate(r.timestamp);
    if(!d || d<anchorDate) return null;
    if(d.getTime()===anchorDate.getTime()){
      return num(r.vbgf_predicted_length_cm,
        num(r.estimated_length_cm,null));
    }
    return num(r.vbgf_predicted_length_cm,null);
  });

  const vbgfLower=graphRows.map(r=>{
    if(isDeadFish) return null;
    const d=parseGrowthDate(r.timestamp);
    if(!d || d<anchorDate) return null;
    if(d.getTime()===anchorDate.getTime()){
      return num(r.vbgf_prediction_lower_cm,
        num(r.observed_lower_cm,null));
    }
    return num(r.vbgf_prediction_lower_cm,null);
  });

  const vbgfUpper=graphRows.map(r=>{
    if(isDeadFish) return null;
    const d=parseGrowthDate(r.timestamp);
    if(!d || d<anchorDate) return null;
    if(d.getTime()===anchorDate.getTime()){
      return num(r.vbgf_prediction_upper_cm,
        num(r.observed_upper_cm,null));
    }
    return num(r.vbgf_prediction_upper_cm,null);
  });

  // FISH 3은 참고 성장선도 표시하지 않는다.
  const comet=graphRows.map(r=>
    isDeadFish ? null : num(r.comet_reference_length_cm,null)
  );
  const cometLower=graphRows.map(r=>
    isDeadFish ? null : num(r.comet_reference_lower_cm,null)
  );
  const cometUpper=graphRows.map(r=>
    isDeadFish ? null : num(r.comet_reference_upper_cm,null)
  );

  if(growthMainChartInst) growthMainChartInst.destroy();

  const datasets=[
    {
      label:"관측 오차 상한",
      data:observedUpper,
      borderColor:"rgba(37,99,235,0)",
      backgroundColor:"rgba(37,99,235,.18)",
      pointRadius:0,
      fill:"+1",
      hidden:!toggles.error
    },
    {
      label:"관측 오차 하한",
      data:observedLower,
      borderColor:"rgba(37,99,235,0)",
      backgroundColor:"rgba(37,99,235,.18)",
      pointRadius:0,
      fill:false,
      hidden:!toggles.error
    },
    {
      label:"vBGF 예측 오차 상한",
      data:vbgfUpper,
      borderColor:"rgba(255,91,127,0)",
      backgroundColor:"rgba(255,91,127,.16)",
      pointRadius:0,
      fill:"+1",
      hidden:isDeadFish || !(toggles.error && toggles.future)
    },
    {
      label:"vBGF 예측 오차 하한",
      data:vbgfLower,
      borderColor:"rgba(255,91,127,0)",
      backgroundColor:"rgba(255,91,127,.16)",
      pointRadius:0,
      fill:false,
      hidden:isDeadFish || !(toggles.error && toggles.future)
    },
    {
      label:"코메트 참고 오차 상한",
      data:cometUpper,
      borderColor:"rgba(126,87,194,0)",
      backgroundColor:"rgba(126,87,194,.06)",
      pointRadius:0,
      fill:"+1",
      hidden:isDeadFish || !(toggles.error && toggles.comet)
    },
    {
      label:"코메트 참고 오차 하한",
      data:cometLower,
      borderColor:"rgba(126,87,194,0)",
      backgroundColor:"rgba(126,87,194,.06)",
      pointRadius:0,
      fill:false,
      hidden:isDeadFish || !(toggles.error && toggles.comet)
    },
    {
      label:`FISH ${selectedGrowthFishId} 성장 이력`,
      data:observed,
      borderColor:"#2563eb",
      backgroundColor:"#2563eb",
      borderWidth:3,
      // FISH 3의 폐사일에는 파란 점을 그리지 않고 X만 표시한다.
      pointRadius:(ctx)=>{
        const row=graphRows[ctx.dataIndex];
        return isDeadFish && row && isGrowthDeathRow(row) ? 0 : 2.5;
      },
      pointHoverRadius:(ctx)=>{
        const row=graphRows[ctx.dataIndex];
        return isDeadFish && row && isGrowthDeathRow(row) ? 0 : 5;
      },
      tension:.22,
      spanGaps:false,
      fill:false,
      hidden:!toggles.past
    },
    {
      label:"향후 vBGF 예측",
      data:vbgf,
      borderColor:"#ff5b7f",
      backgroundColor:"#ff5b7f",
      borderWidth:2.5,
      borderDash:[7,5],
      pointRadius:0,
      tension:.25,
      spanGaps:false,
      fill:false,
      hidden:isDeadFish || !toggles.future
    },
    {
      label:"코메트 참고 성장",
      data:comet,
      borderColor:"#7e57c2",
      backgroundColor:"#7e57c2",
      borderWidth:1.5,
      pointRadius:0,
      tension:.22,
      spanGaps:false,
      fill:false,
      hidden:isDeadFish || !toggles.comet
    }
  ];

  const currentAnchorPlugin={
    id:"growthCurrentAnchor",
    afterDatasetsDraw(chart){
      if(isDeadFish || !toggles.past) return;
      const currentIndex=graphRows.findIndex(r=>r.timestamp===currentRow.timestamp);
      if(currentIndex<0) return;
      const meta=chart.getDatasetMeta(6);
      const point=meta.data[currentIndex];
      if(!point) return;
      const value=num(currentRow.estimated_length_cm,null);
      if(value===null) return;

      const ctx=chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.arc(point.x,point.y,6,0,Math.PI*2);
      ctx.fillStyle="#10b981";
      ctx.fill();
      ctx.lineWidth=2;
      ctx.strokeStyle="#ffffff";
      ctx.stroke();
      ctx.restore();
    }
  };

  const deathMarkerPlugin={
    id:"growthDeathMarker",
    afterDatasetsDraw(chart){
      if(!isDeadFish || !toggles.past) return;

      const deathIndex=graphRows.findIndex(r=>isGrowthDeathRow(r));
      if(deathIndex<0) return;

      const deathValue=num(graphRows[deathIndex].estimated_length_cm,null);
      if(deathValue===null) return;

      // dataset point의 렌더링 여부와 무관하게 x/y scale에서 직접 좌표를 계산한다.
      const x=chart.scales.x.getPixelForValue(deathIndex);
      const y=chart.scales.y.getPixelForValue(deathValue);
      if(!Number.isFinite(x) || !Number.isFinite(y)) return;

      const ctx=chart.ctx;
      const size=8;
      ctx.save();
      ctx.strokeStyle="#ef4444";
      ctx.lineWidth=4;
      ctx.lineCap="round";

      ctx.beginPath();
      ctx.moveTo(x-size,y-size);
      ctx.lineTo(x+size,y+size);
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(x+size,y-size);
      ctx.lineTo(x-size,y+size);
      ctx.stroke();

      ctx.fillStyle="#ef4444";
      ctx.font="bold 11px Arial";
      ctx.textAlign="center";
      ctx.textBaseline="bottom";
      ctx.fillText("폐사",x,y-13);
      ctx.restore();
    }
  };

  growthMainChartInst=new Chart(document.getElementById("growthMainChart"),{
    type:"line",
    data:{labels,datasets},
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{mode:"index",intersect:false},
      plugins:{
        legend:{display:false},
        tooltip:{
          callbacks:{
            label:(ctx)=>{
              if(ctx.raw===null) return "";
              if(ctx.dataset.label.includes("오차")) return "";
              return `${ctx.dataset.label}: ${Number(ctx.raw).toFixed(2)} cm`;
            }
          }
        }
      },
      scales:{
        x:{
          grid:{display:false},
          ticks:{font:{size:9},maxRotation:0,autoSkip:true,maxTicksLimit:12}
        },
        y:{
          // FISH 3은 1~4cm 고정 범위, 0.5cm 간격으로 표시한다.
          min:isDeadFish ? 1 : undefined,
          max:isDeadFish ? 4 : undefined,
          ticks:{
            font:{size:9},
            stepSize:isDeadFish ? 0.5 : undefined,
            callback:v=>v+"cm"
          },
          grid:{color:"rgba(0,0,0,.05)"}
        }
      }
    },
    plugins:[currentAnchorPlugin,deathMarkerPlugin]
  });
}

function getRecentFeedingRows(days=7){
  const now=new Date();
  const cutoff=new Date(now.getTime()-days*24*60*60*1000);

  return rowsUntilNow(FEEDING_ROWS)
    .filter(r=>{
      const t=new Date(r.timestamp);
      return !Number.isNaN(t.getTime()) && t>=cutoff && t<=now;
    })
    .sort(sortDesc);
}

function renderFeedingSelect(){
  // 최근 급이 반응 선택창은 현재 시각 기준 최근 7일 데이터만 표시
  const all=getRecentFeedingRows(7);
  const sel=document.getElementById("feedingTimeSelect");

  if(!all.length){
    sel.innerHTML='<option value="">최근 7일 급이 기록 없음</option>';
    sel.disabled=true;
    return;
  }

  sel.disabled=false;
  sel.innerHTML=all.map((r,i)=>`<option value="${i}">${formatTime(r.timestamp)} · ${r.status==="OK"?(num(r.frs_score,0).toFixed(1)+"점"):"분석불가"}</option>`).join("");
  renderFeedingDetail(0);
}

function renderFeedingDetail(index){
  // 선택창과 동일하게 최근 7일 범위의 급이 데이터만 사용
  const all=getRecentFeedingRows(7);
  const row=all[index];
  if(!row) return;
  const valid=validFeeding(all).filter(r=>new Date(r.timestamp)<=new Date(row.timestamp)).sort(sortDesc);
  const lastValid=valid[0];

  const scoreEl=document.getElementById("detailFrsScore");
  const statusEl=document.getElementById("detailFrsStatus");
  const isValid=row.status==="OK" && row.frs_score!=="";

  if(isValid){
    const score=num(row.frs_score,0);
    scoreEl.textContent=score.toFixed(1)+"점";
    scoreEl.style.color="#3476ef";
    statusEl.textContent=frsGrade(score);
    statusEl.className="status-chip";
    if(score>=60){
      statusEl.style.background="#e3f8ea";
      statusEl.style.color="#16a64a";
    }else if(score>=40){
      statusEl.style.background="#fff4df";
      statusEl.style.color="#d97706";
    }else{
      statusEl.style.background="#fdecec";
      statusEl.style.color="#c0392b";
    }
  }else{
    scoreEl.textContent="분석불가";
    scoreEl.style.color="#ef4444";
    statusEl.textContent="분석불가";
    statusEl.className="status-chip bad";
  }

  document.getElementById("detailFeedTime").textContent=formatTime(row.timestamp);
  document.getElementById("detailFeedAmount").textContent=row.feed_amount_g?row.feed_amount_g+"g":"--";
  document.getElementById("detailActivityIncrease").textContent=isValid?`+${num(row.activity_increase_pct,0).toFixed(1)}%`:"--";
  document.getElementById("detailLatency").textContent=isValid?`${num(row.response_latency_sec,0).toFixed(0)}초`:"--";

  const actScore=isValid?num(row.activity_score,0):0;
  const latScore=isValid?num(row.latency_score,0):0;
  document.getElementById("detailActivityScore").textContent=isValid?actScore.toFixed(1)+"점":"--";
  document.getElementById("detailLatencyScore").textContent=isValid?latScore.toFixed(1)+"점":"--";
  document.getElementById("detailActivityFill").style.width=isValid?Math.min(100,actScore)+"%":"0";
  document.getElementById("detailLatencyFill").style.width=isValid?Math.min(100,latScore)+"%":"0";

  document.getElementById("detailLastValid").textContent=lastValid
    ? `최근 유효 FRS ${num(lastValid.frs_score,0).toFixed(1)}점 / ${formatTime(lastValid.timestamp)}`
    : "최근 유효 FRS 없음";
  document.getElementById("detailValidMessage").textContent=isValid
    ? "선택한 이벤트는 정상적으로 FRS v2가 산출되었습니다."
    : "이번 급이는 분석불가 / 행동데이터 부족입니다. 과거 유효 점수는 참고값으로만 별도 표시합니다.";
}

function renderFeedingRecordPage(){
  const totalPages=Math.max(1,Math.ceil(FEEDING_TABLE_ROWS.length/FEEDING_RECORD_PAGE_SIZE));
  feedingRecordPage=Math.min(Math.max(1,feedingRecordPage),totalPages);

  const start=(feedingRecordPage-1)*FEEDING_RECORD_PAGE_SIZE;
  const pageRows=FEEDING_TABLE_ROWS.slice(start,start+FEEDING_RECORD_PAGE_SIZE);

  document.getElementById("feedingRecordBody").innerHTML=pageRows.length
    ? pageRows.map(r=>`
      <tr>
        <td>${formatTime(r.timestamp)}</td>
        <td>${r.feed_amount_g?Number(r.feed_amount_g).toFixed(1)+"g":"--"}</td>
        <td>${r.meal_no==="1"?"오전":"오후"}</td>
        <td>${r.status}</td>
      </tr>`).join("")
    : `<tr><td colspan="4" style="text-align:center;color:#9ca3af">급이 기록 없음</td></tr>`;

  document.getElementById("feedingPageInfo").textContent=`${feedingRecordPage} / ${totalPages}`;
  document.getElementById("feedingPrevPage").disabled=feedingRecordPage<=1;
  document.getElementById("feedingNextPage").disabled=feedingRecordPage>=totalPages;
}

function renderFeedingTables(){
  const all=rowsUntilNow(FEEDING_ROWS).sort(sortDesc);
  const now=new Date();
  const cutoff=new Date(now.getTime()-7*24*60*60*1000);

  // 급이 상세의 점수 현황은 현재 시각 기준 최근 7일까지만 사용
  FEEDING_TABLE_ROWS=all.filter(r=>{
    const t=new Date(r.timestamp);
    return t>=cutoff && t<=now;
  });

  feedingRecordPage=1;
  renderFeedingRecordPage();

  // 이벤트 결과 그래프는 최근 7일 전체 데이터를 그대로 표시
  renderFeedingEventChart(FEEDING_TABLE_ROWS);
}

function renderFeedingEventChart(rows){
  const ordered=[...rows].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));

  const labels=ordered.map(r=>{
    const t=formatTime(r.timestamp);
    return [t.slice(0,5), t.slice(6,11)];
  });

  const values=ordered.map(r=>{
    const valid=r.status==="OK" && r.frs_score!=="";
    return valid ? num(r.frs_score,0) : null;
  });

  if(feedingEventChartInst) feedingEventChartInst.destroy();

  const ctx=document.getElementById("feedingEventChart");
  feedingEventChartInst=new Chart(ctx,{
    type:"bar",
    data:{
      labels,
      datasets:[{
        label:"FRS v2",
        data:values,
        backgroundColor:"#2f80b9",
        borderColor:"#2f80b9",
        borderWidth:0,
        borderRadius:0,
        maxBarThickness:58,
        categoryPercentage:.78,
        barPercentage:.9
      }]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      layout:{padding:{top:20,right:8,left:0,bottom:0}},
      plugins:{
        legend:{display:false},
        tooltip:{
          callbacks:{
            label:(ctx)=>{
              if(ctx.raw===null) return "INSUFFICIENT_DATA";
              const row=ordered[ctx.dataIndex];
              return [
                `FRS v2: ${Number(ctx.raw).toFixed(1)}점`,
                `활동 증가: +${num(row.activity_increase_pct,0).toFixed(1)}%`,
                `반응지연: ${num(row.response_latency_sec,0).toFixed(0)}s`
              ];
            }
          }
        }
      },
      scales:{
        x:{
          grid:{display:false},
          ticks:{font:{size:10},color:"#475569"}
        },
        y:{
          beginAtZero:true,
          min:0,
          max:100,
          ticks:{stepSize:20,font:{size:10},color:"#475569"},
          title:{display:true,text:"점수",font:{size:11}},
          grid:{color:"rgba(100,116,139,.15)"}
        }
      }
    },
    plugins:[{
      id:"feedingBarValueLabels",
      afterDatasetsDraw(chart){
        const {ctx}=chart;
        ctx.save();
        ctx.font="11px Arial";
        ctx.fillStyle="#374151";
        ctx.textAlign="center";
        ctx.textBaseline="bottom";

        const meta=chart.getDatasetMeta(0);
        meta.data.forEach((bar,i)=>{
          const value=values[i];
          if(value===null) return;
          ctx.fillText(Number(value).toFixed(1),bar.x,bar.y-4);
        });
        ctx.restore();
      }
    }]
  });
}

async function loadCSV(){
  try{
    const [feedingRes, abrRes, activityRes, growthRes] = await Promise.all([
      fetch(FEEDING_CSV_URL,{cache:"no-store"}),
      fetch(ABR_CSV_URL,{cache:"no-store"}),
      fetch(ACTIVITY_CSV_URL,{cache:"no-store"}),
      fetch(GROWTH_CSV_URL,{cache:"no-store"})
    ]);

    if(!feedingRes.ok) throw new Error(`급이 CSV HTTP ${feedingRes.status}`);
    if(!abrRes.ok) throw new Error(`ABR CSV HTTP ${abrRes.status}`);
    if(!activityRes.ok) throw new Error(`Activity CSV HTTP ${activityRes.status}`);
    if(!growthRes.ok) throw new Error(`Growth CSV HTTP ${growthRes.status}`);

    const [feedingText, abrText, activityText, growthText] = await Promise.all([
      feedingRes.text(), abrRes.text(), activityRes.text(), growthRes.text()
    ]);

    FEEDING_ROWS=parseCSV(feedingText);
    ABR_ROWS=parseCSV(abrText);
    ACTIVITY_ROWS=parseCSV(activityText);
    GROWTH_ROWS=parseCSV(growthText);

    renderSummary();
    renderActivity();
    renderFRSMain();
    renderGrowthMain();
    renderFeedingSelect();
    renderFeedingTables();
  }catch(err){
    console.error(err);
    document.querySelectorAll(".footer-panel").forEach(el=>{
      if(el.textContent.includes("불러오는 중")) el.innerHTML=
        '<span class="red">CSV를 불러오지 못했습니다. static 경로와 파일 위치를 확인하세요.</span>';
    });
  }
}

document.getElementById("feedingDetailBtn").addEventListener("click",()=>document.getElementById("feedingModal").classList.add("open"));
document.querySelectorAll(".close-detail").forEach(btn=>btn.addEventListener("click",()=>document.getElementById(btn.dataset.close).classList.remove("open")));
document.querySelectorAll(".detail-modal").forEach(modal=>modal.addEventListener("click",e=>{if(e.target===modal)modal.classList.remove("open")}));

document.getElementById("feedingTimeSelect").addEventListener("change",e=>renderFeedingDetail(Number(e.target.value)));
document.getElementById("feedingPrevPage").addEventListener("click",()=>{
  if(feedingRecordPage>1){
    feedingRecordPage--;
    renderFeedingRecordPage();
  }
});
document.getElementById("feedingNextPage").addEventListener("click",()=>{
  const totalPages=Math.max(1,Math.ceil(FEEDING_TABLE_ROWS.length/FEEDING_RECORD_PAGE_SIZE));
  if(feedingRecordPage<totalPages){
    feedingRecordPage++;
    renderFeedingRecordPage();
  }
});
document.querySelectorAll(".growth-fish-btn").forEach(btn=>{
  btn.addEventListener("click",()=>{
    selectedGrowthFishId=Number(btn.dataset.fishId);
    renderGrowthMain();
  });
});

document.querySelectorAll(".growth-main-toggle").forEach(cb=>{
  cb.addEventListener("change",()=>renderGrowthMain());
});
document.getElementById("growthPeriodSelect").addEventListener("change",()=>renderGrowthMain());

loadCSV();


document.getElementById('sbToggle')?.addEventListener('click',toggleSb);
