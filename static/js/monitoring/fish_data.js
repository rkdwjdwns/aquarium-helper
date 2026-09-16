const APP_CONFIG = document.getElementById('fishDataConfig').dataset;
const TANK_ID = Number(APP_CONFIG.tankId);
const FEEDING_CSV_URL = APP_CONFIG.feedingUrl;
const ZONE_CSV_URL = APP_CONFIG.zoneUrl;

function toggleSb(){
  const sb=document.getElementById('sidebar');sb.classList.toggle('collapsed');
  const c=sb.classList.contains('collapsed');
  document.getElementById('sbToggle').textContent=c?'›':'‹';
  const main=document.getElementById('mainContent');
  main.style.marginLeft=c?'44px':'var(--sw)';
}

function f2(v){const n=parseFloat(v);return isNaN(n)?'--':n.toFixed(2);}
async function sf(url){try{const r=await fetch(url);return r.ok?await r.json():null;}catch{return null;}}

function parseCSV(text){
  const rows=[]; let row=[], cell='', quoted=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i], next=text[i+1];
    if(ch==='"'){ if(quoted && next==='"'){cell+='"';i++;} else quoted=!quoted; }
    else if(ch===',' && !quoted){row.push(cell);cell='';}
    else if((ch==='\n'||ch==='\r') && !quoted){
      if(ch==='\r' && next==='\n') i++;
      row.push(cell);cell='';
      if(row.some(v=>v!=='')) rows.push(row);
      row=[];
    }else cell+=ch;
  }
  if(cell!==''||row.length){row.push(cell);rows.push(row);}
  const headers=rows.shift().map(h=>h.replace(/^\uFEFF/,'').trim());
  return rows.map(r=>Object.fromEntries(headers.map((h,i)=>[h,(r[i]??'').trim()])));
}

const maxH=176;

function niceFeedAxisMax(value){
  const v=Number(value);
  if(!Number.isFinite(v) || v<=0) return 0.5;

  // 최고 막대가 차트 천장에 붙지 않도록 약 15% 여유를 둔다.
  const padded=v*1.15;
  const exponent=Math.floor(Math.log10(padded));
  const base=Math.pow(10,exponent);
  const fraction=padded/base;

  let niceFraction;
  if(fraction<=1) niceFraction=1;
  else if(fraction<=2) niceFraction=2;
  else if(fraction<=2.5) niceFraction=2.5;
  else if(fraction<=5) niceFraction=5;
  else niceFraction=10;

  return niceFraction*base;
}

// ──────────────────────────────────────────────
// 급이량 차트 (feeding_analysis CSV 기반)
// ──────────────────────────────────────────────
let FEED=null; // {labels, am, pm}

function playFeedSwitchAnimation(){
  const bars=document.getElementById('feedingBars');
  const yWrap=document.getElementById('feedingY');

  if(!bars || !yWrap) return;

  bars.classList.remove('is-switching');
  yWrap.classList.remove('is-switching');

  // 같은 애니메이션을 연속 클릭해도 다시 재생되게 강제 reflow
  void bars.offsetWidth;
  void yWrap.offsetWidth;

  bars.classList.add('is-switching');
  yWrap.classList.add('is-switching');

  window.setTimeout(()=>{
    bars.classList.remove('is-switching');
    yWrap.classList.remove('is-switching');
  },700);
}

function renderFeed(key){
  const bars=document.getElementById('feedingBars');
  const yWrap=document.getElementById('feedingY');
  if(!FEED || !FEED.labels || !FEED.labels.length){
    bars.innerHTML='<div class="empty-note">최근 7일간 급이 기록이 없습니다.</div>';
    return;
  }
  const totals=FEED.labels.map((_,i)=>{
    if(key==='am') return FEED.am[i];
    if(key==='pm') return FEED.pm[i];
    return FEED.am[i]+FEED.pm[i];
  });
  const dataMax = Math.max(...totals, 0);
  const maxV = niceFeedAxisMax(dataMax);

  yWrap.innerHTML = [1,0.75,0.5,0.25,0]
    .map(r=>`<span>${(maxV*r).toFixed(2)}</span>`)
    .join('');

  bars.innerHTML='';
  FEED.labels.forEach((day,i)=>{
    const a = key==='pm' ? 0 : FEED.am[i];
    const b = key==='am' ? 0 : FEED.pm[i];
    const aH=Math.round((a/maxV)*maxH);
    const bH=Math.round((b/maxV)*maxH);
    const total=(a+b).toFixed(3);
    bars.innerHTML+=`<div class="bar-grp">
      <div class="bar-val">${total}g</div>
      <div class="bar-stack" style="height:${Math.max(aH+bH,2)}px">
        <div class="seg-b" style="height:${bH}px"></div>
        <div class="seg-a" style="height:${aH}px"></div>
      </div>
      <div class="bar-lbl">${day}</div>
    </div>`;
  });

  playFeedSwitchAnimation();
}

