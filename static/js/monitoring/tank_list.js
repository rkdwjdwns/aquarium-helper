function openModal(){ document.getElementById('modalBackdrop').classList.add('open') }
function closeModal(){
  document.getElementById('modalBackdrop').classList.remove('open');
  closePiMenu();
}
document.getElementById('modalBackdrop').addEventListener('click', e => { if(e.target===e.currentTarget) closeModal() })

function togglePiMenu(){
  const menu=document.getElementById('piMenu');
  const trigger=document.getElementById('piTrigger');
  const willOpen=!menu.classList.contains('open');
  menu.classList.toggle('open',willOpen);
  trigger.classList.toggle('open',willOpen);
}

function closePiMenu(){
  document.getElementById('piMenu')?.classList.remove('open');
  document.getElementById('piTrigger')?.classList.remove('open');
}

function selectPi(value,label){
  document.getElementById('piDeviceInput').value=value;
  document.getElementById('piSelectedTitle').textContent=label;
  document.getElementById('piSelectedSub').textContent='데모용 Raspberry Pi 장치가 선택되었습니다';
  document.getElementById('piTrigger').style.borderColor='#536ae8';
  closePiMenu();
}

document.addEventListener('click',e=>{
  const picker=document.getElementById('piPicker');
  if(picker && !picker.contains(e.target)) closePiMenu();
});

function toggleAll(el){ document.querySelectorAll('.row-check').forEach(c => c.checked = el.checked) }

function confirmDelete(){
  const checked = [...document.querySelectorAll('.row-check:checked')];
  if(!checked.length){ alert('삭제할 어항을 선택해 주세요.'); return; }
  if(confirm('선택한 어항을 삭제하시겠습니까?')){ document.getElementById('deleteForm').submit() }
}


document.getElementById('openTankModalBtn')?.addEventListener('click',openModal);
document.getElementById('deleteTanksBtn')?.addEventListener('click',confirmDelete);
document.getElementById('allCheck')?.addEventListener('change',e=>toggleAll(e.currentTarget));
document.getElementById('piTrigger')?.addEventListener('click',togglePiMenu);
document.querySelectorAll('.pi-option[data-pi-value]').forEach(btn=>btn.addEventListener('click',()=>selectPi(btn.dataset.piValue,btn.dataset.piLabel)));
document.getElementById('closeTankModalBtn')?.addEventListener('click',closeModal);
