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

function validFeeding(rows){ return rows.filter(r=>r.status==="OK" && r.frs_v2!==""); }

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
  // CSV의 activity_grade 값을 그대로 사용한다.
  const grade=String(row?.activity_grade || "").toUpperCase();
  return ["LOW","NORMAL","HIGH"].includes(grade) ? grade : "--";
}

function setActivityStateStyle(el, grade){
  const colors={
    LOW:"#3b82f6",
    NORMAL:"#10b981",
    HIGH:"#ef4444"
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

function renderSummary(){
  // 미래 mock 데이터는 제외하고 현재 시각 기준으로만 요약값을 선택한다.
  const abrRecent=rowsInRecentMinutes(ABR_ROWS,5).sort(sortDesc);
  const s=abrRecent.length ? abrRecent[0] : null;

  const activityRecent=rowsInRecentMinutes(ACTIVITY_ROWS,30).sort(sortDesc);
  const activityLatest=activityRecent.length ? activityRecent[0] : null;

  if(s){
    const abrRate=num(s.abr_5min_pct,0);
    document.getElementById("abrRate").innerHTML=`${abrRate.toFixed(1)}<small>%</small>`;

    // ABR 상태는 CSV 문자열에 의존하지 않고 이상행동률 기준으로 판정
    const abrStatus=abrGrade(abrRate);
    const abrStatusEl=document.getElementById("abrStatus");
    abrStatusEl.textContent=abrStatus;
    setAbrStatusStyle(abrStatusEl,abrStatus);

    document.getElementById("abrCount").textContent=(s.abnormal_count_5min || "0")+"회";
  }else{
    document.getElementById("abrRate").textContent="--";
    document.getElementById("abrStatus").textContent="--";
    document.getElementById("abrStatus").style.color="#6b7280";
    document.getElementById("abrCount").textContent="--";
  }

  if(activityLatest){
    const idx=num(activityLatest.activity_index,100);
    document.getElementById("actIndex").innerHTML=`${idx.toFixed(1)}<small> / 100</small>`;
    const diff=idx-100;
    document.getElementById("actCompare").textContent=`${diff>=0?"+":""}${diff.toFixed(1)}%`;
    document.getElementById("actCompare").style.color=diff>=0?"#10b981":"#ef4444";

    // LOW / NORMAL / HIGH는 CSV activity_grade에서 직접 읽음
    const actGrade=activityState(activityLatest);
    const actStateEl=document.getElementById("actState");
    actStateEl.textContent=actGrade;
    setActivityStateStyle(actStateEl,actGrade);

    // AI 분석품질은 최근 30분 데이터 전체에서 GOOD / FAIR / POOR 비율을 계산한다.
    // quality_*_pct 값이 CSV에 이미 존재하면 가장 최근 유효 품질값을 우선 사용하고,
    // 비어 있는 경우 quality / analysis_quality 계열의 등급 컬럼을 집계한다.
    const qualitySource=activityRecent.find(r=>
      r.quality_good_pct!=="" &&
      r.quality_fair_pct!=="" &&
      r.quality_poor_pct!==""
    );

    if(qualitySource){
      document.getElementById("qualityGood").textContent=num(qualitySource.quality_good_pct,0).toFixed(1)+"%";
      document.getElementById("qualityFair").textContent=num(qualitySource.quality_fair_pct,0).toFixed(1)+"%";
      document.getElementById("qualityPoor").textContent=num(qualitySource.quality_poor_pct,0).toFixed(1)+"%";
    }else{
      const qualityValues=activityRecent
        .map(r=>String(
          r.quality_grade ||
          r.analysis_quality ||
          r.ai_quality ||
          r.quality ||
          ""
        ).trim().toUpperCase())
        .filter(v=>["GOOD","FAIR","POOR"].includes(v));

      if(qualityValues.length){
        const total=qualityValues.length;
        const pct=grade=>qualityValues.filter(v=>v===grade).length/total*100;
        document.getElementById("qualityGood").textContent=pct("GOOD").toFixed(1)+"%";
        document.getElementById("qualityFair").textContent=pct("FAIR").toFixed(1)+"%";
        document.getElementById("qualityPoor").textContent=pct("POOR").toFixed(1)+"%";
      }else{
        document.getElementById("qualityGood").textContent="--";
        document.getElementById("qualityFair").textContent="--";
        document.getElementById("qualityPoor").textContent="--";
      }
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
  const vals=rows.map(r=>num(r.activity_index,100));
  const baseline=rows.map(()=>100);
  if(activityChartInst) activityChartInst.destroy();
  activityChartInst=new Chart(ctx,{
    type:"line",
    data:{
      labels,
      datasets:[
        {label:"Activity Index",data:vals,borderColor:"#3b82f6",backgroundColor:"rgba(59,130,246,.08)",pointRadius:3,borderWidth:2,tension:.25,fill:true},
        {label:"동일 시간대 baseline",data:baseline,borderColor:"#94a3b8",pointRadius:0,borderDash:[5,5],borderWidth:1.5}
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{
        x:{grid:{display:false},ticks:{font:{size:9}}},
        y:{suggestedMin:50,suggestedMax:150,ticks:{font:{size:9}},grid:{color:"rgba(0,0,0,.05)"}}
      }
    }
  });
}

function renderFRSMain(){
  // 현재 시각 이후의 예약/미래 mock 급이는 제외한다.
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
    (current.status==="OK" && current.frs_v2!=="")
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

  const sc=num(displayRow.frs_v2,0);
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
  const d=new Date(v+"T00:00:00");
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatGrowthDate(v){
  const d=parseGrowthDate(v);
  if(!d) return "--";
  return `${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

function renderGrowthMain(){
  const arr=[...GROWTH_ROWS]
    .filter(r=>r.date)
    .sort((a,b)=>parseGrowthDate(a.date)-parseGrowthDate(b.date));

  if(!arr.length) return;

  const now=new Date();
  const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const todayKey=[
    today.getFullYear(),
    String(today.getMonth()+1).padStart(2,"0"),
    String(today.getDate()).padStart(2,"0")
  ].join("-");

  // "우리 성장 이력"에는 주간 측정일(history/current_anchor)만 영구 보존한다.
  // current_temp 행은 해당 날짜가 오늘일 때만 임시 현재값으로 사용하고,
  // 날짜가 지나면 과거 성장 이력에서는 자동으로 제외한다.
  const weeklyHistoryRows=arr.filter(r=>{
    const d=parseGrowthDate(r.date);
    return d && d<=today &&
      r.observed_average_length_cm!=="" &&
      (r.phase==="history" || r.phase==="current_anchor");
  });

  const todayTempRow=arr.find(r=>
    r.date===todayKey &&
    r.phase==="current_temp" &&
    r.observed_average_length_cm!==""
  );

  const historyRows=todayTempRow
    ? [...weeklyHistoryRows, todayTempRow]
        .sort((a,b)=>parseGrowthDate(a.date)-parseGrowthDate(b.date))
    : weeklyHistoryRows;

  // 오늘 비주기 임시값이 있으면 그것을 현재값으로 표시.
  // 없으면 가장 최근 정식 주간 측정값을 현재값으로 사용한다.
  const currentRow=todayTempRow ||
    (weeklyHistoryRows.length ? weeklyHistoryRows[weeklyHistoryRows.length-1] : null);

  if(!currentRow || !historyRows.length) return;

  const first=historyRows[0];
  const current=num(currentRow.observed_average_length_cm,null);
  const currentError=num(currentRow.observed_error_cm,0);
  const firstValue=num(first.observed_average_length_cm,null);

  document.getElementById("growthAvgCurrent").innerHTML=
    current===null ? "--" : `${current.toFixed(2)}<small>cm</small>`;

  document.getElementById("growthErrorRange").textContent=
    current===null ? "--" : `±${currentError.toFixed(2)} cm`;

  document.getElementById("growthAvgDate").textContent=
    `${formatGrowthDate(currentRow.date)} 기준 현재 평균 추정체장${currentRow.phase==="current_temp" ? " · 임시값" : ""}`;

  const startDate=parseGrowthDate(first.date);
  const currentDate=parseGrowthDate(currentRow.date);
  const days=(startDate && currentDate)
    ? Math.max(1,(currentDate-startDate)/(1000*60*60*24))
    : null;

  document.getElementById("growthPeriod").textContent=
    days===null ? "--" : `${Math.round(days)}일`;

  const speed=(days && firstValue!==null && current!==null)
    ? (current-firstValue)/days
    : null;

  document.getElementById("growthSpeed").textContent=
    speed===null ? "--" : `+${speed.toFixed(3)} cm/day`;

  const futureDays=Number(document.getElementById("growthPeriodSelect")?.value || 180);
  renderGrowthMainChart(arr,currentRow,futureDays,today);
}

function renderGrowthMainChart(arr,currentRow,futureDays=180,today=null){
  const toggles={};
  document.querySelectorAll(".growth-main-toggle").forEach(
    c=>toggles[c.value]=c.checked
  );

  const anchorDate=parseGrowthDate(currentRow.date);
  const currentDay=today || anchorDate;
  const cutoffDate=anchorDate
    ? new Date(anchorDate.getTime()+futureDays*24*60*60*1000)
    : null;

  // 그래프 축 자체에서도 표시하지 않을 날짜를 제거한다.
  // - history / current_anchor : 정식 성장 이력으로 유지
  // - current_temp            : 오늘 날짜의 임시 현재값만 유지
  // - prediction              : 선택한 미래 기간까지만 유지
  //
  // 이전에는 current_temp 행을 데이터값만 null 처리했기 때문에
  // Chart.js의 X축에는 날짜가 남아 간격/곡선 모양에 영향을 주었다.
  arr=arr.filter(r=>{
    const d=parseGrowthDate(r.date);
    if(!d) return false;

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

  const labels=arr.map(r=>formatGrowthDate(r.date));

  // 과거 성장 이력은 정식 주간 측정점만 유지한다.
  // 비주기 current_temp 값은 "오늘"과 일치할 때만 그래프에 나타난다.
  const isVisibleObservedRow=r=>{
    const d=parseGrowthDate(r.date);
    if(!d || d>currentDay || r.observed_average_length_cm==="") return false;
    if(r.phase==="history" || r.phase==="current_anchor") return true;
    return r.phase==="current_temp" &&
      d.getFullYear()===currentDay.getFullYear() &&
      d.getMonth()===currentDay.getMonth() &&
      d.getDate()===currentDay.getDate();
  };

  const observed=arr.map(r=>
    isVisibleObservedRow(r) ? num(r.observed_average_length_cm,null) : null
  );

  const observedLower=arr.map(r=>
    isVisibleObservedRow(r) ? num(r.observed_lower_cm,null) : null
  );

  const observedUpper=arr.map(r=>
    isVisibleObservedRow(r) ? num(r.observed_upper_cm,null) : null
  );

  // vBGF: 현재점부터 미래 구간을 연결.
  // 현재점에 예측값이 없으면 관측값을 사용해 선이 끊기지 않게 한다.
  const vbgf=arr.map(r=>{
    const d=parseGrowthDate(r.date);
    if(!d || d<anchorDate) return null;
    if(d.getTime()===anchorDate.getTime()){
      return num(r.vbgf_predicted_length_cm,
        num(r.observed_average_length_cm,null));
    }
    return num(r.vbgf_predicted_length_cm,null);
  });

  const vbgfLower=arr.map(r=>{
    const d=parseGrowthDate(r.date);
    if(!d || d<anchorDate) return null;
    if(d.getTime()===anchorDate.getTime()){
      return num(r.vbgf_prediction_lower_cm,
        num(r.observed_lower_cm,null));
    }
    return num(r.vbgf_prediction_lower_cm,null);
  });

  const vbgfUpper=arr.map(r=>{
    const d=parseGrowthDate(r.date);
    if(!d || d<anchorDate) return null;
    if(d.getTime()===anchorDate.getTime()){
      return num(r.vbgf_prediction_upper_cm,
        num(r.observed_upper_cm,null));
    }
    return num(r.vbgf_prediction_upper_cm,null);
  });

  // 코메트 참고곡선: CSV 전체 날짜 범위
  const comet=arr.map(r=>num(r.comet_reference_length_cm,null));
  const cometLower=arr.map(r=>num(r.comet_reference_lower_cm,null));
  const cometUpper=arr.map(r=>num(r.comet_reference_upper_cm,null));

  if(growthMainChartInst) growthMainChartInst.destroy();

  const datasets=[
    // 관측 오차범위
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

    // vBGF 오차범위
    {
      label:"vBGF 예측 오차 상한",
      data:vbgfUpper,
      borderColor:"rgba(255,91,127,0)",
      backgroundColor:"rgba(255,91,127,.16)",
      pointRadius:0,
      fill:"+1",
      hidden:!(toggles.error && toggles.future)
    },
    {
      label:"vBGF 예측 오차 하한",
      data:vbgfLower,
      borderColor:"rgba(255,91,127,0)",
      backgroundColor:"rgba(255,91,127,.16)",
      pointRadius:0,
      fill:false,
      hidden:!(toggles.error && toggles.future)
    },

    // 코메트 참고 오차범위
    {
      label:"코메트 참고 오차 상한",
      data:cometUpper,
      borderColor:"rgba(126,87,194,0)",
      backgroundColor:"rgba(126,87,194,.06)",
      pointRadius:0,
      fill:"+1",
      hidden:!(toggles.error && toggles.comet)
    },
    {
      label:"코메트 참고 오차 하한",
      data:cometLower,
      borderColor:"rgba(126,87,194,0)",
      backgroundColor:"rgba(126,87,194,.06)",
      pointRadius:0,
      fill:false,
      hidden:!(toggles.error && toggles.comet)
    },

    // 우리 과거 성장: 실선
    {
      label:"우리 성장 이력",
      data:observed,
      borderColor:"#2563eb",
      backgroundColor:"#2563eb",
      borderWidth:3,
      pointRadius:2.5,
      pointHoverRadius:5,
      tension:.22,
      spanGaps:false,
      fill:false,
      hidden:!toggles.past
    },

    // 우리 미래 vBGF: 점선
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
      hidden:!toggles.future
    },

    // 코메트 참고: 얇은 비교선
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
      hidden:!toggles.comet
    }
  ];

  const currentAnchorPlugin={
    id:"growthCurrentAnchor",
    afterDatasetsDraw(chart){
      const currentIndex=arr.findIndex(r=>r.date===currentRow.date);
      if(currentIndex<0 || !toggles.past) return;

      const meta=chart.getDatasetMeta(6);
      const point=meta.data[currentIndex];
      if(!point) return;

      const value=num(currentRow.observed_average_length_cm,null);
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
          ticks:{
            font:{size:9},
            maxRotation:0,
            autoSkip:true,
            maxTicksLimit:12
          }
        },
        y:{
          ticks:{font:{size:9},callback:v=>v+"cm"},
          grid:{color:"rgba(0,0,0,.05)"}
        }
      }
    },
    plugins:[currentAnchorPlugin]
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
  sel.innerHTML=all.map((r,i)=>`<option value="${i}">${formatTime(r.timestamp)} · ${r.status==="OK"?(num(r.frs_v2,0).toFixed(1)+"점"):"분석불가"}</option>`).join("");
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
  const isValid=row.status==="OK" && row.frs_v2!=="";

  if(isValid){
    const score=num(row.frs_v2,0);
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
    ? `최근 유효 FRS ${num(lastValid.frs_v2,0).toFixed(1)}점 / ${formatTime(lastValid.timestamp)}`
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
    const valid=r.status==="OK" && r.frs_v2!=="";
    return valid ? num(r.frs_v2,0) : null;
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
document.querySelectorAll(".growth-main-toggle").forEach(cb=>{
  cb.addEventListener("change",()=>renderGrowthMain());
});
document.getElementById("growthPeriodSelect").addEventListener("change",()=>renderGrowthMain());

loadCSV();


document.getElementById('sbToggle')?.addEventListener('click',toggleSb);
