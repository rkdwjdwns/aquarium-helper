// service-worker.js
const CACHE_NAME  = 'aquarium-v2';
const OFFLINE_URL = '/offline/';

const STATIC_ASSETS = [
  '/static/icons/icon-192.png',
  'https://cdn.tailwindcss.com',
  'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
  'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
];

// 캐시하면 안 되는 경로 (CSRF 토큰 관련 페이지)
const NO_CACHE_PATHS = [
  '/accounts/login/',
  '/accounts/logout/',
  '/accounts/signup/',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS.map(url =>
        new Request(url, { mode: 'no-cors' })
      )).catch(() => {});
    })
  );
  self.skipWaiting();
});

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

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // POST 요청 → 캐시 안 함
  if (event.request.method !== 'GET') return;

  // API, 챗봇 → 캐시 안 함
  if (url.pathname.startsWith('/monitoring/api/') ||
      url.pathname.startsWith('/chatbot/')) return;

  // 로그인/로그아웃/회원가입 → 항상 네트워크 (캐시 절대 안 함)
  if (NO_CACHE_PATHS.some(p => url.pathname.startsWith(p))) {
    event.respondWith(fetch(event.request));
    return;
  }

  // HTML → Network First (캐시 저장 안 함)
  if (event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .catch(() =>
          caches.match(event.request).then(cached =>
            cached || caches.match(OFFLINE_URL)
          )
        )
    );
    return;
  }

  // 정적 파일 → Cache First
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok) {
          caches.open(CACHE_NAME).then(cache =>
            cache.put(event.request, response.clone())
          );
        }
        return response;
      });
    })
  );
});