function setFeed(key,btn){
  document.querySelectorAll('.time-tabs button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  renderFeed(key);
}

function parseFeedDateTime(value){
  if(!value) return null;

  // CSV 예: 2026-09-08 18:00:00+09:00
  // 브라우저 호환성을 위해 날짜/시간 사이 공백을 T로 변환
  const normalized=String(value).trim().replace(' ','T');
  const d=new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatFeedDay(date){
  return `${date.getMonth()+1}/${date.getDate()}`;
}

async function fetchFeeding(){
  try{
    const r=await fetch(FEEDING_CSV_URL,{cache:'no-store'});
    if(!r.ok) throw new Error(`feeding csv HTTP ${r.status}`);

    const rows=parseCSV(await r.text())
      .map(row=>({
        ...row,
        _date:parseFeedDateTime(row.timestamp),
        _amount:Number(row.feed_amount_g)
      }))
      .filter(row=>row._date && Number.isFinite(row._amount));

    if(!rows.length){
      FEED={labels:[],am:[],pm:[]};
      renderFeed('all');
      return;
    }

    // 브라우저의 실제 현재 시각을 기준으로 최근 7일을 표시한다.
    // 오늘 날짜도 포함하며, 현재 시각 이후의 미래 급이 기록은 제외한다.
    const now=new Date();
    const latest=new Date(now);
    latest.setHours(0,0,0,0);

    const days=Array.from({length:7},(_,i)=>{
      const d=new Date(latest);
      d.setDate(latest.getDate()-(6-i));
      return d;
    });

    const dayKey=d=>{
      const y=d.getFullYear();
      const m=String(d.getMonth()+1).padStart(2,'0');
      const day=String(d.getDate()).padStart(2,'0');
      return `${y}-${m}-${day}`;
    };

    const daily=Object.fromEntries(
      days.map(d=>[dayKey(d),{am:0,pm:0}])
    );

    rows.forEach(row=>{
      // 현재 시각 이후에 기록된 미래 mock 데이터는 급이량에 포함하지 않는다.
      if(row._date>now) return;

      const key=dayKey(row._date);
      if(!daily[key]) return;

      // 오전/오후 구간은 CSV timestamp 시각으로 구분
      const period=row._date.getHours()<12 ? 'am' : 'pm';
      daily[key][period]+=row._amount;
    });

    FEED={
      labels:days.map(formatFeedDay),
      am:days.map(d=>Number(daily[dayKey(d)].am.toFixed(3))),
      pm:days.map(d=>Number(daily[dayKey(d)].pm.toFixed(3)))
    };

    renderFeed('all');
  }catch(e){
    console.error('[feeding csv]',e);
    FEED={labels:[],am:[],pm:[]};
    document.getElementById('feedingBars').innerHTML=
      '<div class="empty-note">급이량 CSV를 불러오지 못했습니다.</div>';
  }
}

// ──────────────────────────────────────────────
// 영역 분포 CSV
// ──────────────────────────────────────────────
let zoneChartInst=null;

async function fetchZoneDistribution(){
  try{
    const r=await fetch(ZONE_CSV_URL,{cache:'no-store'});
    if(!r.ok) throw new Error(`zone csv HTTP ${r.status}`);
    const rows=parseCSV(await r.text());

    // 현재 날짜 기준 '어제'의 00:00~23:59 데이터만 그래프/해설에 사용한다.
    const now=new Date();
    const yesterday=new Date(now.getFullYear(),now.getMonth(),now.getDate());
    yesterday.setDate(yesterday.getDate()-1);

    const dayKey=d=>{
      const y=d.getFullYear();
      const m=String(d.getMonth()+1).padStart(2,'0');
      const day=String(d.getDate()).padStart(2,'0');
      return `${y}-${m}-${day}`;
    };

    const yesterdayKey=dayKey(yesterday);

    const hourly=rows
      .filter(r=>r.row_type==='hourly' && r.date===yesterdayKey)
      .sort((a,b)=>Number(a.hour)-Number(b.hour));

    const periodText=`(${yesterday.getMonth()+1}/${yesterday.getDate()} 00:00~23:59)`;
    const periodEl=document.getElementById('zonePeriodLabel');
    const summaryPeriodEl=document.getElementById('zoneSummaryPeriodLabel');
    if(periodEl) periodEl.textContent=periodText;
    if(summaryPeriodEl) summaryPeriodEl.textContent=`(${yesterday.getMonth()+1}/${yesterday.getDate()} 24시간 분포 기반 자동 해석)`;

    if(!hourly.length){
      if(zoneChartInst){
        zoneChartInst.destroy();
        zoneChartInst=null;
      }
      document.getElementById('zoneSummaryBody').innerHTML=
        `<tr><td colspan="3" class="empty-note">${yesterday.getMonth()+1}/${yesterday.getDate()} 영역 분포 데이터가 없습니다.</td></tr>`;
      return;
    }

    const zoneKeys=[
      {zone:'TOP', key:'top_pct'},
      {zone:'MID', key:'mid_pct'},
      {zone:'BOT', key:'bot_pct'}
    ];

    const avgMap={};
    zoneKeys.forEach(z=>{
      const vals=hourly.map(r=>Number(r[z.key])).filter(Number.isFinite);
      avgMap[z.zone]=vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : 0;
    });

    const ranked=[...zoneKeys].sort((a,b)=>avgMap[b.zone]-avgMap[a.zone]);
    const highest=ranked[0]?.zone;
    const second=ranked[1]?.zone;
    const lowest=ranked[2]?.zone;

    function percentile(values,p){
      const arr=[...values].filter(Number.isFinite).sort((a,b)=>a-b);
      if(!arr.length) return 0;
      const idx=(arr.length-1)*p;
      const lo=Math.floor(idx), hi=Math.ceil(idx);
      if(lo===hi) return arr[lo];
      return arr[lo]+(arr[hi]-arr[lo])*(idx-lo);
    }

    function formatActivePeriod(zone){
      const zoneInfo=zoneKeys.find(z=>z.zone===zone);
      if(!zoneInfo) return '특정 시간대 활동 증가';
      const vals=hourly.map(r=>Number(r[zoneInfo.key]));
      const threshold=percentile(vals,.75);

      const activeHours=hourly
        .filter(r=>Number(r[zoneInfo.key])>=threshold)
        .map(r=>Number(r.hour))
        .sort((a,b)=>a-b);

      if(!activeHours.length) return '특정 시간대 활동 증가';

      // 가장 긴 연속 시간대 구간을 선택
      const ranges=[];
      let start=activeHours[0], prev=activeHours[0];

      for(let i=1;i<activeHours.length;i++){
        const h=activeHours[i];
        if(h===prev+1){
          prev=h;
        }else{
          ranges.push([start,prev]);
          start=prev=h;
        }
      }
      ranges.push([start,prev]);

      ranges.sort((a,b)=>(b[1]-b[0])-(a[1]-a[0]));
      const best=ranges[0];
      const startText=String(best[0]).padStart(2,'0');
      const endText=String(best[1]).padStart(2,'0');

      return best[0]===best[1]
        ? `${startText}시경 활동 비율이 상대적으로 높음`
        : `${startText}~${endText}시 활동 비율이 상대적으로 높음`;
    }

    function zoneDescription(zone){
      if(zone===highest) return '주활동 영역';
      if(zone===lowest) return '최근 카메라 기준에서는 체류 비율이 낮음';
      if(zone===second) return formatActivePeriod(zone);
      return '-';
    }

    document.getElementById('zoneSummaryBody').innerHTML = zoneKeys.map(z=>`
      <tr>
        <td><strong>${z.zone}</strong></td>
        <td>${avgMap[z.zone].toFixed(1)}%</td>
        <td>${zoneDescription(z.zone)}</td>
      </tr>`).join('');

    const labels=hourly.map(r=>`${r.hour}시`);
    const top=hourly.map(r=>Number(r.top_pct));
    const mid=hourly.map(r=>Number(r.mid_pct));
    const bot=hourly.map(r=>Number(r.bot_pct));

    if(zoneChartInst) zoneChartInst.destroy();
    zoneChartInst=new Chart(document.getElementById('zoneChart'),{
      type:'line',
      data:{labels,datasets:[
        {label:'TOP',data:top,borderColor:'#2f80b9',backgroundColor:'#2f80b9',pointRadius:0,borderWidth:0,tension:.25,fill:true,stack:'zone'},
        {label:'MID',data:mid,borderColor:'#ff8c2a',backgroundColor:'#ff8c2a',pointRadius:0,borderWidth:0,tension:.25,fill:true,stack:'zone'},
        {label:'BOT',data:bot,borderColor:'#43a843',backgroundColor:'#43a843',pointRadius:0,borderWidth:0,tension:.25,fill:true,stack:'zone'}
      ]},
      options:{
        responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:{callbacks:{label:(ctx)=>`${ctx.dataset.label}: ${Number(ctx.raw).toFixed(1)}%`}}},
        scales:{
          x:{stacked:true,grid:{display:false},ticks:{color:'#64748b',font:{size:9},callback:(v,i)=>i%2===0?labels[i]:''}},
          y:{stacked:true,min:0,max:100,ticks:{stepSize:20,color:'#64748b',font:{size:9},callback:v=>v+'%'},title:{display:true,text:'비율 (%)',font:{size:10}},grid:{color:'rgba(0,0,0,.05)'}}
        }
      }
    });
  }catch(e){
    console.error('[zone csv]',e);
    document.getElementById('zoneSummaryBody').innerHTML='<tr><td colspan="3" class="empty-note">영역 분포 CSV를 불러오지 못했습니다.</td></tr>';
  }
}

async function loadAll(){
  await Promise.allSettled([fetchFeeding(), fetchZoneDistribution()]);
}
loadAll();
setInterval(loadAll, 30000);
