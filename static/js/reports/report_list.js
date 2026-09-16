function toggleSb(){
  const sb = document.getElementById('sidebar');
  sb.classList.toggle('collapsed');
  const collapsed = sb.classList.contains('collapsed');
  document.getElementById('sbToggle').textContent = collapsed ? '›' : '‹';
  document.getElementById('mainContent').style.marginLeft = collapsed ? '44px' : 'var(--sw)';
}
