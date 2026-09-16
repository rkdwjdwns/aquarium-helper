function toggleSb(){
  const sb=document.getElementById('sidebar');sb.classList.toggle('collapsed');
  const c=sb.classList.contains('collapsed');
  document.getElementById('sbToggle').textContent=c?'›':'‹';
  document.getElementById('mainContent').style.marginLeft=c?'44px':'var(--sw)';
}

(function(){
  const pagination = document.querySelector('.pagination[data-current-page]');
  if (!pagination) return;

  const currentPage = Number(pagination.dataset.currentPage || 1);
  const totalPages = Number(pagination.dataset.totalPages || 1);
  const tankId = pagination.dataset.tankId || '';
  const level = pagination.dataset.level || '';
  const sort = pagination.dataset.sort || 'desc';
  const groupSize = 10;

  const group = document.getElementById('pageNumberGroup');
  const prevBtn = document.getElementById('pagePrevGroup');
  const nextBtn = document.getElementById('pageNextGroup');

  const start = Math.floor((currentPage - 1) / groupSize) * groupSize + 1;
  const end = Math.min(start + groupSize - 1, totalPages);

  function buildUrl(page){
    const params = new URLSearchParams();
    params.set('page', page);
    if (tankId) params.set('tank_id', tankId);
    if (level) params.set('level', level);
    if (sort) params.set('sort', sort);
    return '?' + params.toString();
  }

  for (let page = start; page <= end; page++) {
    const a = document.createElement('a');
    a.href = buildUrl(page);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'page-btn' + (page === currentPage ? ' active' : '');
    btn.textContent = page;
    if (page === currentPage) btn.setAttribute('aria-current', 'page');

    a.appendChild(btn);
    group.appendChild(a);
  }

  const hasPrevGroup = start > 1;
  const hasNextGroup = end < totalPages;

  prevBtn.disabled = !hasPrevGroup;
  prevBtn.style.opacity = hasPrevGroup ? '1' : '.35';
  prevBtn.style.cursor = hasPrevGroup ? 'pointer' : 'default';

  nextBtn.disabled = !hasNextGroup;
  nextBtn.style.opacity = hasNextGroup ? '1' : '.35';
  nextBtn.style.cursor = hasNextGroup ? 'pointer' : 'default';

  if (hasPrevGroup) {
    prevBtn.addEventListener('click', () => {
      window.location.href = buildUrl(Math.max(1, start - groupSize));
    });
  }

  if (hasNextGroup) {
    nextBtn.addEventListener('click', () => {
      window.location.href = buildUrl(start + groupSize);
    });
  }
})();
