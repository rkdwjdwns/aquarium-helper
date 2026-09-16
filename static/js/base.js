setTimeout(()=>{document.querySelectorAll('[style*="position:fixed"][style*="top:96px"]').forEach(el=>{el.style.opacity='0';el.style.transition='opacity .4s';setTimeout(()=>el.remove(),400)})},2500)

// ── 이상 경고(알림 벨) ──────────────────────────
const ALERT_LEVEL_COLOR = {DANGER:'#ef4444', WARNING:'#f59e0b', INFO:'#3b82f6'};

async function fetchAlerts(){
  try{
    const res = await fetch('/monitoring/api/alerts/');
    const data = await res.json();
    const badge = document.getElementById('alertBadge');
    const list  = document.getElementById('alertList');
    if(!badge || !list) return;

    if(data.count > 0){
      badge.style.display = 'flex';
      badge.textContent = data.count > 9 ? '9+' : data.count;
    } else {
      badge.style.display = 'none';
    }

    if(!data.alerts.length){
      list.innerHTML = '<div style="padding:24px;text-align:center;color:#9ca3af;font-size:13px">현재 이상 경고가 없습니다.</div>';
      return;
    }

    list.innerHTML = data.alerts.map(a => {
      const color = ALERT_LEVEL_COLOR[a.level] || '#6b7280';
      const actions = (a.actions || []).slice(0,3).map(x => `<li style="margin-bottom:2px">${x}</li>`).join('');
      const time = new Date(a.detected_at).toLocaleString('ko-KR', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'});
      return `
        <div style="padding:12px 10px;border-radius:12px;margin-bottom:6px;background:#f8fafc">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="font-size:13px;font-weight:900;color:${color}">● ${a.title}</span>
            <span style="font-size:10px;color:#9ca3af">${time}</span>
          </div>
          <div style="font-size:11px;color:#6b7280;margin-bottom:6px">${a.tank_name}${a.current_value != null ? ' · 측정값 ' + a.current_value : ''}</div>
          ${actions ? `<ul style="margin:0;padding-left:16px;font-size:11px;color:#4b5564">${actions}</ul>` : ''}
        </div>`;
    }).join('');
  }catch(e){ /* 조용히 무시 — 알림 조회 실패가 페이지 전체를 방해하면 안 됨 */ }
}

function toggleAlerts(){
  const dd = document.getElementById('alertDropdown');
  if(!dd) return;
  dd.style.display = dd.style.display === 'block' ? 'none' : 'block';
}

document.addEventListener('click', function(e){
  const dd = document.getElementById('alertDropdown');
  const btn = document.getElementById('alertBellBtn');
  if(dd && dd.style.display === 'block' && !dd.contains(e.target) && e.target !== btn && !btn.contains(e.target)){
    dd.style.display = 'none';
  }
});

if(document.getElementById('alertBellBtn')){
  fetchAlerts();
  setInterval(fetchAlerts, 30000);
}

if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{
    navigator.serviceWorker.register('/static/service-worker.js')
      .then(r=>console.log('[PWA] SW:',r.scope)).catch(e=>console.warn('[PWA]',e));
  });
}
window.addEventListener('beforeinstallprompt',e=>e.preventDefault());


const googleFontStylesheet=document.getElementById('googleFontStylesheet');
if(googleFontStylesheet){
  const activateGoogleFont=()=>{ googleFontStylesheet.media='all'; };
  googleFontStylesheet.addEventListener('load',activateGoogleFont,{once:true});
  if(googleFontStylesheet.sheet) activateGoogleFont();
}
document.getElementById('alertBellBtn')?.addEventListener('click',toggleAlerts);
