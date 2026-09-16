function toggleSb(){
  const sb = document.getElementById('sidebar');
  sb.classList.toggle('collapsed');
  const collapsed = sb.classList.contains('collapsed');
  document.getElementById('sbToggle').textContent = collapsed ? '›' : '‹';
  document.getElementById('mainContent').style.marginLeft = collapsed ? '44px' : 'var(--sw)';
}


document.getElementById('sbToggle')?.addEventListener('click',toggleSb);
const reportSortSelect=document.getElementById('reportSortSelect');
if(reportSortSelect){
  reportSortSelect.addEventListener('change',()=>{
    window.location.href=`?tank_id=${encodeURIComponent(reportSortSelect.dataset.tankId)}&sort=${encodeURIComponent(reportSortSelect.value)}`;
  });
}
