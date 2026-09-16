(function(){
      const pagination = document.querySelector('.pagination[data-current-page]');
      if (!pagination) return;

      const currentPage = parseInt(pagination.getAttribute('data-current-page') || '1', 10);
      const totalPages = parseInt(pagination.getAttribute('data-total-pages') || '1', 10);
      const tankId = pagination.getAttribute('data-tank-id') || '';
      const level = pagination.getAttribute('data-level') || '';
      const groupSize = 10;

      const numberGroup = document.getElementById('pageNumberGroup');
      const prevBtn = document.getElementById('pagePrevGroup');
      const nextBtn = document.getElementById('pageNextGroup');

      if (!numberGroup || !prevBtn || !nextBtn) return;

      const groupStart = Math.floor((currentPage - 1) / groupSize) * groupSize + 1;
      const groupEnd = Math.min(groupStart + groupSize - 1, totalPages);

      function pageUrl(page) {
        const parts = ['page=' + encodeURIComponent(page)];
        if (tankId) parts.push('tank_id=' + encodeURIComponent(tankId));
        if (level) parts.push('level=' + encodeURIComponent(level));
        return '?' + parts.join('&');
      }

      numberGroup.innerHTML = '';

      for (let page = groupStart; page <= groupEnd; page++) {
        const a = document.createElement('a');
        a.href = pageUrl(page);
        a.style.textDecoration = 'none';

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'page-btn' + (page === currentPage ? ' active' : '');
        btn.textContent = String(page);

        if (page === currentPage) {
          btn.setAttribute('aria-current', 'page');
        }

        a.appendChild(btn);
        numberGroup.appendChild(a);
      }

      if (groupStart > 1) {
        prevBtn.disabled = false;
        prevBtn.style.opacity = '1';
        prevBtn.style.cursor = 'pointer';
        prevBtn.onclick = function(){
          window.location.href = pageUrl(Math.max(1, groupStart - groupSize));
        };
      } else {
        prevBtn.disabled = true;
        prevBtn.style.opacity = '.35';
        prevBtn.style.cursor = 'default';
      }

      if (groupEnd < totalPages) {
        nextBtn.disabled = false;
        nextBtn.style.opacity = '1';
        nextBtn.style.cursor = 'pointer';
        nextBtn.onclick = function(){
          window.location.href = pageUrl(groupStart + groupSize);
        };
      } else {
        nextBtn.disabled = true;
        nextBtn.style.opacity = '.35';
        nextBtn.style.cursor = 'default';
      }
    })();
