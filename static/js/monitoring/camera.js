const APP_CONFIG = document.getElementById('cameraConfig').dataset;
const TANK_ID = Number(APP_CONFIG.tankId);

// 사이드바
function toggleSb(){
  const sb=document.getElementById('sidebar');
  sb.classList.toggle('collapsed');
  const c=sb.classList.contains('collapsed');
  document.getElementById('sbToggle').textContent=c?'›':'‹';
  document.getElementById('mainContent').style.marginLeft=c?'44px':'var(--sw)';
}
setInterval(()=>document.getElementById('stream-time')&&(document.getElementById('stream-time').textContent=new Date().toLocaleTimeString('ko-KR')),1000);


// 구역 오버레이
let zoneOn=false;
function toggleZone(){
  zoneOn=!zoneOn;
  const btn=document.getElementById('zoneBtn');
  let cv=document.getElementById('zoneCv');
  if(zoneOn){
    if(!cv){cv=document.createElement('canvas');cv.id='zoneCv';cv.style.cssText='position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;opacity:.6;';document.getElementById('videoFrame').appendChild(cv);}
    const w=cv.parentElement.offsetWidth,h=cv.parentElement.offsetHeight;
    cv.width=w;cv.height=h;
    const ctx=cv.getContext('2d');
    [{label:'TOP',y:0,h:h/3,c:'rgba(239,68,68,.15)',b:'rgba(239,68,68,.6)'},{label:'MID',y:h/3,h:h/3,c:'rgba(59,130,246,.1)',b:'rgba(59,130,246,.5)'},{label:'BOT',y:h*2/3,h:h/3,c:'rgba(16,185,129,.1)',b:'rgba(16,185,129,.5)'}].forEach(z=>{
      ctx.fillStyle=z.c;ctx.fillRect(0,z.y,w,z.h);
      ctx.strokeStyle=z.b;ctx.lineWidth=1.5;ctx.setLineDash([6,4]);ctx.strokeRect(2,z.y+2,w-4,z.h-4);
      ctx.font='bold 13px sans-serif';ctx.fillStyle=z.b;ctx.setLineDash([]);ctx.fillText(z.label,14,z.y+22);
    });
    btn.classList.add('active');
  } else {cv?.remove();btn.classList.remove('active');}
}
function toggleFs(){const el=document.getElementById('streamWrap');if(!document.fullscreenElement)el.requestFullscreen?.();else document.exitFullscreen?.();}


// ngrok Raspberry Pi MJPEG 라이브 스트림
const STREAM_URL = "https://graded-reoccupy-unbounded.ngrok-free.dev/stream.mjpg";
const liveStream = document.getElementById('liveStream');

function setConnectionState(connected){
  const dot=document.getElementById('liveDot');
  const badge=document.getElementById('connBadge');
  if(dot){
    dot.style.background=connected?'#ef4444':'#6b7280';
    dot.style.animation=connected?'pulse 1s infinite':'none';
  }
  if(badge){
    badge.style.background=connected?'#e6f9f0':'#fee2e2';
    badge.style.color=connected?'#1a7f5a':'#b91c1c';
    badge.innerHTML=connected
      ? '<span style="width:8px;height:8px;border-radius:50%;background:#10b981"></span>카메라 연결됨'
      : '<span style="width:8px;height:8px;border-radius:50%;background:#ef4444"></span>카메라 연결 끊김';
  }
}

function reconnectStream(){
  if(!liveStream) return;
  setConnectionState(false);
  const sep=STREAM_URL.includes('?')?'&':'?';
  liveStream.src=STREAM_URL+sep+'_='+Date.now();
}

if(liveStream){
  liveStream.addEventListener('load',()=>setConnectionState(true));
  liveStream.addEventListener('error',()=>setConnectionState(false));
}


document.getElementById('sbToggle')?.addEventListener('click',toggleSb);
document.getElementById('zoneBtn')?.addEventListener('click',toggleZone);
document.getElementById('fullscreenBtn')?.addEventListener('click',toggleFs);
document.getElementById('reconnectBtn')?.addEventListener('click',reconnectStream);
