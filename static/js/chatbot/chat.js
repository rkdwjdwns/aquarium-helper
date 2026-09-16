const APP_CONFIG = document.getElementById('chatbotConfig').dataset;
const CSRF = APP_CONFIG.csrf;
const win  = document.getElementById('chatMessages');
win.scrollTop = win.scrollHeight;

function autoResize(el){ el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,120)+'px' }
function handleKey(e){ if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); sendMsg() } }

function esc(v){
  return String(v ?? '')
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
    .replaceAll('"','&quot;').replaceAll("'",'&#039;');
}

async function sendMsg(){
  const input   = document.getElementById('chatInput');
  const message = input.value.trim();
  if(!message) return;
  input.value = ''; autoResize(input);

  win.innerHTML += `
    <div class="msg-row user">
      <div class="msg-avatar" style="background:#2f69ef;color:#fff">나</div>
      <div><div class="msg-bubble">${esc(message)}</div></div>
    </div>`;
  win.scrollTop = win.scrollHeight;

  const lid = 'load-'+Date.now();
  win.innerHTML += `
    <div id="${lid}" class="msg-row ai">
      <div class="msg-avatar">🤖</div>
      <div><div class="msg-bubble" style="color:#a2adbc">···</div></div>
    </div>`;
  win.scrollTop = win.scrollHeight;

  try{
    const res  = await fetch('/chatbot/ask/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':CSRF},body:JSON.stringify({message})});
    const data = await res.json();
    document.getElementById(lid)?.remove();
    const reply = data.reply || data.response || '응답을 받지 못했습니다.';
    const now   = new Date().toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'});
    win.innerHTML += `
      <div class="msg-row ai">
        <div class="msg-avatar">🤖</div>
        <div><div class="msg-bubble">${esc(reply)}</div><div class="msg-time">${now}</div></div>
      </div>`;
  }catch{
    document.getElementById(lid)?.remove();
    win.innerHTML += `<div class="msg-row ai"><div class="msg-avatar">🤖</div><div><div class="msg-bubble" style="color:#ef4444">서버 연결 실패</div></div></div>`;
  }
  win.scrollTop = win.scrollHeight;
}


const chatInputEl=document.getElementById('chatInput');
const chatSendBtn=document.getElementById('chatSendBtn');
if(chatInputEl){
  chatInputEl.addEventListener('keydown',handleKey);
  chatInputEl.addEventListener('input',()=>autoResize(chatInputEl));
}
if(chatSendBtn) chatSendBtn.addEventListener('click',sendMsg);
