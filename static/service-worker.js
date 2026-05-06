// service-worker.js
// 어항 도우미 PWA 서비스 워커

const CACHE_NAME    = 'aquarium-v1';
const OFFLINE_URL   = '/offline/';

// 캐시할 정적 파일 목록
const STATIC_ASSETS = [
  '/',
  '/monitoring/dashboard/',
  '/static/icons/icon-192.png',
  'https://cdn.tailwindcss.com',
  'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
  'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
];


// ── 설치: 정적 파일 캐시 ──────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS.map(url => {
        return new Request(url, { mode: 'no-cors' });
      })).catch(() => {});
    })
  );
  self.skipWaiting();
});


// ── 활성화: 구버전 캐시 삭제 ─────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME)
            .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});


// ── 요청 가로채기 ────────────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API 요청 — 캐시 안 함 (항상 서버에서)
  if (url.pathname.startsWith('/monitoring/api/') ||
      url.pathname.startsWith('/chatbot/') ||
      event.request.method !== 'GET') {
    return;
  }

  // HTML 페이지 — Network First (오프라인이면 캐시)
  if (event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        })
        .catch(() =>
          caches.match(event.request).then(cached =>
            cached || caches.match(OFFLINE_URL)
          )
        )
    );
    return;
  }

  // 정적 파일 — Cache First
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok) {
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, response.clone()));
        }
        return response;
      });
    })
  );
});
