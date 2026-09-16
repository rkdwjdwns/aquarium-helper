(() => {
  const current = document.currentScript;
  const baseUrl = current?.src ? current.src.substring(0, current.src.lastIndexOf('/') + 1) : '/static/js/monitoring/';

  function loadScript(name){
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = baseUrl + name;
      script.async = false;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`${name} 로드 실패`));
      document.head.appendChild(script);
    });
  }

  const baseReady = loadScript('dashboard-core.js')
    .then(() => loadScript('dashboard-live.js'))
    .catch(error => console.error('[dashboard loader]', error));

  const detailButton = document.getElementById('environmentDetailBtn');
  if(detailButton){
    detailButton.addEventListener('click', async event => {
      event.preventDefault();
      try{
        await baseReady;
        await loadScript('dashboard-detail.js');
        if(typeof window.openEnvironmentDetail === 'function'){
          window.openEnvironmentDetail();
        }
      }catch(error){
        console.error('[dashboard detail loader]', error);
      }
    }, {once:true});
  }
})();
